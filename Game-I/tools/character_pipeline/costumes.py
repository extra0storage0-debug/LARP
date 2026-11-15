"""Who each body is: its shape, skin, hair, beard and costume zones. Colours are sRGB 0-1.

Faces are original to this project: they follow the written description of each character (hair, beard,
build, age), not any actor's likeness.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def rgb(r: int, g: int, b: int) -> tuple:
    return (r / 255.0, g / 255.0, b / 255.0)


@dataclass(frozen=True)
class Cloth:
    """One costume zone. pattern: "weave", "scales", "leather", "plate", "ribbed" or "skin"."""
    color: tuple
    rough: float = .62
    metal: float = 0.0
    pattern: str = "weave"
    raised: float = 0.0   # how far this zone stands off the body, in game units


def skin_zone() -> Cloth:
    return Cloth((0, 0, 0), .5, 0.0, "skin")


@dataclass(frozen=True)
class Spec:
    name: str
    body: dict                     # mesh_source.build_body sliders
    details: dict
    skin: tuple
    hair: tuple
    hair_style: str
    eyes: tuple
    torso: Cloth
    upper_arm: Cloth
    forearm: Cloth
    hand: Cloth
    thigh: Cloth
    shin: Cloth
    foot: Cloth
    trunks: Cloth | None = None
    belt: Cloth | None = None
    cuff: Cloth | None = None      # bands at glove and boot tops
    knee: Cloth | None = None
    emblem: str = ""
    trim: tuple = (1, 1, 1)
    beard: str = ""                # "", "full", "goatee", "moustache", "chops"
    beard_color: tuple = (0, 0, 0)
    beard_streak: tuple = (0, 0, 0)
    temple: tuple | None = None    # grey at the temples
    goggles: tuple | None = None
    neck_wrap: Cloth | None = None
    chest_plate: Cloth | None = None
    collar: tuple | None = None
    seed: int = 1
    extra: dict = field(default_factory=dict)


SKIN_FAIR, SKIN_MID = rgb(226, 178, 148), rgb(208, 158, 126)
ROUGH_JAW = {"chin/chin-width-incr": .5, "chin/chin-prominent-incr": .3, "head/head-square": .35, "neck/measure-neck-circ-incr": .5}
SENSIBLE_NECK = {"neck/measure-neck-circ-incr": .6}
LEG_MUSCLE = {"legs/l-upperleg-muscle-incr": .5, "legs/r-upperleg-muscle-incr": .5, "legs/l-lowerleg-muscle-incr": .35, "legs/r-lowerleg-muscle-incr": .35}
# A comic-book build: broad shoulders and lats, big chest, narrow waist, and a head a little small for the body.
BIG_BUILD = {"torso/torso-muscle-pectoral-incr": .7, "torso/torso-muscle-dorsi-incr": .85, "torso/measure-shoulder-dist-incr": .8,
             "torso/measure-waist-circ-decr": .5, "arms/l-upperarm-muscle-incr": .6, "arms/r-upperarm-muscle-incr": .6,
             "arms/l-lowerarm-muscle-incr": .4, "arms/r-lowerarm-muscle-incr": .4, "head/head-fat-decr": .7, **LEG_MUSCLE}

# Superman, Man of Steel (2013): deep navy Kryptonian weave, a raised silver shield, no trunks, a red cape.
_NAVY_SUIT, _BOOT = rgb(22, 38, 86), rgb(22, 34, 76)
_KRYPTON = Cloth(_NAVY_SUIT, .46, .1, "scales")
SUPERMAN = Spec(
    "WHITE", dict(muscle=1.0, weight=.46, height=.8), {**BIG_BUILD, **SENSIBLE_NECK, "chin/chin-width-incr": .45, "chin/chin-cleft-incr": .55, "chin/chin-prominent-incr": .3,
                                                       "head/head-square": .45, "torso/measure-shoulder-dist-incr": .95},
    SKIN_FAIR, rgb(12, 12, 16), "superman", rgb(58, 118, 196),
    _KRYPTON, _KRYPTON, _KRYPTON, skin_zone(), _KRYPTON, _KRYPTON, Cloth(_BOOT, .4, .1, "scales"),
    emblem="superman", trim=rgb(178, 184, 192), seed=11)

# Homelander, The Boys TV series: royal blue, gold eagle armour at the shoulders, chest and waist, red gloves and boots, the flag.
_ROYAL = rgb(30, 66, 142)
HOMELANDER = Spec(
    "BLACK", dict(muscle=.92, weight=.42, height=.78), {**BIG_BUILD, "head/head-oval": .3, "nose/nose-scale-horiz-decr": .3, "chin/chin-prominent-incr": .3},
    SKIN_FAIR, rgb(218, 186, 116), "slick", rgb(70, 132, 186),
    Cloth(_ROYAL, .44, .05, "ribbed"), Cloth(_ROYAL, .44, .05, "ribbed"), Cloth(_ROYAL, .44, .05, "ribbed"),
    Cloth(rgb(160, 24, 32), .4, .1, "leather"), Cloth(_ROYAL, .44, .05, "ribbed"), Cloth(_ROYAL, .44, .05, "ribbed"),
    Cloth(rgb(160, 24, 32), .34, .1, "leather"),
    emblem="homelander", trim=rgb(208, 166, 70), seed=23)

# The Sentry, Marvel Comics, as specified: a blue bodysuit, with gold insignia, belt, gloves, boots and cape.
_SENTRY_BLUE, _SENTRY_GOLD = rgb(26, 58, 148), rgb(240, 186, 52)
SENTRY = Spec(
    "YELLOW", dict(muscle=1.0, weight=.44, height=.84), {**BIG_BUILD, **SENSIBLE_NECK, "chin/chin-width-incr": .3, "chin/chin-prominent-incr": .3, "head/head-square": .3},
    SKIN_FAIR, rgb(232, 188, 92), "swept", rgb(58, 112, 170),
    Cloth(_SENTRY_BLUE, .42, .08, "weave"), Cloth(_SENTRY_BLUE, .42, .08, "weave"), Cloth(_SENTRY_BLUE, .42, .08, "weave"),
    Cloth(_SENTRY_GOLD, .36, .4, "leather"), Cloth(_SENTRY_BLUE, .42, .08, "weave"), Cloth(_SENTRY_BLUE, .42, .08, "weave"),
    Cloth(_SENTRY_GOLD, .34, .4, "leather"),
    emblem="sentry", trim=_SENTRY_GOLD, seed=31)

# Omni-Man, Invincible animated series: massive, white with red chest, shoulders and collar; black hair, grey temples, a full black-and-grey beard.
_WHITE, _CRIMSON = rgb(234, 234, 230), rgb(176, 26, 38)
OMNI_MAN = Spec(
    "GREEN", dict(muscle=1.0, weight=.64, height=.82),
    {**BIG_BUILD, **ROUGH_JAW, "head/head-age-incr": .55, "torso/measure-waist-circ-decr": .1, "torso/measure-shoulder-dist-incr": 1.0, "neck/measure-neck-circ-incr": .9},
    SKIN_MID, rgb(18, 16, 18), "omni", rgb(66, 110, 170),
    Cloth(_WHITE, .46, .05, "weave"), Cloth(_WHITE, .46, .05, "weave"), Cloth(_WHITE, .46, .05, "weave"),
    Cloth(_CRIMSON, .42, .05, "leather"), Cloth(_WHITE, .46, .05, "weave"), Cloth(_WHITE, .46, .05, "weave"),
    Cloth(_CRIMSON, .36, .05, "leather"),
    emblem="omni", trim=_CRIMSON, beard="full", beard_color=rgb(24, 24, 26), beard_streak=rgb(128, 128, 132),
    temple=rgb(140, 140, 144), seed=41)

# Soldier Boy, The Boys TV series: heavyweight, olive-drab armour, leather, scarf, eagle insignia, full dark-brown beard.
_OLIVE, _DRAB = rgb(78, 90, 60), rgb(60, 72, 50)
SOLDIER_BOY = Spec(
    "RED", dict(muscle=1.0, weight=.62, height=.72), {**BIG_BUILD, **ROUGH_JAW, "head/head-age-incr": .4, "torso/measure-waist-circ-decr": .15, "torso/measure-shoulder-dist-incr": 1.0},
    SKIN_MID, rgb(46, 30, 20), "rugged", rgb(92, 112, 96),
    Cloth(_OLIVE, .74, .0, "weave"), Cloth(_OLIVE, .74, .0, "weave"), Cloth(_DRAB, .72, .0, "weave"),
    Cloth(rgb(96, 64, 40), .55, .0, "leather"), Cloth(_OLIVE, .76, .0, "weave"), Cloth(_DRAB, .72, .0, "weave"),
    Cloth(rgb(96, 64, 40), .5, .0, "leather"),
    emblem="soldier", trim=rgb(160, 128, 70), beard="full", beard_color=rgb(52, 34, 22), beard_streak=rgb(92, 64, 42), seed=53)

_UNIFORM, _UNIFORM_PALE, _UNIFORM_GREY = rgb(238, 238, 236), rgb(214, 216, 220), rgb(150, 154, 164)


def _viltrumite(name, seed, skin, hair, style, eyes, body, details=None, **options) -> Spec:
    white = Cloth(_UNIFORM, .46, .05, "weave")
    grey = Cloth(_UNIFORM_GREY, .4, .3, "plate", .004)
    return Spec(name, body, {**BIG_BUILD, **(details or {})}, skin, hair, style, eyes,
                white, white, white, Cloth(_UNIFORM_PALE, .42, .1, "leather", .003), white, white, Cloth(_UNIFORM_PALE, .36, .1, "leather", .006),
                belt=grey, cuff=grey, emblem="viltrumite", trim=_UNIFORM_GREY, collar=_UNIFORM_PALE, seed=seed, **options)


SQUAD = (
    _viltrumite("VILTRUMITE_1", 61, rgb(212, 168, 138), rgb(150, 150, 154), "crew", rgb(70, 86, 96), dict(muscle=1.0, weight=.62, height=.74), ROUGH_JAW,
                beard="full", beard_color=rgb(150, 150, 154), beard_streak=rgb(176, 176, 180)),
    _viltrumite("VILTRUMITE_2", 67, rgb(92, 60, 44), rgb(16, 14, 14), "shaved", rgb(50, 36, 26), dict(muscle=.85, weight=.32, height=.92), None,
                beard="goatee", beard_color=rgb(16, 14, 14), beard_streak=rgb(30, 28, 28)),
    _viltrumite("VILTRUMITE_3", 71, rgb(172, 130, 94), rgb(16, 14, 16), "long_back", rgb(60, 44, 30), dict(muscle=1.0, weight=.72, height=.48), {"nose/nose-scale-horiz-incr": .5},
                beard="moustache", beard_color=rgb(16, 14, 16), beard_streak=rgb(30, 28, 30)),
    _viltrumite("VILTRUMITE_4", 73, rgb(232, 196, 174), rgb(120, 62, 34), "auburn", rgb(82, 112, 80), dict(muscle=.72, weight=.34, height=.62), {"chin/chin-width-decr": .3}),
    _viltrumite("VILTRUMITE_5", 79, rgb(138, 94, 66), rgb(46, 30, 20), "flat_top", rgb(52, 38, 26), dict(muscle=1.0, weight=.68, height=.72), ROUGH_JAW,
                beard="chops", beard_color=rgb(46, 30, 20), beard_streak=rgb(60, 42, 30)),
)
_MARK_YELLOW, _MARK_BLUE = rgb(236, 196, 40), rgb(24, 66, 150)
INVINCIBLE = Spec(
    "INVINCIBLE", dict(muscle=.72, weight=.38, height=.6), {"torso/measure-waist-circ-decr": .3}, rgb(218, 170, 138), rgb(16, 14, 16), "mark", rgb(60, 80, 110),
    Cloth(_MARK_YELLOW, .44, .05, "weave"), Cloth(_MARK_YELLOW, .44, .05, "weave"), Cloth(_MARK_BLUE, .44, .05, "weave"),
    Cloth(_MARK_BLUE, .42, .05, "leather", .003), Cloth(_MARK_BLUE, .44, .05, "weave"), Cloth(_MARK_BLUE, .44, .05, "weave"),
    Cloth(_MARK_BLUE, .36, .05, "leather", .006), trunks=Cloth(_MARK_BLUE, .44, .05, "weave", .001),
    emblem="invincible", trim=rgb(16, 16, 20), goggles=rgb(14, 14, 18), seed=83)

ALL = (SENTRY, SUPERMAN, OMNI_MAN, HOMELANDER, SOLDIER_BOY, *SQUAD, INVINCIBLE)
ROSTER_NAMES = {"YELLOW", "WHITE", "GREEN", "BLACK", "RED"}
