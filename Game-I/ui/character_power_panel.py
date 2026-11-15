"""Character Power Configuration: five tabs, up to six ability cards, and Range, Damage and Speed.

All cards are built once and rebound on a tab change, and nothing here runs per frame except an
active drag, so the menu costs almost nothing on integrated graphics. Edits wait as pending
values until Apply. Closing the menu applies them too, and switching character tab keeps them.
"""

from __future__ import annotations

from textwrap import fill

from ursina import Button, Entity, Text, camera, color, mouse

from ui import theme

from characters.registry import default_player, definitions
from characters.roster import KITS, ROSTER_IDS
from config.power_schema import (ABILITIES, BOOST_SPEED, CHARACTER, FLY_SPEED, FULL_HEAL_SECONDS, HEALING_SPEED, HEALTH, MAX_CARDS,
                                 MOVEMENT_KEYS, PARAM_KEYS, PARAM_LABELS, RUN_SPEED, SCHEMA, SQUAD_ACTIVE, SQUAD_CYCLE,
                                 SQUAD_KEYS, SQUAD_MARK, SQUAD_VILTRUMITES, TOGGLE, TYPE_LABELS, ability_of,
                                 character_settings)
from ui.enemy_team_ui import _DefaultShader, set_dormant

CARD_WIDTH, CARD_HEIGHT = .525, .345
CARD_COLUMNS = (-.54, 0.0, .54)
CARD_TOPS = (.385, .03)
ROW_OFFSETS = (-.175, -.222, -.269)
CHARACTER_ROWS = {HEALTH: -.388, HEALING_SPEED: -.422}
CHARACTER_ROW_X = CARD_COLUMNS[0] + .05  # leaves room for the longer label
MOVEMENT_ROWS = {RUN_SPEED: -.372, FLY_SPEED: -.402, BOOST_SPEED: -.432}
MOVEMENT_ROW_X = .055
SQUAD_ROWS = {SQUAD_VILTRUMITES: -.068, SQUAD_MARK: -.115, SQUAD_ACTIVE: -.162, SQUAD_CYCLE: -.209}
TRACK_OFFSET, TRACK_WIDTH = -.165, .25
KNOB_WIDTH = .010
_GOLD = theme.TEXT
_BORDER = theme.ACCENT
_PANEL = theme.PANEL
_CARD = theme.STEEL_DEEP
_IDLE = theme.STEEL_LIGHT
_HOVER = theme.ACCENT_HOVER
_ACTIVE = theme.ACCENT
_EDITING = theme.ACCENT_DIM
_GOOD = theme.SUCCESS
_WARN = theme.WARNING
_MUTED = theme.TEXT_FAINT
_TRACK = theme.STEEL_TRACK
_FILL = theme.ACCENT_LINE
_CARD_TINTS = {item.character_id: color.rgb32(*item.card_tint) for item in definitions()}
_STATES = {"": "READY", "ON": "ACTIVE", "NULL": "NULLIFIED"}


def format_value(value: float) -> str:
    return f"{value:.0f}"


def _button(parent, text, position, scale, action, tint=_IDLE, text_scale=.8) -> Button:
    # Ursina only creates the label for non-empty text, and rows are filled in later.
    button = Button(parent=parent, text=text or " ", position=position, scale=scale, model="quad",
                    color=tint, highlight_color=_HOVER, text_color=color.white)
    button.text_entity.scale *= text_scale
    button.on_click = action
    return button


