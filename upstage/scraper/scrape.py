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


BROOKLANDS_PLAYHOUSE_URL = "https://www.brooklandsradio.co.uk/playhouse.html"
# A play's heading starts "Upstage Surrey presents - " (the dash is sometimes missing, and "presents" sometimes has a
# capital) or "Upstage Theatre Company - ". Plays whose headings start any other way are not Upstage's, and are ignored.
_PLAY_HEADING_RE = re.compile(r"^(?:Upstage Surrey\s+presents|Upstage Theatre Company)\s*[-–—]?\s*", re.IGNORECASE)
_PLAY_TEXT_START = "A play for radio -"
_LISTEN_MARKER = "Click to listen:"
# " 18th September 2026" on the end of a heading (sometimes with no space before it, or a dash).
_HEADING_DATE_RE = re.compile(r"\s*[-–—]?\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s*\d{4})\s*$")
# "Part 2": a play in several parts. A title ends where this begins, as it does at the date.
_PART = r"part\s+(?:\d+|[ivx]+|one|two|three|four|five|six)\b"
_TITLE_PART_RE = re.compile(rf"\s+({_PART}).*$", re.IGNORECASE)


def _brooklands_list_html(url=BROOKLANDS_PLAYHOUSE_URL):
    """
    The HTML of the Brooklands Radio Playhouse list. The playhouse page loads its list in an iframe,
    so this fetches the page, then the iframe's address.
    """
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    iframe = BeautifulSoup(response.content, "html.parser").find("iframe", src=True)
    if iframe is None:
        return response.text  # the list is on the page itself
    list_response = requests.get(urljoin(url, iframe["src"]), headers=HEADERS, timeout=30)
    list_response.raise_for_status()
    list_response.encoding = list_response.encoding or "utf-8"
    return list_response.text


def _split_title_date(heading):
    """
    A heading's title, date and part: the title ends at the first number (the date) or "Part".

        "The Good Guard 18th September 2026"  ->  ("The Good Guard", "18th September 2026", "")
        "Cinderella Part 2 3rd January 2026"  ->  ("Cinderella", "3rd January 2026", "Part 2")
    """
    date_text = ""
    match = _HEADING_DATE_RE.search(heading)
    if match:
        heading, date_text = heading[: match.start()].strip(), _clean(match.group(1))
    part = ""
    match = _TITLE_PART_RE.search(heading)
    if match:
        heading, part = heading[: match.start()].strip().rstrip("-" + chr(0x2013) + chr(0x2014) + " "), _clean(match.group(1))
    return heading, date_text, part


def _brooklands_entries(list_html):
    """
    Every play in the Brooklands Radio Playhouse list. Each entry looks like

        <b><u>Upstage Surrey presents - The Good Guard 18th September 2026</u></b><br/>
        A play for radio - The Good Guard -Define Good. Starring ... <br/>
        Click to listen: <u><a href="https://....mp3">....mp3</a></u>

    and is returned as a dict: title, date, part ("Part 2", or ""), text (what's between "A play for radio - " and
    "Click to listen:"; the whole of it if the entry doesn't start "A play for radio -") and url (or None).

    The heading must start "Upstage Surrey presents - " or "Upstage Theatre Company - ": any other
    play on the page is ignored.
    """
    soup = BeautifulSoup(list_html, "html.parser")
    entries = []
    for heading in soup.find_all("b"):
        heading_text = _clean(heading.get_text())
        prefix = _PLAY_HEADING_RE.match(heading_text)
        if not prefix:
            continue  # not an Upstage play
        # Everything after the heading, up to the listen link, is the entry's text.
        parts, link = [], None
        for node in heading.next_siblings:
            if isinstance(node, Tag):
                if node.name == "b":  # the next entry
                    break
                link = node.find("a", href=True) if node.name != "a" else node
                if link is not None:
                    break
            if isinstance(node, NavigableString):
                parts.append(str(node))
        title, date_text, part = _split_title_date(heading_text[prefix.end():].strip())
        text = _clean(" ".join(parts)).split(_LISTEN_MARKER)[0]
        if _PLAY_TEXT_START in text:
            text = text.split(_PLAY_TEXT_START, 1)[1]
        entries.append({
            "title": title, "date": date_text, "part": part, "text": _clean(text), "url": link["href"] if link is not None else None,
        })
    return entries


