"""Character selection and team management: click PLAY on anyone to take over their body."""

from __future__ import annotations

from pathlib import Path

from ursina import Button, Entity, Text, Texture, camera, color

from ui import theme

from characters.registry import default_player, definition, definitions
from characters.roster import KITS, ROSTER_IDS
from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM, RosterError, TEAM_LABELS, TEAMS
from ui.enemy_team_ui import _DefaultShader, set_dormant

ROW_TOP = .22
# The rows share the same space however many characters there are.
ROW_STEP = min(.092, .44 / max(1, len(ROSTER_IDS)))
ROW_HEIGHT = ROW_STEP * .76
COLUMN_X = {MY_TEAM: -.235, ENEMY_TEAM: -.105, AVAILABLE: .025}
_ACTIVE = theme.ACCENT
_IDLE = theme.STEEL
_SELECTED = theme.ACCENT_DIM
_WARNING = theme.WARNING
_GOOD = theme.SUCCESS
PORTRAITS = Path(__file__).resolve().parent.parent / "assets" / "portraits"
_SWATCHES = {item.character_id: (color.rgb32(*item.card_tint), color.rgb(*item.palette[5])) for item in definitions()}


def _button(parent, text, position, scale, on_click) -> Button:
    button = Button(parent=parent, text=text, position=position, scale=scale, model="quad",
                    color=_IDLE, highlight_color=theme.ACCENT_HOVER,
                    text_color=color.white)
    button.text_entity.scale *= .95
    button.on_click = on_click
    return button