class _ParamRow:
    """Label, slider, exact value box and unit for one of the three values on one card."""

    def __init__(self, panel, card, key: str, x: float, y: float, label_x: float | None = None) -> None:
        self.panel = panel
        self.card = card
        self.key = key
        self.param = None
        self.track_left = x + TRACK_OFFSET
        self.label = Text(parent=panel, text=PARAM_LABELS[key],
                          position=(x - .25 if label_x is None else label_x, y), scale=.62,
                          origin=(-.5, 0), color=color.white)
        self.track = Button(parent=panel, model="quad", position=(self.track_left + TRACK_WIDTH * .5, y),
                            scale=(TRACK_WIDTH, .016), color=_TRACK, highlight_color=_TRACK)
        self.track.on_click = self.begin_drag
        self.fill = Entity(parent=panel, model="quad", origin=(-.5, 0),
                           position=(self.track_left, y, -.001), scale=(.001, .016), color=_FILL,
                           collider=None)
        self.knob = Entity(parent=panel, model="quad", position=(self.track_left, y, -.002),
                           scale=(KNOB_WIDTH, .028), color=_GOLD, collider=None)
        self.value = _button(panel, "", (x + .14, y), (.085, .032), self.begin_edit, text_scale=.72)
        self.unit = Text(parent=panel, text="", position=(x + .186, y), scale=.54, origin=(-.5, 0),
                         color=_MUTED)
        self.not_applicable = Text(parent=panel, text="N/A", position=(x + .14, y), scale=.66,
                                   origin=(0, 0), color=_MUTED)
        self.items = (self.track, self.fill, self.knob, self.value, self.unit)

    def bind(self, param) -> None:
        """A value that means nothing to this ability shows N/A and offers no control."""
        self.param = param
        for item in self.items:
            item.enabled = param is not None
        self.not_applicable.enabled = param is None
        if param is not None:
            self.unit.text = "" if param.unit == TOGGLE else param.unit

    def draw(self, value: float, changed: bool, editing_text: str | None) -> None:
        fraction = self.param.fraction(value)
        self.fill.scale_x = max(.0001, TRACK_WIDTH * fraction)
        self.knob.x = self.track_left + TRACK_WIDTH * fraction
        if editing_text is not None:
            self.value.text = f"{editing_text}_"
            self.value.color = _EDITING
        else:
            self.value.text = ("ON" if value >= 1.0 else "OFF") if self.param.unit == TOGGLE else format_value(value)
            self.value.color = _IDLE
        self.value.text_color = _GOOD if changed else theme.TEXT

    def fraction_at(self, mouse_x: float) -> float:
        return max(0.0, min(1.0, (mouse_x - self.track_left) / TRACK_WIDTH))

    def begin_drag(self) -> None:
        self.panel.begin_drag(self)

    def begin_edit(self) -> None:
        if self.param.unit == TOGGLE:  # a switch: one click, and nothing to type
            self.panel.toggle(self)
        else:
            self.panel.begin_edit(self)


class _AbilityCard:
    """One ability: its name, key, description, status and three values."""

    def __init__(self, panel, x: float, top: float) -> None:
        self.panel = panel
        self.ability = None
        y = top - CARD_HEIGHT * .5
        self.background = Entity(parent=panel, model="quad", position=(x, y, .01),
                                 scale=(CARD_WIDTH, CARD_HEIGHT), color=_CARD, collider=None)
        left = x - CARD_WIDTH * .5 + .012
        self.name = Text(parent=panel, text="", position=(left, top - .022), origin=(-.5, 0),
                         scale=.8, color=color.white)
        self.meta = Text(parent=panel, text="", position=(left, top - .048), origin=(-.5, 0),
                         scale=.56, color=_GOLD)
        self.state = Text(parent=panel, text="", position=(x + CARD_WIDTH * .5 - .012, top - .048),
                          origin=(.5, 0), scale=.56, color=_GOOD)
        self.description = Text(parent=panel, text="", position=(left, top - .066), origin=(-.5, .5),
                                scale=.54, color=_MUTED)
        self.rows = {key: _ParamRow(panel, self, key, x, top + offset)
                     for key, offset in zip(PARAM_KEYS, ROW_OFFSETS)}
        self.reset_button = _button(panel, "RESET ABILITY", (x + .185, top - .316), (.14, .028),
                                    self.reset, text_scale=.6)

    def hide(self) -> None:
        """A character with fewer abilities leaves this space empty."""
        self.ability = None
        for item in (self.background, self.name, self.meta, self.state, self.description,
                     self.reset_button):
            item.enabled = False
        for row in self.rows.values():
            row.label.enabled = False
            row.not_applicable.enabled = False
            for item in row.items:
                item.enabled = False
            row.param = None

    def bind(self, ability) -> None:
        self.ability = ability
        for item in (self.background, self.name, self.meta, self.state, self.description,
                     self.reset_button):
            item.enabled = True
        for row in self.rows.values():
            row.label.enabled = True
        self.name.text = ability.name
        self.meta.text = f"{TYPE_LABELS[ability.kind]}   |   Key: {ability.binding}"
        self.description.text = fill(ability.description, 74)
        for key, row in self.rows.items():
            row.bind(ability.param(key))

    def reset(self) -> None:
        self.panel.reset_ability(self.ability.ability_id)


