"""
Search engine and link preview tags for the public pages: the canonical address, a description, and the Open Graph /
Twitter card values. `seo()` builds them for a page; the public base template writes them into the page's head.
Pages that don't give their own get the site's defaults (see `default_seo`).
"""

import html
import re

from django.conf import settings
from django.utils.functional import SimpleLazyObject

from backstage.context_processors import navbar_logo

SITE_NAME = "Upstage Theatre"


def plain_text(value, limit=155):
    """HTML as plain text for a description: tags removed, spaces tidied, cut at a word to `limit` characters at most."""
    # Paragraphs, breaks and the like separate words; inline tags (bold, links) don't: "<b>panto</b>." is "panto."
    text = re.sub(r"</?(?:p|br|div|li|ul|ol|h[1-6]|tr|td|th|blockquote)(?=[\s/>])[^>]*>", " ", value or "", flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", text))).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "…"


def seo(request, title="", description="", image=None, og_type="website", noindex=False, canonical_path=None):
    """
    The page's tags as a dict for the `seo` template variable.

    `image` is a backstage Image (the site logo if none is given); `canonical_path` is the address search engines should
    use for this content when it is not the page's own path; `noindex` keeps the page out of search results.
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
    }


def default_seo(request):
    """Context processor: `seo` for pages whose view doesn't give its own (worked out only if a template uses it)."""
    return {"seo": SimpleLazyObject(lambda: seo(request))}