class TeamManagerPanel(Entity):
    def __init__(self, game, **kwargs) -> None:
        kwargs.setdefault("parent", camera.ui)
        kwargs.setdefault("model", None)
        with _DefaultShader():
            super().__init__(**kwargs)
            self.game = game
            self.teams = game.teams
            self.selected = self.teams.state.player
            self._reset_armed = False
            self._build()
        self.visible = False
        self.enabled = False
        set_dormant(self, True)

    # -- construction ----------------------------------------------------
    def _build(self) -> None:
        Entity(parent=self, model="quad", scale=(1.46, .80), z=.02, color=theme.ACCENT)
        Entity(parent=self, model="quad", scale=(1.455, .795), z=.01,
               color=theme.PANEL)
        Text(parent=self, text="CHARACTER SELECTION & TEAMS", position=(0, .365), origin=(0, 0),
             scale=1.35, font=theme.TITLE_FONT, color=theme.TEXT)
        for team, x in COLUMN_X.items():
            Text(parent=self, text=TEAM_LABELS[team], position=(x, .30), origin=(0, 0), scale=.68,
                 color=theme.TEXT_MUTED)
        Text(parent=self, text="TAKE CONTROL", position=(.155, .30), origin=(0, 0), scale=.68,
             color=theme.TEXT_MUTED)
        self.rows = {}
        for index, character_id in enumerate(ROSTER_IDS):
            y = ROW_TOP - index * ROW_STEP
            suit, trim = _SWATCHES[character_id]
            self._portrait(character_id, y, suit, trim)
            name = _button(self, KITS[character_id].display, (-.49, y), (.30, ROW_HEIGHT),
                           lambda chosen=character_id: self.select(chosen))
            slots = {team: _button(self, "ADD", (COLUMN_X[team], y), (.118, ROW_HEIGHT),
                                   lambda chosen=character_id, target=team: self.assign(chosen, target))
                     for team in TEAMS}
            swap = _button(self, "PLAY", (.155, y), (.118, ROW_HEIGHT),
                           lambda chosen=character_id: self.swap(chosen))
            self.rows[character_id] = (name, slots, swap)
        Text(parent=self, text="POWER CONTROL", position=(.47, .30), origin=(0, 0), scale=.68,
             color=theme.TEXT_MUTED)
        self.flight_button = _button(self, "FLIGHT", (.47, .22), (.42, .062), self.toggle_flight)
        self.speed_button = _button(self, "SPEED", (.47, .15), (.42, .062), self.cycle_speed)
        self.boost_button = _button(self, "BOOST", (.47, .08), (.42, .062), self.cycle_boost)
        self.ground_text = Text(parent=self, text="GROUND-BOUND\nFLIGHT UNAVAILABLE",
                                position=(.47, .15), origin=(0, 0), scale=.86, color=_WARNING)
        self.helmet_button = _button(self, "HELMET", (.47, .01), (.42, .062), self.toggle_helmet)
        self.reset_button = _button(self, "RESET CHARACTER DEFAULTS", (.47, -.06), (.42, .058),
                                    self.reset_character)
        self.reset_all_button = _button(self, "RESET ALL DEFAULTS", (.47, -.125), (.42, .058),
                                        self.reset_all)
        Text(parent=self, text="CHARACTER DETAILS", position=(-.685, -.255), origin=(-.5, 0),
             scale=.68, color=theme.TEXT_MUTED)
        self.details = Text(parent=self, text="", position=(-.685, -.285), origin=(-.5, .5),
                            scale=.72, color=color.white)
        self.status = Text(parent=self, text="", position=(0, -.365), origin=(0, 0), scale=.78,
                           color=_GOOD)
        Text(parent=self, text="M Close   |   Up/Down Select   |   Enter Take Control   |   F Flight",
             position=(.47, -.20), origin=(0, 0), scale=.62, color=color.gray)

    def _portrait(self, character_id: str, y: float, suit, trim) -> None:
        """A rendered head-and-shoulders picture, or the costume colours if it is missing."""
        path = PORTRAITS / f"{character_id.lower()}.png"
        if path.exists():
            Entity(parent=self, model="quad", position=(-.67, y), scale=(ROW_STEP * .82, ROW_STEP * .92),
                   texture=Texture(path), color=color.white)
            return
        Entity(parent=self, model="quad", position=(-.685, y), scale=(.03, ROW_HEIGHT), color=suit)
        Entity(parent=self, model="quad", position=(-.655, y), scale=(.03, ROW_HEIGHT), color=trim)

    # -- open and close --------------------------------------------------
    def open(self) -> None:
        self.visible = True
        self.enabled = True
        set_dormant(self, False)
        self.selected = self.teams.state.player
        self._reset_armed = False
        self.status.text = ""
        self.refresh()

    def close(self) -> None:
        self.visible = False
        self.enabled = False
        set_dormant(self, True)

    def input(self, key: str) -> None:
        order = list(ROSTER_IDS)
        index = order.index(self.selected)
        if key in ("up arrow", "up arrow hold"):
            self.select(order[(index - 1) % len(order)])
        elif key in ("down arrow", "down arrow hold"):
            self.select(order[(index + 1) % len(order)])
        elif key in ("enter", "return"):
            self.swap(self.selected)
        elif key == "f":
            self.toggle_flight()

    # -- actions ---------------------------------------------------------
    def select(self, character_id: str) -> None:
        self.selected = character_id
        self._reset_armed = False
        self.refresh()

    def assign(self, character_id: str, team: str) -> None:
        self.selected = character_id
        if self.teams.state.team_of(character_id) == team:
            self.refresh()
            return
        try:
            self.teams.assign(character_id, team)
            self._say(f"{KITS[character_id].display}: {TEAM_LABELS[team]}", _GOOD)
        except RosterError as error:
            self._say(str(error), _WARNING)
        self.refresh()

    def swap(self, character_id: str) -> None:
        self.selected = character_id
        try:
            self.teams.swap(character_id)
            self._say(f"You now control {KITS[character_id].display}", _GOOD)
        except RosterError as error:
            self._say(str(error), _WARNING)
        self.refresh()

    def _changed(self) -> None:
        self.teams.state.save()
        self.game.apply_sentry_config()
        self.refresh()

    def toggle_flight(self) -> None:
        state = self.teams.state
        if KITS[self.selected].can_fly:
            state.set_flight(self.selected, not state.settings(self.selected)["flight_enabled"])
            self._changed()

    def cycle_speed(self) -> None:
        if KITS[self.selected].can_fly:
            self.teams.state.cycle_flight_speed(self.selected)
            self._changed()

    def cycle_boost(self) -> None:
        if KITS[self.selected].can_fly:
            self.teams.state.cycle_flight_boost(self.selected)
            self._changed()

    def toggle_helmet(self) -> None:
        settings = self.teams.state.settings(self.selected)
        settings["helmet"] = not settings["helmet"]
        self._changed()

    def reset_character(self) -> None:
        self.teams.state.reset_character(self.selected)
        self._say(f"{KITS[self.selected].display}: defaults restored", _GOOD)
        self._changed()

    def reset_all(self) -> None:
        """A second click confirms, and the player keeps a valid My Team character."""
        if not self._reset_armed:
            self._reset_armed = True
            self._say("Click RESET ALL DEFAULTS again to confirm", _WARNING)
            self.refresh()
            return
        self._reset_armed = False
        teams = self.teams
        teams.state.assignment[default_player()] = MY_TEAM
        teams.swap(default_player(), save=False)
        teams.state.reset_all()
        teams._apply_roster()
        self._say("All characters and teams restored", _GOOD)
        self._changed()

    def _say(self, message: str, tint) -> None:
        self.status.text = message
        self.status.color = tint

    # -- drawing ---------------------------------------------------------
    def refresh(self) -> None:
        state = self.teams.state
        for character_id, (name, slots, swap) in self.rows.items():
            name.color = _SELECTED if character_id == self.selected else _IDLE
            current = state.team_of(character_id)
            for team, button in slots.items():
                chosen = team == current
                button.color = _ACTIVE if chosen else _IDLE
                button.text = "IN" if chosen else "ADD"
                button.text_color = theme.TEXT if chosen else color.gray
            playing = character_id == state.player
            swap.text = "YOU" if playing else "PLAY"
            swap.color = _ACTIVE if playing else _IDLE
            swap.text_color = theme.TEXT if playing else color.white
        kit = KITS[self.selected]
        settings = state.settings(self.selected)
        for button in (self.flight_button, self.speed_button, self.boost_button):
            button.enabled = kit.can_fly
        self.ground_text.enabled = not kit.can_fly
        self.helmet_button.enabled = bool(kit.helmet_parts)
        if kit.can_fly:
            self.flight_button.text = f"FLIGHT: {'ENABLED' if settings['flight_enabled'] else 'DISABLED'}"
            self.speed_button.text = f"FLIGHT SPEED: {settings['flight_speed']}"
            self.boost_button.text = f"FLIGHT BOOST: {settings['flight_boost']}"
        if kit.helmet_parts:
            self.helmet_button.text = f"HELMET: {'ON' if settings['helmet'] else 'OFF'}"
        control = "PLAYER" if self.selected == state.player else (
            "NOT IN THE WORLD" if state.team_of(self.selected) == AVAILABLE else "AI")
        flight = "CAN FLY" if kit.can_fly else "GROUND-BOUND"
        self.details.text = (f"{kit.display}  |  {TEAM_LABELS[state.team_of(self.selected)]}  |  "
                             f"{control}  |  {flight}\n{kit.description}")