class _CharacterSettings:
    """The character-level rows, built like a card's rows so all edits share one path."""

    def __init__(self, panel) -> None:
        self.ability = None
        self.rows = {key: _ParamRow(panel, self, key, CHARACTER_ROW_X, y, label_x=CARD_COLUMNS[0] - .25)
                     for key, y in CHARACTER_ROWS.items()}
        self.rows.update({key: _ParamRow(panel, self, key, MOVEMENT_ROW_X, y, label_x=MOVEMENT_ROW_X - .3)
                          for key, y in MOVEMENT_ROWS.items()})

    def bind(self, character_id: str) -> None:
        self.ability = character_settings(character_id)
        for key, row in self.rows.items():
            row.bind(self.ability.param(key))


class _SquadSettings:
    """Who Omni-Man's key 1 calls and for how long, in the space his five cards leave free."""

    def __init__(self, panel, x: float, top: float) -> None:
        self.panel = panel
        self.ability = None
        self.background = Entity(parent=panel, model="quad", position=(x, top - CARD_HEIGHT * .5, .01),
                                 scale=(CARD_WIDTH, CARD_HEIGHT), color=_CARD, collider=None)
        left = x - CARD_WIDTH * .5 + .012
        self.name = Text(parent=panel, text="SQUAD SUMMONING", position=(left, top - .022), origin=(-.5, 0), scale=.8,
                         color=color.white)
        self.rows = {key: _ParamRow(panel, self, key, x + .05, top + y, label_x=x - .25)
                     for key, y in SQUAD_ROWS.items()}
        self.inactive = Text(parent=panel, text="", position=(left, top - .262), origin=(-.5, 0), scale=.6, color=_GOLD)
        self.reset_button = _button(panel, "RESET TO DEFAULT", (x + .165, top - .316), (.18, .028), panel.reset_squad,
                                    text_scale=.6)

    def bind(self, character_id: str) -> None:
        shown = character_id == "GREEN"
        self.ability = ability_of("GREEN", "squad_summon") if shown else None
        for item in (self.background, self.name, self.inactive, self.reset_button):
            item.enabled = shown
        for key, row in self.rows.items():
            row.label.enabled = shown
            row.not_applicable.enabled = False
            if shown:
                row.bind(self.ability.param(key))
            else:
                row.param = None
                for item in row.items:
                    item.enabled = False

    def refresh(self) -> None:
        if self.ability is None:
            return
        current = self.panel.current
        cycle = current("GREEN", "squad_summon", SQUAD_CYCLE)
        active = min(current("GREEN", "squad_summon", SQUAD_ACTIVE), cycle)
        self.inactive.text = f"Out for {active:.0f} s, then away for {cycle - active:.0f} s, every {cycle:.0f} s"


