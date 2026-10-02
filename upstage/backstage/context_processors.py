import os

from django.contrib.staticfiles import finders
from django.utils.functional import SimpleLazyObject

from backstage.models import Image

# The image library entry shown on the left of the navbar.
NAVBAR_LOGO_DESCRIPTION = "Upstage Surrey Logo"


def navbar_logo(request):
    """`navbar_logo`: the site logo from the image library, or None (the navbar then shows a home icon)."""

    def find_logo():
        return (
            Image.objects.filter(image_type=Image.ImageType.LOGO, description__iexact=NAVBAR_LOGO_DESCRIPTION)
            .exclude(image="")
            .order_by("-id")
            .first()
        )

    return {"navbar_logo": SimpleLazyObject(find_logo)}


def css_version(request):
    """
    `css_version`: when the compiled stylesheet last changed. base.html puts it on the stylesheet's address, so a
    rebuilt stylesheet (new themes, say) is fetched at once instead of the browser's cached copy being used.
    """
    path = finders.find("css/src/output.css")
    try:
        return {"css_version": int(os.path.getmtime(path))}
    except (TypeError, OSError):
        return {"css_version": 0}