def parse_brooklands_play(list_html, name):
    """
    Find a play in the Brooklands Radio Playhouse list (see _brooklands_entries for the layout).
    Returns (text, url), where text is what's between "A play for radio - " and "Click to listen:",
    or None if there's no entry for the play. The title is matched ignoring case, and a title followed
    by a date ("The Good Guard 18th September 2026") counts; failing that, any entry whose title contains the name.
    """
    wanted = _clean(name).lower()
    entries = _brooklands_entries(list_html)
    for matches in (lambda title: title.lower() == wanted, lambda title: wanted in title.lower()):
        for entry in entries:
            if matches(entry["title"]) and entry["url"]:
                return entry["text"], entry["url"]
    return None


def find_brooklands_play(name):
    """
    Look a radio play up on the Brooklands Radio Playhouse page, in the list that starts
    "Upstage Surrey presents - ". Returns (text, url): the text between "A play for radio - " and
    "Click to listen:", and the listen URL that follows; or None if the play isn't listed.
    """
    return parse_brooklands_play(_brooklands_list_html(), name)


# Where a play's blurb stops and its credits begin: a credit or cast list marker...
_BLURB_END_RE = re.compile(
    r"\b(?:written|witten|directed|irected|edited|narrated|performed|produced|engineered|starring|staring|featuring"
    r"|writer|director|editor)\b|\bcast(?:\s+members)?\s*:|\bread\s+by\b",
    re.IGNORECASE,
)
# ...or a cast list with no marker: "Mark Bradford as Roger", "Rita played by Mills Ross",
# "Man - played by Dave Andrew", "Sara Robinson played Maureen".
_UNMARKED_CAST_RE = re.compile(r"(?:\b[A-Z][\w'’-]*\s+){1,3}(?:[-–—]\s*)?(?:as|played(?:\s+by)?)\s+[A-Z]")
# "A one-hour radio play" or "The role of" left on the end of the blurb, as the lead-in to "written by ..." or a cast list.
_TRAILING_LEAD_IN_RE = re.compile(
    r"(?:(?<=[.!?])|^)\s*An?\s+(?:[\w-]+\s+){0,3}(?:play|panto|drama|monologue|comedy)(?:\s+for\s+radio)?\s*$"
    r"|\s*\b(?:the\s+)?roles?\s+of\s*$",
    re.IGNORECASE,
)


def _loose(text):
    """Lower case, with curly and mangled apostrophes as plain ones, for matching titles."""
    return text.lower().replace("’", "'").replace("�", "'")


def parse_brooklands_blurb(text, title):
    """
    The blurb in a Brooklands play's text: what follows the "-" after the play's name, up to where a cast
    list, writer or director appears. It may be empty (there may be no "-" after the name, or the credits
    may come straight after it).

        "The Good Guard -Define Good. Starring Ray James as ..."  ->  "Define Good."
        "The Good Guard Starring Ray James as ..."                ->  ""
    """
    text = _clean(text)
    title = _clean(title)
    # The site's apostrophes are sometimes mangled ("Life�s"), so match them loosely; the swaps keep the length.
    position = _loose(text).find(_loose(title)) if title else -1
    after = text[position + len(title):] if position >= 0 else None
    # The "-" must come straight after the name (or after its "Part 2").
    dash = re.match(rf"\s*(?:{_PART}\s*)?[-–—]\s*", after, re.IGNORECASE) if after is not None else None
    if not dash:
        return ""
    blurb = after[dash.end():]
    cuts = [m.start() for m in (_BLURB_END_RE.search(blurb), _UNMARKED_CAST_RE.search(blurb)) if m]
    if cuts:
        blurb = blurb[: min(cuts)]
    blurb = _TRAILING_LEAD_IN_RE.sub("", blurb)
    return blurb.strip().rstrip(",;-–— ").strip()


# Words that start the credits that follow a cast list ("Written by...", "An Upstage Surrey Production").
_CAST_END_RE = re.compile(
    r"\b(?:written|witten|directed|irected|edited|editing|engineered|recorded|music|sounds?|produced|assisted"
    r"|an\s+upstage|an\s+upsatge|abridged|narrated)\b",
    re.IGNORECASE,
)
# Where a cast list starts, when it has a marker: "Starring ...", "featuring: ...", "Cast: ...".
_CAST_START_RE = re.compile(r"\b(?:starring|staring|featuring|featuirng|featured)\b\s*:?|\bcast(?:\s+members)?\s*:", re.IGNORECASE)
_PLAYED_BY_RE = re.compile(r"^(?:the\s+role\s+of\s+)?(?P<character>.+?)\s*[-–—]?\s*played\s+by\s+(?P<actor>.+)$", re.IGNORECASE)
_PLAYED_RE = re.compile(r"^(?P<actor>.+?)\s+played\s+(?P<character>.+)$", re.IGNORECASE)
_NEXT_PLAYED_RE = re.compile(r"\s+and\s+(?=(?:[A-Z][\w'’-]*\s+){1,3}played\b)")


