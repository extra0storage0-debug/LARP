"""The full settings screen: two profiles, eleven categories, exact integer entry."""

from __future__ import annotations

from ursina import Button, Entity, Text, camera, color

from ui import theme

from config.sentry_profiles import (CATEGORIES, ENEMY, LIVE, MAX_INPUT_DIGITS, PLAYER,
                                    PROFILE_LABELS, SETTINGS, coerce)
from game.controls import binding_conflict, normalize_key
from ui.enemy_team_ui import set_dormant

ROWS_PER_PAGE = 13
ROW_TOP = .305
ROW_STEP = .0495
_GOLD = theme.TEXT
_NORMAL_BOX = theme.STEEL_DARK
_EDIT_BOX = theme.ACCENT_DIMMER
_CHANGED_TEXT = theme.SUCCESS
_VALUE_TEXT = theme.TEXT
_IGNORED_KEY_SUFFIXES = (" up", " hold")
_IGNORED_CAPTURE = {"mouse1", "mouse2", "mouse3", "scroll up", "scroll down"}


def _button(parent, text, position, scale, *, active=False) -> Button:
    return Button(parent=parent, text=text, position=position, scale=scale, model="quad",
                  color=theme.ACCENT if active else theme.STEEL,
                  highlight_color=theme.ACCENT_HOVER,
                  text_color=theme.TEXT if active else color.white)


