"""The themes the site offers: the two Upstage themes, then all of daisyUI's."""

BUILT_IN = (
    "abyss acid aqua autumn black bumblebee business caramellatte cmyk coffee corporate cupcake cyberpunk dark dim "
    "dracula emerald fantasy forest garden halloween lemonade light lofi luxury night nord pastel retro silk sunset "
    "synthwave valentine winter wireframe"
).split()

THEMES = [("upstage", "Upstage"), ("upstage-dark", "Upstage dark")] + [(name, name.capitalize()) for name in BUILT_IN]

THEME_NAMES = {value for value, _ in THEMES}


def is_theme(value):
    """Whether `value` is the name of one of the themes."""
    return value in THEME_NAMES
