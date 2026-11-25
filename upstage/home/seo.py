"""
Search engine and link preview tags for the public pages: the canonical address, a description, and the Open Graph /
Twitter card values. `seo()` builds them for a page; the public base template writes them into the page's head.
Pages that don't give their own get the site's defaults (see `default_seo`).
"""

import html
import json
import re

from django.conf import settings
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from backstage.context_processors import navbar_logo

SITE_NAME = "Upstage Surrey"


def plain_text(value, limit=155):
    """HTML as plain text for a description: tags removed, spaces tidied, cut at a word to `limit` characters at most."""
    # Paragraphs, breaks and the like separate words; inline tags (bold, links) don't: "<b>panto</b>." is "panto."
    text = re.sub(r"</?(?:p|br|div|li|ul|ol|h[1-6]|tr|td|th|blockquote)(?=[\s/>])[^>]*>", " ", value or "", flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", text))).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "…"


def seo(request, title="", description="", image=None, og_type="website", noindex=False, canonical_path=None, json_ld=None):
    """
    The page's tags as a dict for the `seo` template variable.

    `image` is a backstage Image (the site logo if none is given); `canonical_path` is the address search engines should
    use for this content when it is not the page's own path; `noindex` keeps the page out of search results;
    `json_ld` is structured data (a dict or a list of them) for search engines, see `script_json`.
    """
    image = image or navbar_logo(request)["navbar_logo"] or None
    return {
        "site_name": SITE_NAME,
        "title": title or SITE_NAME,
        "description": plain_text(description) or settings.SITE_DESCRIPTION,
        # The address without any query (?production=... and the like): the same page however it was reached.
        "canonical": request.build_absolute_uri(canonical_path or request.path),
        "image": request.build_absolute_uri(image.image.url) if image and image.image else "",
        "type": og_type,
        "noindex": noindex,
        "json_ld": script_json(json_ld) if json_ld else "",
    }


def default_seo(request):
    """Context processor: `seo` for pages whose view doesn't give its own (worked out only if a template uses it)."""
    return {"seo": SimpleLazyObject(lambda: seo(request))}


def script_json(data):
    """
    `data` as JSON that is safe inside a <script> element: < > & are written as unicode escapes, so nothing in a title or a
    description (a "</script>" typed into one, say) can end the element early.
    """
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def organization_ld(request, image_url=""):
    """Structured data for the home page: who the site is."""
    data = {
        "@context": "https://schema.org",
        "@type": "PerformingGroup",
        "name": "Upstage Surrey",
        "url": request.build_absolute_uri("/"),
        "description": settings.SITE_DESCRIPTION,
    }
    if image_url:
        data["logo"] = image_url
    return data


def production_ld(request, production, image_url=""):
    """Structured data for a production's page."""
    data = {
        "@context": "https://schema.org",
        "@type": "CreativeWork",
        "name": production.title,
        "url": request.build_absolute_uri(request.path),
        "publisher": {"@type": "PerformingGroup", "name": "Upstage Surrey"},
    }
    # Only the description, like the page's own meta description: the strap line may be hidden on the page.
    description = plain_text(production.description, limit=300)
    if description:
        data["description"] = description
    if image_url:
        data["image"] = image_url
    return data


def event_ld(request, event, title, dates, image_url="", description="", ticket_url=""):
    """
    Structured data for an event's page: one schema.org Event for each date (that is what search engines want),
    each with the venue if there is one. Only performances are marked as theatre events. With a `ticket_url` a date
    still to come offers tickets there (the price is not recorded, so none is given).
    """
    now = timezone.now()
    kind = "TheaterEvent" if event.event_type == "performance" else "Event"
    items = []
    for when in dates:
        item = {
            "@context": "https://schema.org",
            "@type": kind,
            "name": title,
            "startDate": when.datetime.isoformat(),
            "eventStatus": "https://schema.org/EventScheduled",
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "url": request.build_absolute_uri(request.path),
            "organizer": {"@type": "PerformingGroup", "name": "Upstage Surrey"},
        }
        if description:
            item["description"] = plain_text(description, limit=300)
        if image_url:
            item["image"] = image_url
        venue = event.venue
        if venue:
            place = {"@type": "Place", "name": venue.name}
            if venue.address:
                place["address"] = " ".join(venue.address.split())
            item["location"] = place
        if ticket_url and when.datetime >= now:
            item["offers"] = {"@type": "Offer", "url": ticket_url, "availability": "https://schema.org/InStock"}
        items.append(item)
    return items