class ProfileSettingsPage(Entity):
    """Shows one category of one profile; changes wait in ``pending`` until Apply."""

    def __init__(self, game, panel, **kwargs) -> None:
        kwargs.setdefault("parent", camera.ui)
        kwargs.setdefault("model", None)
        super().__init__(**kwargs)
        self.game = game
        self.panel = panel
        self.store = game.profiles
        self.profile = PLAYER
        self.category = "camera"
        self.page = 0
        self.pending: dict[str, dict[str, object]] = {PLAYER: {}, ENEMY: {}}
        self.editing: str | None = None
        self.capturing: str | None = None
        self.buffer = ""
        self._replace_prefix: str | None = None  # set until the first digit replaces the value
        self._visible_keys: list[str] = []
        self._build()
        self.enabled = False
        set_dormant(self, True)

    # -- construction ----------------------------------------------------
    def _build(self) -> None:
        Entity(parent=self, model="quad", scale=(1.54, .95), z=.02,
               color=theme.ACCENT)
        Entity(parent=self, model="quad", scale=(1.535, .945), z=.01,
               color=theme.PANEL)
        Text(parent=self, text="GAME SETTINGS", position=(-.615, .375), origin=(0, 0), scale=1.2, font=theme.TITLE_FONT, color=theme.TEXT)
        self.profile_buttons = {}
        for index, profile in enumerate((PLAYER, ENEMY)):
            button = _button(self, PROFILE_LABELS[profile], (-.42 + index * .46, .425), (.44, .042))
            button.on_click = lambda chosen=profile: self.show_profile(chosen)
            self.profile_buttons[profile] = button
        self.close_button = _button(self, "BACK", (.67, .425), (.14, .042))
        self.close_button.on_click = self.close
        self.category_buttons = {}
        for index, (category, label) in enumerate(CATEGORIES):
            button = _button(self, label, (-.615, .305 - index * .055), (.27, .047))
            button.on_click = lambda chosen=category: self.show_category(chosen)
            self.category_buttons[category] = button
        self.row_labels, self.row_tags, self.row_values = [], [], []
        for index in range(ROWS_PER_PAGE):
            y = ROW_TOP - index * ROW_STEP
            self.row_labels.append(Text(parent=self, text="", position=(-.455, y), scale=.86,
                                        origin=(-.5, 0), color=color.white))
            self.row_tags.append(Text(parent=self, text="", position=(.335, y), scale=.62,
                                      origin=(0, 0), color=theme.WARNING))
            value = _button(self, "", (.56, y), (.31, .043))
            value.color = _NORMAL_BOX
            value.on_click = lambda row=index: self.click_row(row)
            self.row_values.append(value)
        self.previous_button = _button(self, "< PREV", (-.40, -.345), (.12, .04))
        self.previous_button.on_click = lambda: self.turn_page(-1)
        self.next_button = _button(self, "NEXT >", (-.27, -.345), (.12, .04))
        self.next_button.on_click = lambda: self.turn_page(1)
        self.page_text = Text(parent=self, text="", position=(-.13, -.345), scale=.74,
                              origin=(0, 0), color=color.gray)
        self.apply_button = _button(self, "APPLY & SAVE", (-.40, -.405), (.24, .046), active=True)
        self.apply_button.on_click = self.apply
        self.reset_category_button = _button(self, "RESET CATEGORY", (-.135, -.405), (.26, .046))
        self.reset_category_button.on_click = self.reset_category
        self.reset_profile_button = _button(self, "RESET PROFILE", (.15, -.405), (.25, .046))
        self.reset_profile_button.on_click = self.reset_profile
        self.status = Text(parent=self, text="", position=(.40, -.345), scale=.76,
                           origin=(0, 0), color=_CHANGED_TEXT)
        self.hint = Text(parent=self, text="Click a value, type a new number, press Enter. "
                                           "Closing saves. RESPAWN settings apply next battle.",
                         position=(.0, -.45), scale=.68, origin=(0, 0), color=color.gray)
        for button in self._all_buttons():
            if button.text_entity is not None:
                button.text_entity.scale *= .82

    def _all_buttons(self):
        return (*self.profile_buttons.values(), *self.category_buttons.values(), *self.row_values,
                self.close_button, self.previous_button, self.next_button, self.apply_button,
                self.reset_category_button, self.reset_profile_button)

    # -- navigation ------------------------------------------------------
    def _set_hud_hidden(self, hidden: bool) -> None:
        """Clear the HUD so its text cannot show through this full-screen page."""
        self.game.hud.set_atlas_visible(hidden)

    def open(self) -> None:
        self.enabled = True
        set_dormant(self, False)
        self._set_hud_hidden(True)
        self.show_profile(self.profile)

    def close(self) -> None:
        self.commit_edit()
        self.capturing = None
        if any(self.pending.values()):
            self.apply()
        self.enabled = False
        set_dormant(self, True)
        self._set_hud_hidden(False)
        self.panel.page_closed()

    def categories_for(self, profile: str) -> list[str]:
        used = {setting.category for setting in SETTINGS[profile].values()}
        return [category for category, _label in CATEGORIES if category in used]

    def show_profile(self, profile: str) -> None:
        self.commit_edit()
        self.profile = profile
        if self.category not in self.categories_for(profile):
            self.category = "camera"
        self.page = 0
        self.refresh()

    def show_category(self, category: str) -> None:
        self.commit_edit()
        self.category = category
        self.page = 0
        self.refresh()

    def turn_page(self, step: int) -> None:
        self.commit_edit()
        self.page += step
        self.refresh()

    def keys_in_category(self) -> list[str]:
        return [key for key, setting in SETTINGS[self.profile].items()
                if setting.category == self.category]

    # -- drawing ---------------------------------------------------------
    def current_value(self, key: str):
        pending = self.pending[self.profile]
        return pending[key] if key in pending else self.store.get(self.profile, key)

    def _display(self, key: str) -> str:
        setting = SETTINGS[self.profile][key]
        value = self.current_value(key)
        if key == self.editing:
            return f"{self.buffer}_"
        if key == self.capturing:
            return "PRESS A KEY..."
        if setting.kind == "toggle":
            return "ON" if value else "OFF"
        if setting.kind == "key":
            return str(value).upper()
        return str(value)

    def refresh(self) -> None:
        for profile, button in self.profile_buttons.items():
            button.color = theme.ACCENT if profile == self.profile \
                else theme.STEEL
            button.text_color = theme.TEXT if profile == self.profile else color.white
        available = self.categories_for(self.profile)
        for category, button in self.category_buttons.items():
            button.enabled = category in available
            selected = category == self.category
            button.color = theme.ACCENT_LINE_DIM if selected else theme.STEEL
        keys = self.keys_in_category()
        pages = max(1, (len(keys) + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE)
        self.page = max(0, min(pages - 1, self.page))
        start = self.page * ROWS_PER_PAGE
        self._visible_keys = keys[start:start + ROWS_PER_PAGE]
        for row in range(ROWS_PER_PAGE):
            present = row < len(self._visible_keys)
            self.row_labels[row].enabled = self.row_tags[row].enabled = present
            self.row_values[row].enabled = present
            if present:
                self._draw_row(row)
        self.page_text.text = f"PAGE {self.page + 1}/{pages}"
        self.previous_button.enabled = self.page > 0
        self.next_button.enabled = self.page < pages - 1

    def _draw_row(self, row: int) -> None:
        key = self._visible_keys[row]
        setting = SETTINGS[self.profile][key]
        self.row_labels[row].text = setting.label
        self.row_tags[row].text = "" if setting.applies == LIVE else "RESPAWN"
        button = self.row_values[row]
        button.text = self._display(key)
        active = key in (self.editing, self.capturing)
        button.color = _EDIT_BOX if active else _NORMAL_BOX
        changed = key in self.pending[self.profile]
        button.text_color = _CHANGED_TEXT if changed else _VALUE_TEXT

    def _say(self, message: str) -> None:
        self.status.text = message

    # -- editing ---------------------------------------------------------
    def click_row(self, row: int) -> None:
        if row >= len(self._visible_keys):
            return
        key = self._visible_keys[row]
        setting = SETTINGS[self.profile][key]
        self._say("")
        self.commit_edit()
        self.capturing = None
        if setting.kind == "toggle":
            self.pending[self.profile][key] = 0 if self.current_value(key) else 1
        elif setting.kind == "key":
            self.capturing = key
        else:
            self.editing = key
            self.buffer = str(self.current_value(key))
            self._replace_prefix = ""
        self.refresh()

    def commit_edit(self) -> None:
        """Keep the typed number exactly, or refuse it and say why."""
        if self.editing is None:
            return
        key, self.editing = self.editing, None
        setting = SETTINGS[self.profile][key]
        try:
            value = coerce(setting, self.buffer)
        except (ValueError, TypeError, OverflowError) as error:
            self._say(f"{error}; value unchanged")
            return
        if value != int(self.store.get(self.profile, key)):
            self.pending[self.profile][key] = value
        else:
            self.pending[self.profile].pop(key, None)

    def input(self, key: str) -> None:
        if key.endswith(_IGNORED_KEY_SUFFIXES):
            return
        if self.capturing is not None:
            self._capture(key)
            return
        if self.editing is None:
            return
        if key.isdigit() and len(key) == 1:
            if self._replace_prefix is not None:
                self.buffer, self._replace_prefix = self._replace_prefix, None
            if self.buffer in ("0", "-0"):
                self.buffer = self.buffer[:-1]
            if len(self.buffer.lstrip("-")) < MAX_INPUT_DIGITS:
                self.buffer += key
            else:
                self._say(f"{MAX_INPUT_DIGITS} digits maximum")
        elif key in ("-", "minus") and SETTINGS[self.profile][self.editing].minimum < 0:
            self.buffer = self.buffer[1:] if self.buffer.startswith("-") else f"-{self.buffer}"
            if self._replace_prefix is not None:
                self._replace_prefix = "-" if self.buffer.startswith("-") else ""
        elif key == "backspace":
            self._replace_prefix = None
            self.buffer = self.buffer[:-1] or "0"
        elif key in ("enter", "return"):
            self.commit_edit()
        self.refresh()

    def _capture(self, key: str) -> None:
        if key in _IGNORED_CAPTURE or key == "escape":
            return
        chosen = normalize_key(key)
        target = self.capturing
        action = target.removeprefix("key_")
        others = {name.removeprefix("key_"): value
                  for name, value in self.pending[PLAYER].items() if name.startswith("key_")}
        conflict = binding_conflict(action, chosen, others)
        self.capturing = None
        if conflict is not None:
            self._say(f"{chosen.upper()} is {'reserved' if conflict == 'reserved' else 'used by ' + conflict}")
        else:
            self.pending[PLAYER][target] = chosen
        self.refresh()

    # -- saving ----------------------------------------------------------
    def apply(self) -> bool:
        self.commit_edit()
        for profile, values in self.pending.items():
            for key, value in values.items():
                self.store.set(profile, key, value, notify=False)
            values.clear()
        saved = self.store.save()
        self.game.apply_sentry_config()
        self._say("Saved" if saved else "Could not save to disk")
        self.refresh()
        return saved

    def reset_category(self) -> None:
        self.editing = self.capturing = None
        for key in self.keys_in_category():
            self.pending[self.profile].pop(key, None)
        self.store.reset(self.profile, self.category)
        self.store.save()
        self.game.apply_sentry_config()
        self._say("Controls restored" if self.category == "input" else "Category reset")
        self.refresh()

    def reset_profile(self) -> None:
        self.editing = self.capturing = None
        self.pending[self.profile].clear()
        self.store.reset(self.profile)
        self.store.save()
        self.game.apply_sentry_config()
        self._say(f"{PROFILE_LABELS[self.profile]} reset")
        self.refresh()
