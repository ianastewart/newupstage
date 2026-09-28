"""Scrape performers and radio plays from the Upstage Theatre Company website."""

import difflib
import html
import re
from datetime import date
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

SITE_URL = "https://www.upstagetheatrecompany.co.uk/"
PERFORMERS_URL = "https://www.upstagetheatrecompany.co.uk/performers"
WRITERS_URL = "https://www.upstagetheatrecompany.co.uk/our-writers"
TEAM_URL = "https://www.upstagetheatrecompany.co.uk/copy-of-who-we-are"
RADIO_URL ="https://www.upstagetheatrecompany.co.uk/radio-plays"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UpstageScraper/1.0)"}


def _clean(text):
    """Collapse whitespace and strip zero-width characters left by the site builder."""
    return re.sub(r"\s+", " ", text.replace("﻿", "")).strip()


def _is_italic(tag):
    style = re.sub(r"\s+", "", (tag.get("style") or "").lower())
    return tag.name in ("i", "em") or (tag.name == "span" and "font-style:italic" in style)


def _link_open_tag(href):
    """An <a> start tag for a link on the site, or None if it isn't a web or email link."""
    url = urljoin(SITE_URL, href.strip())  # "/radio-plays#airbnb" -> the Upstage site
    if urlsplit(url).scheme not in ("http", "https", "mailto"):
        return None
    external = urlsplit(url).netloc not in ("", urlsplit(SITE_URL).netloc)
    new_tab = ' target="_blank" rel="noopener"' if external else ""
    return f'<a href="{html.escape(url)}"{new_tab}>'


def _inline_html(node, italic=False):
    """
    A text block as safe HTML: text is escaped, italic spans (and <i>/<em>) become <i>,
    links are kept (made absolute), <br> becomes a space and every other tag is dropped,
    keeping its text.
    """
    if isinstance(node, NavigableString):
        return "" if isinstance(node, Comment) else html.escape(str(node), quote=False)
    if node.name == "br":
        return " "
    inner_italic = not italic and _is_italic(node)
    inner = "".join(_inline_html(child, italic or inner_italic) for child in node.children)
    if inner_italic and inner.strip():
        inner = f"<i>{inner}</i>"
    if node.name == "a" and node.get("href") and _clean(inner):
        open_tag = _link_open_tag(node["href"])
        if open_tag:
            inner = f"{open_tag}{inner}</a>"
    return inner


# Adjacent links to the same page, e.g. a Spotlight number split into "1" + "173-5616-0196".
_SPLIT_LINK_RE = re.compile(r'(<a href="([^"]+)"[^>]*>)(.*?)</a>\s*<a href="\2"[^>]*>')


def _html_paragraphs(block):
    """
    Split a site text block into paragraphs of inline HTML. Blocks use <p> for paragraphs,
    or text with <div>s for the later paragraphs ("Karen has...<div>Karen had been...</div>").
    """
    if block.find("p"):
        parts = block.find_all("p")
    else:
        parts, run = [], []
        for child in block.children:
            if isinstance(child, Tag) and child.name == "div":
                parts += [run, [child]]
                run = []
            else:
                run.append(child)
        parts.append(run)
    paragraphs = []
    for part in parts:
        nodes = part if isinstance(part, list) else [part]
        paragraph = _clean("".join(_inline_html(node) for node in nodes))
        paragraph = re.sub(r"<i>\s*</i>", "", paragraph).strip()
        while _SPLIT_LINK_RE.search(paragraph):
            paragraph = _SPLIT_LINK_RE.sub(r"\1\3", paragraph)
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs


def _parse_performer(row):
    """Extract one performer from a `div.dmDefaultListContentRow` on the performers page."""
    heading = row.find("h3")
    name = _clean(heading.get_text(" ")) if heading else _clean(row.get("data-anchor", ""))
    first_name, _, last_name = name.partition(" ")

    # Biography: every text block in the row except the name heading, as HTML paragraphs.
    paragraphs = []
    for block in row.select(".dmNewParagraph"):
        if block.find("h3") or "dmDefaultH3" in (block.get("class") or []):
            continue
        paragraphs.extend(_html_paragraphs(block))

    image = row.find("img")
    return {
        "anchor": row.get("id"),
        "name": name,
        "first_name": first_name,
        "last_name": last_name,
        "biography": "\n".join(f"<p>{paragraph}</p>" for paragraph in paragraphs),
        "image_url": image.get("src") if image else None,
    }


