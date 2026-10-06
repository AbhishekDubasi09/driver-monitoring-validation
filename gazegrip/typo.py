"""Single source of truth for the typeface: JetBrains Mono (files in ./fonts)."""
import os

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
CSS_STACK = '"JetBrains Mono",Consolas,"Cascadia Mono",monospace'


def font_path(weight="Regular"):
    name = {"Regular": "Regular", "SemiBold": "Bold", "Bold": "Bold"}[weight]
    p = os.path.join(FONT_DIR, f"JetBrainsMono-{name}.ttf")
    return p


def family_in_use():
    return "JetBrains Mono"
