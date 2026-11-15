"""The Esc menu, and Graphics Settings: the only place graphics quality can be changed."""

from __future__ import annotations

from ursina import Button, Entity, Text, camera, color

from ui import theme

from config import RESOLUTIONS, resolution_of
from ui.enemy_team_ui import set_dormant

_IDLE = theme.STEEL
_HOVER = theme.ACCENT_HOVER
_ACTIVE = theme.ACCENT
QUALITIES = ("low", "medium", "high", "ultra")
AUTO_LOCK_LABEL = "AUTO TARGET LOCK  (8):  {}"


class PauseMenu(Entity):
    def __init__(self, game, **kwargs) -> None:
        kwargs.setdefault("parent", camera.ui)
        kwargs.setdefault("model", None)
        super().__init__(**kwargs)
        self.game = game
        Entity(parent=self, model="quad", scale=(.74, .985), z=.02, color=theme.ACCENT)
        Entity(parent=self, model="quad", scale=(.735, .98), z=.01, color=theme.PANEL)
        Text(parent=self, text="PAUSED", origin=(0, 0), y=.445, scale=2.0, font=theme.TITLE_FONT, color=theme.TEXT)
        self.main_buttons = []
        for index, (label, action) in enumerate((
                ("RESUME  (Esc)", game.toggle_pause),
                ("SAVE GAME", self._save_game),
                ("LOAD GAME", self._load_game),
                ("CHARACTER SELECTION  (M)", self._open_switcher),
                ("POWERS & ABILITIES  (P)", self._open_powers),
                ("GAME SETTINGS", self._open_settings),
                ("GRAPHICS SETTINGS", self.show_graphics),
                (AUTO_LOCK_LABEL.format("OFF"), self.toggle_auto_lock),
                ("RESTORE ISLAND LANDMARKS", self._restore_landmarks),
                ("MAIN MENU", game.return_to_title))):
            button = self._button(label, (0, .395 - index * .052), action, height=.046)
            self.main_buttons.append(button)
        self.auto_lock_button = self.main_buttons[7]
        self.message = Text(parent=self, text="", origin=(0, 0), y=-.145, scale=.86,
                            color=theme.SUCCESS)
        self.help = Text(parent=self, origin=(0, .5), y=-.18, scale=.82,
                         color=theme.TEXT_MUTED,
                         text="WASD move   Mouse look   Wheel zoom   + punch   - kick\n"
                              "Space jump/rise   Ctrl descend   Shift run/boost   F fly\n"
                              "Q lock target   Wheel next target or zoom   1-4 abilities   T stop time\n"
                              "Tab info   M switch character   P powers   C camera")
        # Graphics Settings
        self.graphics_title = Text(parent=self, text="GRAPHICS SETTINGS", origin=(0, 0), y=.24,
                                   scale=1.3, font=theme.TITLE_FONT, color=theme.TEXT)
        self.quality_buttons = {}
        for index, quality in enumerate(QUALITIES):
            button = self._button(quality.upper(), (-.255 + index * .17, .15),
                                  lambda chosen=quality: self.choose_quality(chosen), width=.16)
            self.quality_buttons[quality] = button
        self.resolution_buttons = {}
        for index, resolution in enumerate(RESOLUTIONS):
            button = self._button(resolution.replace("x", " x "), (-.22 + index * .22, .07),
                                  lambda chosen=resolution: self.choose_resolution(chosen), width=.2)
            self.resolution_buttons[resolution] = button
        self.graphics_note = Text(parent=self, origin=(0, .5), y=.02, scale=.74,
                                  color=theme.TEXT_MUTED,
                                  text="Higher settings draw more terrain, shadows, debris and character detail.\n"
                                       "Ultra is for stronger machines than Iris Xe.\n"
                                       "Keys 1, 2 and 3 are ability slots and never change this.")
        self.back_button = self._button("BACK", (0, -.14), self.show_main)
        self.graphics_items = (self.graphics_title, *self.quality_buttons.values(),
                               *self.resolution_buttons.values(), self.graphics_note, self.back_button)
        self.show_main()
        self.enabled = False
        set_dormant(self, True)

    def _button(self, label, position, action, width: float = .62, height: float = .056) -> Button:
        button = Button(parent=self, text=label, position=position, scale=(width, height),
                        model="quad", color=_IDLE, highlight_color=_HOVER, text_color=color.white)
        button.text_entity.scale *= .8
        button.on_click = action
        return button

    def set_visible(self, visible: bool) -> None:
        self.enabled = visible
        set_dormant(self, not visible)
        if visible:
            self.message.text = ""
            self.show_main()
            self._mark_auto_lock()

    def show_main(self) -> None:
        for item in (*self.main_buttons, self.message, self.help):
            item.enabled = True
        for item in self.graphics_items:
            item.enabled = False

    def show_graphics(self) -> None:
        for item in (*self.main_buttons, self.message, self.help):
            item.enabled = False
        for item in self.graphics_items:
            item.enabled = True
        self._mark_quality()

    def _mark_quality(self) -> None:
        current = self.game.settings.quality.lower()
        for quality, button in self.quality_buttons.items():
            button.color = _ACTIVE if quality == current else _IDLE
            button.text_color = theme.TEXT if quality == current else color.white

        chosen = "x".join(str(value) for value in resolution_of(self.game.settings))
        for resolution, button in self.resolution_buttons.items():
            button.color = _ACTIVE if resolution == chosen else _IDLE
            button.text_color = theme.TEXT if resolution == chosen else color.white

    def choose_quality(self, quality: str) -> None:
        self.game.set_quality(quality)
        self._mark_quality()

    def choose_resolution(self, resolution: str) -> None:
        self.game.set_resolution(resolution)
        self._mark_quality()

    def toggle_auto_lock(self) -> None:
        self.game.toggle_auto_target_lock()
        self._mark_auto_lock()

    def _mark_auto_lock(self) -> None:
        on = self.game.teams.state.auto_target_lock
        self.auto_lock_button.text = AUTO_LOCK_LABEL.format("ON" if on else "OFF")

    def _open_switcher(self) -> None:
        self.game.toggle_team_panel()

    def _open_powers(self) -> None:
        self.game.toggle_power_panel()

    def _open_settings(self) -> None:
        self.game.open_settings_page()

    def _save_game(self) -> None:
        self.message.text = "Game saved" if self.game.save_game() else "The game could not be saved"

    def _load_game(self) -> None:
        self.message.text = "Game loaded" if self.game.load_game() else "There is no saved game to load"

    def _restore_landmarks(self) -> None:
        self.game.landmarks.restore_all()
        self.message.text = "Buildings, vehicles and boulders restored"


class SettingsMenu:
    """Labels for the quality presets."""

    LABELS = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "ultra": "ULTRA"}

    @classmethod
    def label(cls, quality: str) -> str:
        return cls.LABELS.get(quality.lower(), "MEDIUM")
