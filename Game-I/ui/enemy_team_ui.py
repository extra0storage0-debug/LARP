"""World-space name and health bar above each character."""

from __future__ import annotations

from math import ceil, log

from ursina import Entity, Text, color
from ursina.shaders import unlit_shader

from config.character_roster import ENEMY_TEAM, MY_TEAM

TAG_OFFSET = 3.45  # clear of the tallest hair and helmet, which reach 3.11 m
# Tag scale per metre of distance is how big it looks on screen. It is steady up close, so a bar
# never swells as someone comes near, then eases down across this range of distances.
NEAR_METRES, FAR_METRES = 30.0, 1200.0
NEAR_RATIO, FAR_RATIO = .042, .012
MIN_SCALE, MAX_SCALE = .3, 26.0
TEAM_COLORS = {MY_TEAM: color.rgb32(150, 232, 170), ENEMY_TEAM: color.rgb32(255, 170, 150)}
BAR_COLORS = {MY_TEAM: color.rgb32(70, 205, 100), ENEMY_TEAM: color.rgb32(232, 70, 56)}
BAR_WIDTH, BAR_HEIGHT = 1.9, .17
TARGET_SCALE = 1.35
FADE_START, FADE_END = 900.0, 2500.0
TEXT_FADE_START, TEXT_FADE_END = 180.0, 320.0  # too small to read from here, while the bar still is
MIN_ALPHA = .01


class _DefaultShader:
    """Build UI entities unlit; GameManager is constructed under the lit default."""

    def __enter__(self):
        self._previous = Entity.default_shader
        Entity.default_shader = unlit_shader

    def __exit__(self, *_exc):
        Entity.default_shader = self._previous


def set_dormant(root, dormant: bool) -> None:
    """Make a closed menu cost nothing: Ursina otherwise walks every hidden button each frame."""
    for child in root.children:
        child.ignore = dormant
        set_dormant(child, dormant)


def _smooth(amount: float) -> float:
    amount = max(0.0, min(1.0, amount))
    return amount * amount * (3.0 - 2.0 * amount)


def apparent_ratio(distance: float) -> float:
    """Tag scale per metre of distance: the eased shrink from near to far, with no steps in it."""
    if distance <= NEAR_METRES:
        return NEAR_RATIO
    return NEAR_RATIO * (FAR_RATIO / NEAR_RATIO) ** _smooth(log(distance / NEAR_METRES) / log(FAR_METRES / NEAR_METRES))


def _draw_on_top(node, order: int) -> None:
    node.setBin("fixed", order)
    node.setDepthTest(False)
    node.setDepthWrite(False)


class CharacterTag:
    """A camera-facing name and health bar, parented to the body so it follows without tracking."""

    def __init__(self, character) -> None:
        self.character = character
        self._names_wanted = True
        self.is_player = False
        self.targeted = False
        self._shown_fraction = 1.0
        self._shown_alpha = 1.0
        self._text_alpha = 1.0
        self._percent = 100
        self._scale = 0.0
        with _DefaultShader():
            self.root = Entity(parent=character, y=TAG_OFFSET, model=None, collider=None,
                               name=f"{character.character_id.lower()}-health-bar",
                               add_to_scene_entities=False)
            self.root.setBillboardPointEye()
            self.root.setLightOff()
            self.root.setTransparency(True)
            self.label = Text(parent=self.root, text=character.display_name, y=.36, scale=11.0,
                              origin=(0, 0), color=color.white, add_to_scene_entities=False)
            self.percent = Text(parent=self.root, text="100%", x=BAR_WIDTH * .5 + .12, scale=8.0,
                                origin=(-.5, 0), color=color.white, add_to_scene_entities=False)
            self.back = Entity(parent=self.root, model="quad", scale=(BAR_WIDTH + .1, BAR_HEIGHT + .1),
                               color=color.rgba32(8, 10, 16, 210), collider=None,
                               add_to_scene_entities=False)
            self.fill = Entity(parent=self.root, model="quad", origin=(-.5, 0), x=-BAR_WIDTH * .5,
                               scale=(BAR_WIDTH, BAR_HEIGHT), color=color.white, collider=None,
                               add_to_scene_entities=False)
            self.marker = Entity(parent=self.root, model="quad", y=-.32, rotation_z=45.0, scale=.2,
                                 color=color.rgb32(255, 90, 70), collider=None, enabled=False,
                                 add_to_scene_entities=False)
        _draw_on_top(self.back, 40)
        _draw_on_top(self.fill, 41)
        _draw_on_top(self.marker, 41)
        _draw_on_top(self.label, 42)
        _draw_on_top(self.percent, 42)

    @property
    def fraction(self) -> float:
        return self._shown_fraction

    def set_team(self, team: str, is_player: bool) -> None:
        """The player's own health is on the HUD: nothing floats over their head."""
        self.is_player = is_player
        self.label.color = TEAM_COLORS.get(team, color.white)
        self.percent.color = TEAM_COLORS.get(team, color.white)
        self.fill.color = BAR_COLORS.get(team, color.white)
        self._refresh_shown()

    def set_visible(self, visible: bool) -> None:
        """The enemy-names setting hides only the name: health bars always stay."""
        self._names_wanted = bool(visible)
        self.label.enabled = self._names_wanted

    def set_targeted(self, targeted: bool) -> None:
        self.targeted = targeted
        self.marker.enabled = targeted
        self._scale = 0.0

    def _refresh_shown(self) -> None:
        if self.is_player or self._shown_alpha < MIN_ALPHA:
            self.root.hide()
        else:
            self.root.show()

    def update(self, distance: float, vitals) -> None:
        fraction = max(0.0, min(1.0, vitals.fraction))
        if fraction != self._shown_fraction:
            self._shown_fraction = fraction
            self.fill.scale_x = max(.0001, BAR_WIDTH * fraction)
        if self.is_player:
            return  # kept current, for the moment control moves to another body
        scale = max(MIN_SCALE, min(MAX_SCALE, distance * apparent_ratio(distance)))
        if self.targeted:
            scale *= TARGET_SCALE
        if abs(scale - self._scale) > self._scale * .01:
            self._scale = scale
            self.root.setScale(scale)
        alpha = 1.0
        text_alpha = 1.0
        if not self.targeted:  # the one being fought stays readable however far away
            alpha = 1.0 - _smooth((distance - FADE_START) / (FADE_END - FADE_START))
            text_alpha = 1.0 - _smooth((distance - TEXT_FADE_START) / (TEXT_FADE_END - TEXT_FADE_START))
        if abs(alpha - self._shown_alpha) > .02 or (alpha != self._shown_alpha and alpha in (0.0, 1.0)):
            self._shown_alpha = alpha
            self.root.setAlphaScale(alpha)
            self._refresh_shown()
        if abs(text_alpha - self._text_alpha) > .02 or (text_alpha != self._text_alpha and text_alpha in (0.0, 1.0)):
            self._text_alpha = text_alpha
            self.label.setAlphaScale(text_alpha)
            self.percent.setAlphaScale(text_alpha)
        if text_alpha > 0.0:  # a rebuilt Text is not free, so only when it shows and only when it changes
            percent = ceil(fraction * 100.0)
            if percent != self._percent:
                self._percent = percent
                self.percent.text = f"{percent}%"
