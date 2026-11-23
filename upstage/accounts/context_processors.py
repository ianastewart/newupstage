from django.conf import settings
from django.utils.functional import SimpleLazyObject

from .access import can_backstage


def access(request):
    """`is_backstage` (may make backstage changes) and `sandbox_site` (this is the sandbox, not the live site)."""
    return {
        "is_backstage": SimpleLazyObject(lambda: can_backstage(request.user)),
        "sandbox_site": settings.SITE_MODE == "sandbox",
        # The account pages (login...) use the public layout on the sandbox, where the login form is on the home page.
        "auth_layout": "public_base.html" if settings.SITE_MODE == "sandbox" else "base.html",
    }