def _played_to_as(item):
    """"Rita played by Mills Ross" and "Sara Robinson played Maureen" -> "Mills Ross as Rita", "Sara Robinson as Maureen"."""
    match = _PLAYED_BY_RE.match(item)
    if match:
        return f"{match.group('actor').strip()} as {match.group('character').strip()}"
    match = _PLAYED_RE.match(item)
    if match:
        return f"{match.group('actor').strip()} as {match.group('character').strip()}"
    return item


def parse_brooklands_cast(text, known_names=()):
    """
    The cast listed in a Brooklands play's text, as [{"actors": [...], "character": ...}] (possibly empty).

    Understands "Actor as Character" (after "Starring", "Featuring", "Cast:" or with no marker), and
    "Character played by Actor" / "Actor played Character". The cast list ends where credits begin ("Written by ...").
    The site cuts its text off, often in the middle of the cast list: then the last item (which may be
    incomplete) is dropped. Entries that don't look like a person and a character are skipped.
    """
    text = _clean(text)
    start = None
    marker = _CAST_START_RE.search(text)
    unmarked = _UNMARKED_CAST_RE.search(text)
    if marker and (unmarked is None or marker.start() <= unmarked.start()):
        start = marker.end()
    elif unmarked:
        start = unmarked.start()
    if start is None:
        return []

    end = _CAST_END_RE.search(text, start)
    span = text[start:end.start()] if end else text[start:]
    # Without a credit after it, the list is complete only if the text ends with a full stop.
    truncated = end is None and not text.rstrip().endswith(".")

    items = []
    for item in re.split(r"\s*,\s*", span.strip(" .:,")):
        items.extend(_NEXT_PLAYED_RE.split(item))
    if truncated and len(items) > 1:
        items = items[:-1]  # the last item may have been cut off
    elif truncated:
        return []
    line = ", ".join(_played_to_as(item.strip()) for item in items if item.strip())

    cast = []
    for entry in _parse_cast_line(line, known_names):
        character = entry["character"].strip(" ,.;")
        actors = [name for actor in entry["actors"] for name in canonical_names(actor)]
        # Skip anything that isn't a person's name and a character ("Elf and Police People are Marie", or
        # "DCI Hepper, Typhinia Mulford and Sylvia", where a name has run into the character).
        if (
            character and len(character) <= 40 and " are " not in character
            and not re.search(r"[A-Z][\w'\u2019-]+\s+[A-Z][\w'\u2019-]+\s+and\b", character)
            and actors and all(NAME_RE.match(actor) for actor in actors)
        ):
            cast.append({"actors": actors, "character": character})
    return cast


# Credits in a Brooklands play's text: "Written and directed by Pip Rolls", "edits by Darren Partridge", "A play for radio by Peter Bridge".
# Only writing, directing and editing become roles; the other verbs are here so that "Directed and Produced by X" reads properly.
_CREDIT_VERB = (
    r"(?:written|witten|writing|directed|irected|edited|edits|editing"
    r"|produced|engineered|recorded|narrated|performed|abridged)"
)
_CREDITS_BY_RE = re.compile(rf"\b(?P<verbs>{_CREDIT_VERB}(?:\s*(?:,|and|&)\s*{_CREDIT_VERB})*)\s+by\b", re.IGNORECASE)
# "by" with no verb is the writer: "A panto for radio by Edgar Stephenson", "...at Christmas. By Clive Foskett",
# "High Infidelity by Peter Bridge" (the first sentence of the text).
_BARE_BY_RE = re.compile(
    r"(?:(?<=radio)|(?<=play)|(?<=panto)|(?<=monologue)|(?<=[.!?]))(?P<by>\s+by\s+)"
    r"|^[A-Z][^.!?,]{0,60}?(?<!read)(?P<by2>\s+by\s+)",  # "Read by Emma White" is not a writer
    re.IGNORECASE,
)
# Where a credit's names stop (besides the next credit): a cast list, other credits, or the end of the sentence.
_NAMES_END_RE = re.compile(
    r"\b(?:read\s+by|music|sounds?|with|assisted|an\s+upstage|an\s+upsatge)\b|[.!?](?:\s|$)",
    re.IGNORECASE,
)
_CREDIT_ROLE_BY_VERB = {
    "written": "Writer", "witten": "Writer", "writing": "Writer",
    "directed": "Director", "irected": "Director",
    "edited": "Editor", "edits": "Editor", "editing": "Editor",
}