def scrape_performers(url=PERFORMERS_URL):
    """
    Fetch the performers page and return a list of performer dicts.

    If the URL has an anchor (e.g. ".../performers#JulietBagnall") only that
    performer is returned. Each dict has: anchor, name, first_name, last_name,
    biography, image_url.
    """
    page_url, anchor = urldefrag(url)
    response = requests.get(page_url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    if anchor:
        row = soup.find(id=anchor)
        return [_parse_performer(row)] if row else []

    # Only some rows have a data-anchor, so take every list row with a name heading.
    rows = [row for row in soup.select("div.dmDefaultListContentRow") if row.find("h3")]
    return [_parse_performer(row) for row in rows]


# --- Writers -----------------------------------------------------------------


def scrape_writers(url=WRITERS_URL):
    """
    Fetch the writers page and return a list of writer dicts, in the same shape as
    scrape_performers. The page uses the same layout as the performers page, but
    an entry can name several writers ("Sarah Edgar & Helen Stephenson"): each gets
    the shared biography, and the photo goes to the writer named in its file name.
    """
    writers = []
    for entry in scrape_performers(url):
        name = _clean(re.sub(r"\(.*?\)", "", entry["name"]))  # "William (Billy) McKay"
        names = [part for part in re.split(r"\s*&\s*|\s+and\s+", name) if part]
        image_url = entry["image_url"] or ""
        for index, name in enumerate(names):
            first_name, _, last_name = name.partition(" ")
            if len(names) == 1:
                photo = image_url
            else:
                photo = image_url if last_name and last_name.lower() in unquote(image_url).lower() else ""
            writers.append({
                **entry,
                "anchor": entry["anchor"] if len(names) == 1 else f"{entry['anchor']}-{index + 1}",
                "name": name,
                "first_name": first_name,
                "last_name": last_name,
                "image_url": photo or None,
            })
    return writers


# --- Team ---------------------------------------------------------------------

# Words in a team member's job title and the roles they map to.
TITLE_ROLES = {
    r"producer": "Producer",
    r"director": "Director",
    r"production manager": "Production Manager",
    r"pr|marketing|publicity": "Marketing",
    r"web": "Web admin",
    r"edit(?:ing|or)": "Editor",
    r"photograph(?:y|er)": "Photographer",
    r"sound": "Sound",
    r"backstage|stage manage(?:r|ment)": "Backstage",
    r"props?": "Prop maker",
    r"costumes?|costumer": "Costumer",
}
# Team members listed without a job title, with roles taken from their biographies.
UNTITLED_TEAM_ROLES = {
    "Morayo Lasebikan": ["Costumer"],  # costume design
    "Jonathan Palmer": ["Photographer"],  # camera operator
}


def title_roles(title):
    """'Director / Production Manager / PR' -> ['Director', 'Production Manager', 'Marketing']."""
    return [role for pattern, role in TITLE_ROLES.items() if re.search(rf"\b(?:{pattern})\b", title, re.IGNORECASE)]


def scrape_team(url=TEAM_URL):
    """
    Fetch the "who we are" page and return a list of team member dicts, in the same
    shape as scrape_performers plus `title` (e.g. "Photography and Sound") and
    `roles` (role names derived from the title).
    """
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    team = []
    for row in soup.select("div.dmDefaultListContentRow"):
        headings = row.find_all("h3")
        if not headings:
            continue
        member = _parse_performer(row)
        member["title"] = _clean(headings[1].get_text(" ")) if len(headings) > 1 else ""
        member["roles"] = title_roles(member["title"]) or UNTITLED_TEAM_ROLES.get(member["name"], [])
        team.append(member)
    return team

# --- Radio plays -------------------------------------------------------------

# Credit words that map to production team roles. Other credit words (recorded,
# narrated, ...) only mark where a name ends; those credits stay in the description.
CREDIT_ROLES = {
    "written": "Writer", "directed": "Director", "edited": "Editor",
    "writer": "Writer", "director": "Director", "editor": "Editor", "by": "Writer",
}
_CREDIT_WORD = r"(?:written|directed|edited|recorded|narrated|read|produced|engineered|performed|abridged|assisted)"
CREDIT_RE = re.compile(
    rf"\b(?P<words>{_CREDIT_WORD}(?:\s*(?:,|and|&)\s*{_CREDIT_WORD})*)\s+b[yr]\b\s*:?"  # "Written and directed by" ("br" typo)
    r"|\b(?P<label>Writer|Director|Editor)s?\s*:"  # "Writer: ..."
    r"|^\s*(?:A\s[\w ]{0,30}?\s)?(?P<by>By)\b",  # "By Peter Shaw", "A panto for radio by ..."
    re.IGNORECASE | re.MULTILINE,
)
CAST_RE = re.compile(r"\b(?:Starring|Staring|Featuring)\b\s*:?|^\s*Cast\b\s*:?|\bCast\s*:", re.IGNORECASE | re.MULTILINE)
AS_RE = re.compile(r"\s+as(?:\s+|(?=[A-Z]))")
NAME_RE = re.compile(r"^[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*){0,3}$")  # "Pip Rolls", "Darren R Partridge"
_LINE_BREAK = "\x00"


# Names written differently (or wrongly) on the radio page, and who they really are.
NAME_ALIASES = {
    "Edgar Stephenson": ["Sarah Edgar", "Helen Stephenson"],  # the writing duo, by surnames
    "Edgar Stevenson": ["Sarah Edgar", "Helen Stephenson"],
    "Darren R Partridge": ["Darren Partridge"],
    "Evin Wheeler": ["Evon Wheeler"],
    "John Williams": ["John Louis Williams"],  # as he's listed on the performers page
}
# Credits that aren't people ("Written by Upstate [Upstage] and AI assistance").
NOT_PEOPLE = {"Upstate", "Upstage"}


def canonical_names(name):
    """The people a name on the page refers to: fixes aliases and typographic apostrophes."""
    name = _clean(name).replace("’", "'")
    if name in NOT_PEOPLE:
        return []
    return NAME_ALIASES.get(name, [name])


def match_name(name, known_names, cutoff=0.85):
    """Return the known name that `name` refers to (ignoring case and small typos), or None."""
    lookup = {known.lower(): known for known in known_names}
    close = difflib.get_close_matches(_clean(name).lower(), lookup, n=1, cutoff=cutoff)
    return lookup[close[0]] if close else None


def _row_lines(row, title):
    """Text lines of a play row: <br> and paragraphs start new lines; the title is skipped."""
    lines = []
    for block in row.select(".dmNewParagraph"):
        if block.find("h3"):
            continue
        for part in block.find_all(["p", "li"]) or [block]:
            for line in part.get_text().split(_LINE_BREAK):
                line = _clean(line)
                if line.strip(".") and line != title and not line.lower().startswith("visit the gallery"):
                    lines.append(line)
    return lines


def _background_images(soup):
    """Map each Duda `u_...` CSS class to its background image URL."""
    css = "\n".join(style.get_text() for style in soup.find_all("style"))
    pattern = r"\.(u_[\w-]+)\s*\{[^}]*?background-image:\s*url\(\s*['\"]?([^'\")]+)"
    # Collapse "//" in the path: the CDN redirects "cdn-website.com//e4129320/..." to a broken host.
    return {css_class: re.sub(r"(?<=[^:/])/{2,}", "/", url) for css_class, url in re.findall(pattern, css)}


def _split_actors(text):
    """'Jean Anderson and Sarah Edgar' -> two actors; 'Paul' -> one."""
    text = re.sub(r"^(?:and|&)\s+", "", text.strip(" ,"), flags=re.IGNORECASE)
    parts = [part.strip() for part in re.split(r"\s+and\s+|\s*&\s*", text)]
    if len(parts) > 1 and all(len(part.split()) >= 2 for part in parts):
        return parts
    return [text] if text else []


def _take_name_suffix(words, known_names):
    """Split the known person's name that best matches the end of `words`, or return None."""
    best = None
    for size in (3, 2):
        if len(words) <= size:
            continue
        candidate = " ".join(words[-size:])
        known = match_name(candidate, known_names)
        if known:
            score = difflib.SequenceMatcher(None, candidate.lower(), known.lower()).ratio()
            # Prefer the closer match, so "Suit 3 Matthew Baylis" splits as "Suit 3" + "Matthew Baylis".
            if best is None or score > best[0]:
                best = (score, words[:-size], candidate)
    return (best[1], best[2]) if best else None


def _split_character_and_next_actor(segment, known_names):
    """'Amy Sarah Edgar' (a character then the next actor, run together) -> ('Amy', 'Sarah Edgar')."""
    words = segment.split()
    found = _take_name_suffix(words, known_names)
    if not found:
        # Unknown actor: assume a two-word name.
        return (" ".join(words[:-2]), " ".join(words[-2:])) if len(words) > 2 else ("", segment)
    rest, actor = found
    # "... Jean Anderson and Sarah Edgar as ..." -> both actors share the next character.
    if len(rest) > 1 and rest[-1].lower() in ("and", "&"):
        earlier = _take_name_suffix(rest[:-1], known_names)
        if earlier:
            rest, actor = earlier[0], f"{earlier[1]} and {actor}"
    return " ".join(rest), actor


def _parse_cast_line(line, known_names):
    """Parse 'Actor as Character' entries, including several run together on one line."""
    parts = AS_RE.split(line.strip(" :"))
    if len(parts) < 2:
        return []
    entries, actors_text = [], parts[0]
    for index, segment in enumerate(parts[1:], start=1):
        if index < len(parts) - 1:
            character, next_actors = _split_character_and_next_actor(segment, known_names)
        else:
            character, next_actors = segment, ""
        character = re.sub(r"\s+(?:and|&)$", "", character.strip(" ,.;"), flags=re.IGNORECASE)
        actors = _split_actors(actors_text)
        if actors and character:
            entries.append({"actors": actors, "character": character})
        actors_text = next_actors
    return entries


def _is_cast_line(line, known_names):
    """A line outside a cast section that starts with a person's name followed by ' as '."""
    if re.match(r"^[A-Z][\w'’-]+(?: [A-Z][\w'’-]+){1,2}\s+as\s", line):
        return True  # e.g. "Helen Coverdale as Eileen"
    match = re.match(r"^(.{3,40}?)\s+as\s", line)
    return bool(match and match_name(match.group(1), known_names))


def _parse_credits(text):
    """Find Writer/Director/Editor credits. Returns (credits, spans of fully captured credit text)."""
    credits, spans = [], []
    matches = list(CREDIT_RE.finditer(text))
    for index, match in enumerate(matches):
        # A credit's names run to the next credit or the end of the line.
        ends = [text.find("\n", match.end()), len(text)]
        if index + 1 < len(matches):
            ends.append(matches[index + 1].start())
        end = min(e for e in ends if e >= 0)
        keyword = match.group("words") or match.group("label") or match.group("by")
        words = [w for w in re.findall(r"\w+", keyword.lower()) if w != "and"]
        roles = list(dict.fromkeys(CREDIT_ROLES[w] for w in words if w in CREDIT_ROLES))
        parts = [n.strip(" .,") for n in re.split(r"\s*(?:,|&|\band\b)\s*", text[match.end():end]) if n.strip(" .,")]
        names = [part for part in parts if NAME_RE.match(part)]
        credits.extend({"role": role, "name": name} for role in roles for name in names)
        # Remove the credit from the description only if it was entirely roles and names:
        # "Written and narrated by ..." or "written by X, is about the journey" stay as text.
        if roles and names and len(names) == len(parts) and all(w in CREDIT_ROLES for w in words):
            spans.append((match.start(), end))
    return credits, spans


def _parse_play(row, title, background_images, page_url, known_names):
    text = "\n".join(_row_lines(row, title))
    cast_match = CAST_RE.search(text)
    main, cast_text = (text[: cast_match.start()], text[cast_match.end():]) if cast_match else (text, "")

    credits, spans = _parse_credits(main)
    for start, end in reversed(spans):
        main = main[:start] + main[end:]

    description, cast = [], []
    for line in main.split("\n"):
        line = line.strip(" ,")
        if not line.strip("."):
            continue
        if _is_cast_line(line, known_names):
            cast.extend(_parse_cast_line(line, known_names))
        else:
            description.append(line)
    for line in cast_text.split("\n"):
        entries = _parse_cast_line(line, known_names)
        if entries:
            cast.extend(entries)
        elif line.strip(" :."):
            description.append(line.strip())

    image_url = None
    for element in [row, *row.find_all(True)]:
        for css_class in element.get("class") or []:
            image_url = image_url or background_images.get(css_class)

    listen_url = None
    for link in row.select("a.dmButtonLink"):
        if "listen" in link.get_text().lower() and link.get("href"):
            listen_url = _fix_listen_url(urljoin(page_url, link["href"]), title)
            break

    credits = [
        dict(credit)
        for credit in dict.fromkeys(
            (("role", c["role"]), ("name", name)) for c in credits for name in canonical_names(c["name"])
        )
    ]
    cast = [
        {**entry, "actors": [name for actor in entry["actors"] for name in canonical_names(actor)]}
        for entry in cast
    ]

    return {
        "title": title,
        "description": "\n".join(description),
        "credits": credits,
        "cast": [entry for entry in cast if entry["actors"]],
        "listen_url": listen_url,
        "broadcast_date": broadcast_date(listen_url) or UNKNOWN_BROADCAST_DATE,
        "image_url": image_url,
    }


# Used for plays whose listen link has no date in it (older plays on the site's own listen-now page).
UNKNOWN_BROADCAST_DATE = date(2021, 1, 1)
MP3_DATE_RE =re.compile(r"(\d{4}-\d{2}-\d{2})[A-Za-z]*\.mp3$")  # "...2024-03-15TX.mp3" too


def broadcast_date(listen_url):
    """The broadcast date from a podcast URL ending in '...2026-05-22.mp3', or None."""
    match = MP3_DATE_RE.search(listen_url or "")
    try:
        return date.fromisoformat(match.group(1)) if match else None
    except ValueError:
        return None


def _fix_listen_url(url, title):
    """
    Some links on the page are two podcast URLs pasted together
    ('.../UpstageSurrey-Evolution2025-10-03.mp3ts/UpstageSurrey-AlfredTheGreat2026-03-20.mp3'):
    keep the one whose file name best matches the play's title.
    """
    parts = [part for part in url.split(".mp3")[:-1] if re.search(r"\d{4}-\d{2}-\d{2}[A-Za-z]*$", part)]
    if len(parts) < 2:
        return url
    folder = parts[0].rsplit("/", 1)[0]
    squash = lambda text: re.sub(r"[^a-z]", "", text.lower().replace("upstagesurrey", ""))
    best = max(
        (part.rsplit("/", 1)[-1] for part in parts),
        key=lambda name: difflib.SequenceMatcher(None, squash(name), squash(title)).ratio(),
    )
    return f"{folder}/{best}.mp3"


def scrape_radio(url=RADIO_URL, known_names=()):
    """
    Fetch the radio plays page and return a list of play dicts with: title,
    description, credits ([{role, name}] for Writer/Director/Editor), cast
    ([{actors, character}]), listen_url, broadcast_date (from the podcast file
    name) and image_url.

    `known_names` (e.g. everyone in the database) helps split cast lists where
    several "Actor as Character" entries are run together, and tolerates typos.
    """
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    background_images = _background_images(soup)
    for br in soup.find_all("br"):
        br.replace_with(_LINE_BREAK)

    plays = []
    for heading in soup.find_all("h3"):
        row = heading.find_parent(class_="dmRespRow")
        title = _clean(heading.get_text().replace(_LINE_BREAK, " "))
        if row and title:
            plays.append(_parse_play(row, title, background_images, url, known_names))
    return plays


if __name__ == "__main__":
    for performer in scrape_performers("https://www.upstagetheatrecompany.co.uk/performers#JulietBagnall"):
        print(performer["name"], "-", performer["image_url"])
        print(performer["biography"])
