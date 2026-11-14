"""The themes the site offers: the three Upstage themes, then all of daisyUI's."""

BUILT_IN = (
    "abyss acid aqua autumn black bumblebee business caramellatte cmyk coffee corporate cupcake cyberpunk dark dim "
    "dracula emerald fantasy forest garden halloween lemonade light lofi luxury night nord pastel retro silk sunset "
    "synthwave valentine winter wireframe"
).split()

THEMES = [("upstage", "Upstage"), ("upstage-dark", "Upstage dark"), ("upstage-spotlight", "Upstage spotlight")] + [(name, name.capitalize()) for name in BUILT_IN]

THEME_NAMES = {value for value, _ in THEMES}


def is_theme(value):
    """Whether `value` is the name of one of the themes."""
    return value in THEME_NAMES


# The fixed palette offered as swatches for a production's public page background: the colours of the public
# (upstage-spotlight) theme in backstage/static/css/input.css, as #rrggbb. Change them here if that theme changes.
# PUBLIC_PALETTE = [
#     ("base-100", "#0e050d"),
#     ("base-200", "#5c2277"),
#     ("base-300", "#6018b3"),
#     ("blue", "#1d057a"),
#     ("primary", "#9643e3"),
#     ("secondary", "#d780e8"),
#     ("accent", "#331d46"),
#     ("info", "#640060"),
# ]

# A pink to blue palette, same form as PUBLIC_PALETTE: (name, #rrggbb).
PUBLIC_PALETTE = [
    ("Dark Plum", "#8b0e78"),
    ("Raspberry Plum", "#b5179e"),
    ("Indigo Bloom", "#7209b7"),
    # ("Ultrasonic Blue", "#560bad"),
    ("True Azure", "#480ca8"),
    # ("Vivid Royal", "#3a0ca3"),
    ("Bright Indigo", "#3f37c9"),
    ("Electric Sapphire", "#4361ee"),
    ("Blue Energy", "#4895ef"),
    ("Sky Aqua", "#4cc9f0"),
]