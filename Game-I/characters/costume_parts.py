"""What a costume is made of: the kit every character fills in, the shapes it is built from, and Omni-Man's squad.

Costume parts are simple shapes baked onto the shared body. Anchors: "body" is model space, "face" is relative
to the point between the eyes, and limb anchors are relative to that limb's joint.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, sin


def rgb(r: int, g: int, b: int) -> tuple[float, float, float]:
    return (r / 255.0, g / 255.0, b / 255.0)


@dataclass(frozen=True, slots=True)
class CharacterKit:
    character_id: str
    display: str
    can_fly: bool
    description: str
    parts: tuple = ()
    helmet_parts: tuple = ()              # shown only while the Helmet setting is on
    cape: bool = True
    flag_cape: bool = False
    body_scale: tuple = (1.0, 1.0, 1.0)   # width, height, depth
    chest_s: tuple | None = None          # colour of the chest S; None removes it
    biology: str = "other"                # compound_v characters can be nullified
    shield_parts: tuple = ()              # hidden while the shield is thrown
    skin: tuple | None = None             # the head's tone, if it is not the shared one
    super_jump: bool = False              # jumps as high as the player wants; this is not flight


HAIR_BLACK = rgb(18, 16, 18)
HAIR_DARK_BROWN = rgb(46, 30, 20)
HAIR_BLOND = rgb(214, 176, 96)
GOLD = rgb(214, 172, 70)
ANTIQUE_GOLD = rgb(169, 135, 67)
RED = rgb(176, 24, 30)
DEEP_RED = rgb(146, 23, 36)
WHITE = rgb(233, 233, 233)
STEEL = rgb(112, 118, 124)
SILVER = rgb(186, 192, 198)
ROYAL = rgb(24, 61, 117)
SKIN = rgb(205, 157, 128)
BEARD_BLACK = rgb(24, 24, 26)
BEARD_GREY = rgb(128, 128, 132)
BEARD_BROWN = rgb(52, 34, 22)
BEARD_LIGHT_BROWN = rgb(92, 64, 42)
OLIVE = rgb(102, 112, 76)
DARK_GREEN = rgb(48, 59, 44)
CHARCOAL = rgb(37, 42, 40)
LEATHER = rgb(89, 60, 41)
UNIFORM_WHITE = rgb(240, 240, 238)
UNIFORM_PALE = rgb(214, 216, 220)
UNIFORM_GREY = rgb(168, 172, 180)


def brows(color) -> tuple:
    return (("face", "s", (-.095, .075, -.01), (.13, .03, .04), color, -6.0),
            ("face", "s", (.095, .075, -.01), (.13, .03, .04), color, 6.0))


def skull(skin=SKIN) -> tuple:
    """The face sits well forward of the small original skull, with long hair hiding
    the gap. This fills the head out to meet the eyes, cheeks and jaw."""
    return (("body", "s", (0.0, 2.47, .20), (.47, .60, .52), skin, 0.0),
            ("body", "s", (-.245, 2.48, .17), (.05, .13, .09), skin, 0.0),   # ears
            ("body", "s", (.245, 2.48, .17), (.05, .13, .09), skin, 0.0))


def short_hair(color, skin=SKIN) -> tuple:
    """A cap over the crown and a shorter mass behind, instead of long hair."""
    return (*skull(skin),
            ("body", "s", (0.0, 2.70, .16), (.50, .26, .60), color, 0.0),
            ("body", "s", (0.0, 2.52, -.01), (.49, .50, .34), color, 0.0))


def boots(color) -> tuple:
    return tuple((leg, "s", (0.0, -.66, .03), (.25, .62, .29), color, 0.0)
                 for leg in ("left_leg", "right_leg"))


def thighs(color) -> tuple:
    return tuple((leg, "s", (0.0, -.24, .0), (.30, .62, .33), color, 0.0)
                 for leg in ("left_leg", "right_leg"))


def gloves(color) -> tuple:
    return tuple((arm, "s", (0.0, -1.02, .03), (.17, .24, .18), color, 0.0)
                 for arm in ("left_arm", "right_arm"))


def star(anchor, position, size, color) -> tuple:
    """Five crossed bars read as a star at game distance."""
    return tuple((anchor, "c", position, (size * .18, size, .012), color, angle)
                 for angle in (0.0, 36.0, 72.0, 108.0, 144.0))


def full_beard(main, streak, streak_every: int = 2) -> tuple:
    """A connected beard: solid jaw masses, then layered strands around the outline.

    Covers the upper lip, cheeks, jaw, chin, underside and sideburns. The strands are
    what stop it reading as a flat painted patch, at 120 triangles each.
    """
    parts = [
        ("body", "s", (0.0, 2.235, .345), (.30, .20, .22), main, 0.0),      # chin
        ("body", "s", (0.0, 2.18, .22), (.30, .12, .34), main, 0.0),        # underside
        ("body", "s", (-.175, 2.33, .25), (.17, .30, .36), main, 0.0),      # jaw
        ("body", "s", (.175, 2.33, .25), (.17, .30, .36), main, 0.0),
        ("body", "s", (-.19, 2.44, .30), (.09, .17, .22), main, 0.0),       # cheeks
        ("body", "s", (.19, 2.44, .30), (.09, .17, .22), main, 0.0),
        ("body", "s", (-.225, 2.55, .20), (.055, .22, .16), main, 0.0),     # sideburns
        ("body", "s", (.225, 2.55, .20), (.055, .22, .16), main, 0.0),
        ("body", "s", (0.0, 2.355, .455), (.24, .05, .06), main, 0.0),      # moustache
        ("body", "s", (-.115, 2.315, .425), (.07, .10, .07), main, 0.0),    # joins the beard
        ("body", "s", (.115, 2.315, .425), (.07, .10, .07), main, 0.0),
    ]
    count = 22
    for index in range(count):
        angle = pi * index / (count - 1)                     # right jaw, chin, left jaw
        x, y = cos(angle) * .185, 2.33 - sin(angle) * .16
        z = .20 + sin(angle) * .25
        tint = streak if index % streak_every == 0 else main
        parts.append(("body", "s", (x, y, z), (.03, .12, .04), tint, cos(angle) * 22.0))
    return tuple(parts)


def tone(color, share: float) -> tuple:
    return tuple(channel * share for channel in color)


def features(skin, *, nose, jaw, chin, lid=.022) -> tuple:
    """Nose, jaw, chin and heavy or light eyelids, built over the head every clone shares."""
    shade = tone(skin, .78)
    return (("body", "s", (0.0, 2.34, .13), jaw, skin, 0.0),
            ("body", "s", (0.0, 2.245, .345), chin, tone(skin, 1.04), 0.0),
            ("body", "s", (0.0, 2.43, .49), nose, tone(skin, 1.03), 0.0),
            ("body", "s", (-.105, 2.578, .432), (.098, lid, .030), shade, 0.0),
            ("body", "s", (.105, 2.578, .432), (.098, lid, .030), shade, 0.0))


def soldier(description: str, skin, hair: tuple, face: tuple, kit: tuple, *, build, cape: bool = False) -> CharacterKit:
    """One Viltrumite soldier: their own white uniform, on Omni-Man's side and using his values.

    Their ID is his: they fight beside him and read his settings, and are not a sixth character.
    """
    return CharacterKit("GREEN", "VILTRUMITE", True, description, parts=(*hair, *face, *kit), cape=cape,
                        body_scale=build, skin=skin)


def bar(y: float, width: float, tint=UNIFORM_GREY) -> tuple:
    return (("body", "c", (0.0, y, .385), (width, .035, .02), tint, 0.0),)


INVINCIBLE_YELLOW = rgb(236, 196, 40)
INVINCIBLE_BLUE = rgb(24, 66, 150)
_ELDER, _DARK, _OLIVE, _PALE, _BROWN = (rgb(212, 168, 138), rgb(92, 60, 44), rgb(172, 130, 94),
                                       rgb(232, 196, 174), rgb(138, 94, 66))
SQUAD_KITS = {
    # The veteran: grey crew cut and full beard, square jaw, broad, with shoulder plates and a cape.
    "VILTRUMITE_1": soldier(
        "A grey-bearded Viltrumite commander.", _ELDER,
        (*short_hair(BEARD_GREY, _ELDER), *brows(BEARD_GREY)),
        (*features(_ELDER, nose=(.09, .10, .07), jaw=(.42, .36, .36), chin=(.26, .13, .12), lid=.03),
         *full_beard(BEARD_GREY, rgb(160, 160, 164), 3)),
        (("body", "s", (-.47, 1.98, .02), (.40, .17, .38), UNIFORM_PALE, 14.0),
         ("body", "s", (.47, 1.98, .02), (.40, .17, .38), UNIFORM_PALE, -14.0),
         *bar(1.78, .46), *bar(1.68, .36)),
        build=(1.14, 1.05, 1.10), cape=True),
    # The tall one: dark skin, shaved head, thin goatee, lean, high collar.
    "VILTRUMITE_2": soldier(
        "A tall, lean, shaved-headed Viltrumite.", _DARK,
        (*skull(_DARK), *brows(HAIR_BLACK)),
        (*features(_DARK, nose=(.10, .075, .07), jaw=(.33, .38, .32), chin=(.18, .15, .11)),
         ("body", "s", (0.0, 2.205, .35), (.10, .10, .07), HAIR_BLACK, 0.0)),
        (("body", "s", (0.0, 2.13, .03), (.42, .17, .36), UNIFORM_WHITE, 0.0),
         ("body", "c", (0.0, 1.72, .385), (.05, .46, .02), UNIFORM_GREY, 0.0)),
        build=(.98, 1.10, .96)),
    # The stocky one: olive skin, long black hair swept back, moustache and a broad nose.
    "VILTRUMITE_3": soldier(
        "A stocky Viltrumite with long swept-back hair.", _OLIVE,
        (*short_hair(HAIR_BLACK, _OLIVE), *brows(HAIR_BLACK),
         ("body", "s", (0.0, 2.26, -.12), (.44, .52, .22), HAIR_BLACK, 0.0)),
        (*features(_OLIVE, nose=(.13, .08, .08), jaw=(.40, .34, .34), chin=(.22, .11, .11)),
         ("body", "s", (0.0, 2.355, .465), (.27, .055, .06), HAIR_BLACK, 0.0)),
        (("body", "c", (-.14, 1.76, .385), (.26, .04, .02), UNIFORM_GREY, 32.0),
         ("body", "c", (.14, 1.76, .385), (.26, .04, .02), UNIFORM_GREY, -32.0),
         ("body", "c", (0.0, 1.02, .385), (.56, .08, .03), UNIFORM_PALE, 0.0)),
        build=(1.20, .95, 1.14)),
    # The young one: pale, clean-shaven, narrow jaw and auburn hair; slim, with a cape.
    "VILTRUMITE_4": soldier(
        "A young, clean-shaven Viltrumite with auburn hair.", _PALE,
        (*short_hair(rgb(120, 62, 34), _PALE), *brows(rgb(120, 62, 34)),
         ("body", "s", (0.0, 2.72, .32), (.30, .10, .18), rgb(120, 62, 34), -10.0)),
        features(_PALE, nose=(.065, .07, .055), jaw=(.30, .32, .30), chin=(.15, .10, .10), lid=.016),
        (*bar(1.84, .30), ("body", "s", (0.0, 1.62, .36), (.20, .20, .03), UNIFORM_PALE, 0.0)),
        build=(1.0, 1.0, .95), cape=True),
    # The bruiser: brown skin, tall flat-top, heavy brow and big jaw, with mutton chops.
    "VILTRUMITE_5": soldier(
        "A heavy-browed Viltrumite with a flat-top and mutton chops.", _BROWN,
        (*skull(_BROWN), ("body", "c", (0.0, 2.80, .14), (.46, .20, .50), HAIR_DARK_BROWN, 0.0),
         ("body", "c", (0.0, 2.66, .22), (.48, .05, .03), tone(_BROWN, .6), 0.0)),
        (*features(_BROWN, nose=(.11, .09, .09), jaw=(.44, .40, .38), chin=(.28, .14, .13), lid=.04),
         ("body", "s", (-.20, 2.34, .27), (.10, .28, .14), HAIR_DARK_BROWN, 0.0),
         ("body", "s", (.20, 2.34, .27), (.10, .28, .14), HAIR_DARK_BROWN, 0.0),
         ("body", "s", (-.10, 2.625, .44), (.17, .05, .05), HAIR_DARK_BROWN, -6.0),
         ("body", "s", (.10, 2.625, .44), (.17, .05, .05), HAIR_DARK_BROWN, 6.0)),
        (("body", "s", (0.0, 1.70, .30), (.72, .52, .14), UNIFORM_PALE, 0.0), *bar(1.42, .50),
         ("body", "s", (-.50, 1.96, .02), (.34, .22, .36), UNIFORM_GREY, 10.0),
         ("body", "s", (.50, 1.96, .02), (.34, .22, .36), UNIFORM_GREY, -10.0)),
        build=(1.12, 1.03, 1.06)),
    "INVINCIBLE": CharacterKit(
        "GREEN", "INVINCIBLE", True,
        "Mark Grayson. Yellow suit, blue gloves, boots and legs, black goggles and short black hair: young and athletic.",
        parts=(*short_hair(HAIR_BLACK), *brows(HAIR_BLACK),
               ("body", "s", (0.0, 2.71, .36), (.34, .10, .16), HAIR_BLACK, 8.0),      # the swept-up fringe
               ("face", "s", (-.095, .005, -.005), (.15, .085, .05), HAIR_BLACK, 0.0),  # goggles
               ("face", "s", (.095, .005, -.005), (.15, .085, .05), HAIR_BLACK, 0.0),
               ("body", "s", (0.0, 1.72, .375), (.50, .42, .06), INVINCIBLE_YELLOW, 0.0),
               ("body", "c", (0.0, 1.78, .412), (.07, .22, .02), HAIR_BLACK, 0.0),     # the i on his chest
               ("body", "c", (0.0, 1.94, .412), (.07, .05, .02), HAIR_BLACK, 0.0),
               ("body", "s", (0.0, 1.24, .335), (.62, .46, .06), INVINCIBLE_BLUE, 0.0),
               *thighs(INVINCIBLE_BLUE), *boots(INVINCIBLE_BLUE), *gloves(INVINCIBLE_BLUE)),
        cape=False, body_scale=(.97, .98, .97), skin=rgb(218, 170, 138)),
}