class CharacterPowerPanel(Entity):
    def __init__(self, game, **kwargs) -> None:
        kwargs.setdefault("parent", camera.ui)
        kwargs.setdefault("model", None)
        with _DefaultShader():
            super().__init__(**kwargs)
            self.game = game
            self.store = game.combat.settings
            self.character_id = default_player()
            # character -> ability -> parameter -> value
            self.pending: dict[str, dict[str, dict[str, float]]] = {}
            self.dragging: _ParamRow | None = None
            self.editing: _ParamRow | None = None
            self.buffer = ""
            self._replace_on_digit = False
            self._armed_reset: str | None = None
            self._build()
        self.visible = False
        self.enabled = False
        self.ignore_input = True  # keys come from GameManager.input; from Ursina as well, each digit counts twice
        set_dormant(self, True)

    # -- construction ----------------------------------------------------
    def _build(self) -> None:
        Entity(parent=self, model="quad", scale=(1.62, .985), z=.03, color=_BORDER)
        Entity(parent=self, model="quad", scale=(1.615, .98), z=.02, color=_PANEL)
        Text(parent=self, text="POWERS & ABILITIES", position=(0, .468), origin=(0, 0),
             scale=1.3, font=theme.TITLE_FONT, color=theme.TEXT)
        self.tabs = {}
        for index, character_id in enumerate(ROSTER_IDS):
            step = 1.6 / len(ROSTER_IDS)  # the tabs share the panel's width, however many there are
            x = -.8 + step * (index + .5)
            tab = _button(self, KITS[character_id].display, (x, .425), (step - .01, .046),
                          lambda chosen=character_id: self.select_character(chosen), text_scale=.9)
            Entity(parent=self, model="quad", position=(x, .399, -.001), scale=(step - .01, .006),
                   color=_CARD_TINTS[character_id], collider=None)
            self.tabs[character_id] = tab
        self.cards = [_AbilityCard(self, x, top) for top in CARD_TOPS for x in CARD_COLUMNS]
        self.character_card = _CharacterSettings(self)
        self.squad_card = _SquadSettings(self, CARD_COLUMNS[2], CARD_TOPS[1])
        y = -.336
        self.apply_button = _button(self, "APPLY", (-.665, y), (.17, .036), self.apply, tint=_ACTIVE)
        self.apply_button.text_color = theme.TEXT
        self.max_button = _button(self, "MAX ALL", (-.485, y), (.17, .036), self.max_character)
        self.max_all_button = _button(self, "MAX ALL CHARACTERS", (-.265, y), (.25, .036), self.max_all)
        self.reset_character_button = _button(self, "RESET CHARACTER", (-.015, y), (.23, .036),
                                              self.reset_character)
        self.reset_all_button = _button(self, "RESET ALL", (.185, y), (.15, .036), self.reset_all)
        self.close_button = _button(self, "CLOSE", (.68, y), (.2, .036), self.close_from_button)
        self.reset_movement_button = _button(self, "RESET SPEEDS", (.345, -.405), (.135, .03), self.reset_movement,
                                             text_scale=.6)
        self.status = Text(parent=self, text="", position=(.61, -.388), origin=(0, 0), scale=.6,
                           color=_GOOD)
        self.pending_text = Text(parent=self, text="", position=(.61, -.42), origin=(0, 0), scale=.6,
                                 color=_WARN)
        Text(parent=self, text="Drag a slider, or click a value and type. Changes take effect on Apply; closing "
                               f"applies them too. Healing Speed 100% refills a full bar in {FULL_HEAL_SECONDS:.0f} s. "
                               "Boost multiplies Flying Speed. Soldier Boy always outruns the fastest flyer.",
             position=(0, -.452), origin=(0, 0), scale=.5, color=_MUTED)

    # -- open and close --------------------------------------------------
    def open(self) -> None:
        self.visible = True
        self.enabled = True
        set_dormant(self, False)
        self.character_id = self.game.sentry.kit.character_id
        self.dragging = None
        self.editing = None
        self._armed_reset = None
        self.status.text = ""
        self.refresh()

    def close(self) -> None:
        self.commit_edit()
        self.dragging = None
        if self.has_pending:
            self.apply()
        self.visible = False
        self.enabled = False
        set_dormant(self, True)

    def close_from_button(self) -> None:
        self.game.toggle_power_panel()

    @property
    def has_pending(self) -> bool:
        return bool(self.pending)

    # -- navigation ------------------------------------------------------
    def select_character(self, character_id: str) -> None:
        self.commit_edit()
        self.character_id = character_id
        self._armed_reset = None
        self.refresh()

    def card_of(self, ability_id: str) -> _AbilityCard:
        return next(card for card in self.cards
                    if card.ability is not None and card.ability.ability_id == ability_id)

    # -- values ----------------------------------------------------------
    def saved(self, character_id: str, ability_id: str, key: str) -> float:
        """A speed nobody has chosen shows what the character moves at now, not a number of its own."""
        if key in MOVEMENT_KEYS and self.store.chosen(character_id, ability_id, key) is None:
            body = self.game.teams.characters[character_id]
            return float(round({RUN_SPEED: body.default_run_speed, FLY_SPEED: body.default_fly_speed,
                                BOOST_SPEED: body.default_boost_speed}[key]))
        return self.store.get(character_id, ability_id, key)

    def current(self, character_id: str, ability_id: str, key: str) -> float:
        pending = self.pending.get(character_id, {}).get(ability_id, {})
        return pending[key] if key in pending else self.saved(character_id, ability_id, key)

    def set_pending(self, row: _ParamRow, value: float) -> float:
        """Slider and box both end here, so they can never disagree."""
        param = row.param
        clamped = param.clamp(value)
        character_id, ability_id = self.character_id, row.card.ability.ability_id
        if clamped == self.saved(character_id, ability_id, param.key):
            table = self.pending.get(character_id, {}).get(ability_id, {})
            table.pop(param.key, None)
            if not table:
                self.pending.get(character_id, {}).pop(ability_id, None)
            if not self.pending.get(character_id, True):
                self.pending.pop(character_id, None)
        else:
            self.pending.setdefault(character_id, {}).setdefault(ability_id, {})[param.key] = clamped
        self._draw_pending()
        return clamped

    # -- slider ----------------------------------------------------------
    def begin_drag(self, row: _ParamRow) -> None:
        self.commit_edit()
        self.dragging = row
        self.drag_to(mouse.x)

    def drag_to(self, mouse_x: float) -> None:
        row = self.dragging
        if row is None or row.param is None:
            return
        self.set_pending(row, row.param.value_at(row.fraction_at(mouse_x)))
        self.refresh_rows()

    # -- typed values ----------------------------------------------------
    def begin_edit(self, row: _ParamRow) -> None:
        self.commit_edit()
        self.editing = row
        self.buffer = format_value(self.current(self.character_id, row.card.ability.ability_id,
                                                row.param.key))
        self._replace_on_digit = True
        self.refresh_rows()

    def commit_edit(self) -> None:
        row, self.editing = self.editing, None
        if row is None or row.param is None:
            return
        param = row.param
        try:
            typed = float(self.buffer)
        except ValueError:
            self._say(f"'{self.buffer}' is not a number; value unchanged", _WARN)
            self.refresh_rows()
            return
        stored = self.set_pending(row, typed)
        if abs(stored - typed) >= .5:
            self._say(f"{param.label}: {typed:g} adjusted to {format_value(stored)} "
                      f"(allowed {param.minimum:g} to {param.maximum:g})", _WARN)
        self.refresh_rows()

    def toggle(self, row: _ParamRow) -> None:
        self.commit_edit()
        value = self.current(self.character_id, row.card.ability.ability_id, row.param.key)
        self.set_pending(row, 0.0 if value >= 1.0 else 1.0)
        self.refresh_rows()

    def input(self, key: str) -> None:
        if key == "left mouse up":
            self.dragging = None
            return
        if self.editing is None:
            return
        if key in ("enter", "return"):
            self.commit_edit()
            return
        if key == "backspace":
            self._replace_on_digit = False
            self.buffer = self.buffer[:-1]
        elif len(key) == 1 and key.isdigit():
            self.buffer = key if self._replace_on_digit else self.buffer + key
            self._replace_on_digit = False
        elif key in (".", "period") and "." not in self.buffer:
            self.buffer = "0." if self._replace_on_digit else self.buffer + "."
            self._replace_on_digit = False
        else:
            return
        self.buffer = self.buffer[:12]
        self.refresh_rows()

    def update(self) -> None:
        """Only runs while the menu is open, and does work only during a drag."""
        if self.dragging is not None:
            if not mouse.left:
                self.dragging = None
            else:
                self.drag_to(mouse.x)

    # -- actions ---------------------------------------------------------
    def _commit_store(self, message: str) -> bool:
        """Save the stored values and hand them to the game at once."""
        saved = self.store.save()
        self.game.combat.apply_settings()
        self._say(message if saved else f"{message}, but could not save to disk",
                  _GOOD if saved else _WARN)
        self.refresh()
        return saved

    def apply(self) -> bool:
        self.commit_edit()
        for character_id, abilities in self.pending.items():
            for ability_id, values in abilities.items():
                for key, value in values.items():
                    self.store.set(character_id, ability_id, key, value)
        self.pending.clear()
        message = "Applied and saved"
        if self.store.fit_squad_times():
            message = "Saved: Active Time cut to the length of the cycle"
        return self._commit_store(message)

    def max_character(self) -> None:
        self.commit_edit()
        self.pending.pop(self.character_id, None)
        self.store.max_character(self.character_id)
        self._armed_reset = None
        self._commit_store(f"{KITS[self.character_id].display} set to maximum")

    def max_all(self) -> None:
        self.commit_edit()
        self.pending.clear()
        self.store.max_all()
        self._armed_reset = None
        self._commit_store("All five characters set to maximum")

    def reset_ability(self, ability_id: str) -> None:
        self.commit_edit()
        character_id = self.character_id
        self.pending.get(character_id, {}).pop(ability_id, None)
        if not self.pending.get(character_id, True):
            self.pending.pop(character_id, None)
        self.store.reset_ability(character_id, ability_id)
        self._commit_store(f"{ABILITIES[character_id][ability_id].name} restored to defaults")

    def reset_squad(self) -> None:
        """Back to five Viltrumites and Mark, for 30 seconds in every 60. His Range is left as it is."""
        self.commit_edit()
        waiting = self.pending.get("GREEN", {}).get("squad_summon", {})
        for key in SQUAD_KEYS:
            waiting.pop(key, None)
        if not waiting:
            self.pending.get("GREEN", {}).pop("squad_summon", None)
        if not self.pending.get("GREEN", True):
            self.pending.pop("GREEN", None)
        self.store.reset_squad()
        self._commit_store("Squad summoning back to default")

    def reset_movement(self) -> None:
        """Back to Default: this character's speeds only, and nothing else about it."""
        self.commit_edit()
        character_id = self.character_id
        waiting = self.pending.get(character_id, {}).get(CHARACTER, {})
        for key in MOVEMENT_KEYS:
            waiting.pop(key, None)
        if not waiting:
            self.pending.get(character_id, {}).pop(CHARACTER, None)
        if not self.pending.get(character_id, True):
            self.pending.pop(character_id, None)
        self.store.reset_movement(character_id)
        self._commit_store(f"{KITS[character_id].display}: speeds back to default")

    def _confirmed(self, which: str, prompt: str) -> bool:
        if self._armed_reset != which:
            self._armed_reset = which
            self._say(prompt, _WARN)
            return False
        self._armed_reset = None
        return True

    def reset_character(self) -> None:
        name = KITS[self.character_id].display
        if not self._confirmed(self.character_id, f"Click RESET CHARACTER again to reset all of {name}"):
            return
        self.commit_edit()
        self.pending.pop(self.character_id, None)
        self.store.reset_character(self.character_id)
        self._commit_store(f"{name} restored to defaults")

    def reset_all(self) -> None:
        if not self._confirmed("all", "Click RESET ALL again to reset all five characters"):
            return
        self.commit_edit()
        self.pending.clear()
        self.store.reset_all()
        self._commit_store("All five characters restored to defaults")

    def _say(self, message: str, tint) -> None:
        self.status.text = message
        self.status.color = tint

    # -- drawing ---------------------------------------------------------
    def refresh(self) -> None:
        for character_id, tab in self.tabs.items():
            selected = character_id == self.character_id
            tab.color = _ACTIVE if selected else _IDLE
            tab.text_color = theme.TEXT if selected else color.white
        self.character_card.bind(self.character_id)
        self.squad_card.bind(self.character_id)
        abilities = SCHEMA[self.character_id]
        powers = self.game.teams.characters[self.character_id].powers
        for card in self.cards[len(abilities):]:
            card.hide()
        if self.squad_card.ability is not None:  # it lies on top of the sixth card, which he has no use for
            self.cards[len(abilities)].background.enabled = False
        for card, ability in zip(self.cards, abilities):
            card.bind(ability)
            state = powers.abilities[ability.ability_id].hud_state()
            card.state.text = _STATES.get(state, state)
        self.refresh_rows()
        self._draw_pending()

    def refresh_rows(self) -> None:
        self.squad_card.refresh()
        for card in (*self.cards, self.character_card, self.squad_card):
            if card.ability is None:
                continue
            ability_id = card.ability.ability_id
            pending = self.pending.get(self.character_id, {}).get(ability_id, {})
            for row in card.rows.values():
                if row.param is not None:
                    value = self.current(self.character_id, ability_id, row.param.key)
                    row.draw(value, row.param.key in pending,
                             self.buffer if row is self.editing else None)

    def _draw_pending(self) -> None:
        count = sum(len(values) for abilities in self.pending.values()
                    for values in abilities.values())
        self.pending_text.text = (f"{count} unsaved change{'s' if count != 1 else ''}: "
                                  "press APPLY" if count else "")


__all__ = ["CharacterPowerPanel", "MAX_CARDS", "format_value"]