def parse_brooklands_credits(text, title=""):
    """
    The writer, director and editor credits in a Brooklands play's text: [{"role": "Writer", "name": "Pip Rolls"}, ...].

    Understands "Written by A and B", "Written and directed by A", "Directed by A, edits by B", and "by A" (the
    writer) after "for radio", at the start of a sentence, or after the title. A credit's names stop at the next credit,
    a cast list ("starring ...", "X as Y") or the end of the sentence. The site cuts its text off, sometimes in the
    middle of a name: the last name is dropped then. "Upstage" and other non-people are skipped.
    """
    text = _clean(text)
    found = []  # (start, end of the "by", roles)
    for match in _CREDITS_BY_RE.finditer(text):
        verbs = re.findall(_CREDIT_VERB, match.group("verbs"), re.IGNORECASE)
        roles = list(dict.fromkeys(_CREDIT_ROLE_BY_VERB[v.lower()] for v in verbs if v.lower() in _CREDIT_ROLE_BY_VERB))
        found.append((match.start(), match.end(), roles))
    for match in _BARE_BY_RE.finditer(text):
        by_start = match.start("by") if match.group("by") else match.start("by2")
        by_end = match.end("by") if match.group("by") else match.end("by2")
        if not any(start <= by_start < end for start, end, _ in found):
            found.append((by_start, by_end, ["Writer"]))
    found.sort()

    credits = []
    for index, (_, names_start, roles) in enumerate(found):
        if not roles:
            continue  # "Narrated by ...", "Produced by ...": not a team role
        ends = [len(text)]
        if index + 1 < len(found):
            ends.append(found[index + 1][0])
        for pattern in (_NAMES_END_RE, _CAST_START_RE, _UNMARKED_CAST_RE):
            cut = pattern.search(text, names_start)
            if cut:
                # A sentence's full stop ends the names but isn't part of the next text.
                ends.append(cut.start())
        end = min(ends)
        # "Upstage Surrey by Peter Bridge": a "by" inside the names separates them, too.
        names = [n.strip(" ,.;:") for n in re.split(r"\s*(?:,|&|\band\b|\bby\b)\s*", text[names_start:end]) if n.strip(" ,.;:")]
        # Cut off in the middle of a name: the text ran out before the credit ended.
        if end == len(text) and not text.rstrip().endswith((".", "!", "?")) and names:
            names = names[:-1]
        for name in names:
            name = re.sub(r"^by\s+", "", name, flags=re.IGNORECASE)  # "by By Upstage and AI assistance"
            for person in canonical_names(name):
                if (
                    NAME_RE.match(person) and len(person) >= 3  # not "A" or "AI"
                    and not person.lower().startswith(("upstage", "ai "))
                ):
                    credits.extend({"role": role, "name": person} for role in roles)
    return list({(c["role"], c["name"]): c for c in credits}.values())


def brooklands_plays(list_html=None):
    """
    Every play in the Brooklands Radio Playhouse list, latest first as on the page: a list of dicts with
    title, date, part, text (the blurb, possibly empty), raw_text (all of the entry's text) and listen_url.
    """
    entries = _brooklands_entries(list_html if list_html is not None else _brooklands_list_html())
    return [
        {
            "title": entry["title"],
            "date": entry["date"],
            "part": entry["part"],
            "raw_text": entry["text"],
            "text": parse_brooklands_blurb(entry["text"], entry["title"]),
            "listen_url": entry["url"],
        }
        for entry in entries
    ]


def print_brooklands_plays():
    """Read every play from the Brooklands Radio Playhouse page and print its title, text and listen URL."""
    plays = brooklands_plays()
    for play in plays:
        print(f"Title: {play['title']}")
        print(f"Text:  {play['text']}")
        print(f"Listen: {play['listen_url']}")
        print()
    print(f"{len(plays)} plays")


if __name__ == "__main__":
    for performer in scrape_performers("https://www.upstagetheatrecompany.co.uk/performers#JulietBagnall"):
        print(performer["name"], "-", performer["image_url"])
        print(performer["biography"])
