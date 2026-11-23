import os

from django.contrib.staticfiles import finders
from django.utils.functional import SimpleLazyObject

from backstage.models import Image, Palette, Production, SiteSettings
from backstage.themes import PUBLIC_PALETTE, THEMES, is_theme

# The palette (in the admin) whose colours are the colour picker's fixed row.
PICKER_PALETTE_NAME = "Background 1"

# The image library entry shown on the left of the navbar.
NAVBAR_LOGO_DESCRIPTION = "Christmas logo" #"Upstage Surrey Logo"
# The backstage navbar shows this one instead on light themes.
NAVBAR_LOGO_LIGHT_DESCRIPTION = "Upstage big bw"


def navbar_logo(request):
    """`navbar_logo`: the site logo from the image library, or None (the navbar then shows a home icon)."""

    def find_logo():
        return (
            Image.objects.filter(image_type=Image.ImageType.LOGO, description__iexact=NAVBAR_LOGO_DESCRIPTION)
            .exclude(image="")
            .order_by("-id")
            .first()
        )

    def find_light_logo():
        return Image.objects.filter(description__iexact=NAVBAR_LOGO_LIGHT_DESCRIPTION).exclude(image="").order_by("-id").first()

    return {"navbar_logo": SimpleLazyObject(find_logo), "navbar_logo_light": SimpleLazyObject(find_light_logo)}


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


def themes(request):
    """
    `themes`: every theme the site offers, as (name, label). `public_theme`: the theme chosen for the public pages
    (a name, or "" for automatic). It is only looked up when a template uses it.
    """

    def find_public_theme():
        chosen = SiteSettings.load().public_theme
        return chosen if is_theme(chosen) else ""

    return {"themes": THEMES, "public_theme": SimpleLazyObject(find_public_theme)}


def colour_palette(request):
    """
    The colour picker's two rows. `colour_palette`: the fixed row, themes.PUBLIC_PALETTE as [(name, #rrggbb)].
    `colour_saved`: the saved row, the 8 places of the palette PICKER_PALETTE_NAME (a (name, #rrggbb) or None for an
    empty place). The saved row is only looked up when a template uses it.
    """

    def find_saved():
        palette = Palette.objects.filter(name=PICKER_PALETTE_NAME).first()
        return palette.slots() if palette else [None] * Palette.SIZE

    return {"colour_palette": PUBLIC_PALETTE, "colour_saved": SimpleLazyObject(find_saved)}


def production_types(request):
    """`production_types`: the types of production as (value, title in the plural), for the backstage menu."""
    return {"production_types": [(value, Production.TYPE_TITLES[value]) for value, _ in Production.ProductionType.choices]}
