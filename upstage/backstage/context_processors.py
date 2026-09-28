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
