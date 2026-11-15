"""The look of every menu and the HUD: near-black, steel, off-white and one clean red. The fonts are SIL OFL; see assets/fonts."""

from __future__ import annotations

from pathlib import Path

from ursina import Text, application, color

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
BRANDING = ROOT / "assets" / "branding"
TITLE_FONT = "Anton-Regular.ttf"
BODY_FONT = "BarlowCondensed-SemiBold.ttf"

application.fonts_folder = FONTS
Text.default_font = BODY_FONT

ACCENT = color.rgb32(196, 28, 34)
ACCENT_BRIGHT = color.rgb32(255, 72, 64)
ACCENT_SOFT = color.rgb32(255, 150, 140)
ACCENT_DIM = color.rgba32(96, 22, 26, 255)
ACCENT_DIMMER = color.rgba32(74, 20, 24, 255)
ACCENT_HOVER = color.rgba32(128, 26, 30, 255)
ACCENT_LINE = color.rgb32(170, 36, 40)
ACCENT_LINE_DIM = color.rgb32(110, 28, 30)
WAITING = color.rgba32(66, 26, 28, 220)

TEXT = color.rgb32(238, 236, 230)
TEXT_MUTED = color.rgb32(184, 184, 186)
TEXT_FAINT = color.rgb32(140, 140, 144)
HELP_TEXT = color.rgba32(238, 236, 230, 170)
SUCCESS = color.rgb32(232, 232, 226)
WARNING = color.rgb32(255, 150, 90)

STEEL = color.rgba32(40, 40, 44, 240)
STEEL_LIGHT = color.rgba32(46, 46, 50, 240)
STEEL_DARK = color.rgba32(34, 34, 38, 240)
STEEL_DARK_SOFT = color.rgba32(34, 34, 38, 220)
STEEL_SLOT = color.rgba32(26, 26, 30, 210)
STEEL_EMPTY = color.rgba32(20, 20, 22, 120)
STEEL_TRACK = color.rgba32(26, 26, 30, 255)
STEEL_DEEP = color.rgba32(22, 22, 26, 255)

PANEL = color.rgba32(11, 11, 13, 248)
PANEL_SOFT = color.rgba32(11, 11, 13, 228)
READOUT = color.rgba32(11, 11, 13, 110)
READOUT_DARK = color.rgba32(11, 11, 13, 180)
BAR_BACK = color.rgba32(8, 8, 10, 200)
