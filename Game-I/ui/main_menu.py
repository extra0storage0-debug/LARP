"""The title screen: what a launch opens on, and where the pause menu's MAIN MENU leads back to."""

from __future__ import annotations

from pathlib import Path

from ursina import Button, Entity, Text, Texture, application, camera, color

from characters.roster import KITS
from config.branding import TAGLINE
from config.character_roster import TEAM_LABELS
from ui import theme
from ui.enemy_team_ui import set_dormant

PORTRAITS = Path(__file__).resolve().parent.parent / "assets" / "portraits"
LEFT = -.46
BUTTON_TOP, BUTTON_STEP = -.02, .068
PORTRAIT_X, PORTRAIT_Y, PORTRAIT_SIZE = .46, .07, .56


class MainMenu(Entity):
    def __init__(self, game, **kwargs) -> None:
        kwargs.setdefault("parent", camera.ui)
        kwargs.setdefault("model", None)
        super().__init__(**kwargs)
        self.game = game
        self.started = False
        self._portraits: dict = {}
        Entity(parent=self, model="quad", scale=(4, 2), z=.5, color=color.white, texture=Texture(theme.BRANDING / "backdrop.jpg"))
        Entity(parent=self, model="quad", position=(LEFT, .27), z=.4, scale=(.68, .68 * 494 / 1236), color=color.white,
               texture=Texture(theme.BRANDING / "logo.png"))
        Text(parent=self, text=TAGLINE, position=(LEFT - .34, .075), origin=(-.5, 0), scale=1.15, color=theme.TEXT_MUTED)
        self.play_button = self._button("PLAY", 0, game.leave_title, primary=True)
        self.buttons = [self.play_button,
                        self._button("CHARACTER SELECTION", 1, game.toggle_team_panel),
                        self._button("POWERS & ABILITIES", 2, game.toggle_power_panel),
                        self._button("GAME SETTINGS", 3, game.open_settings_page),
                        self._button("QUIT", 4, application.quit)]
        Entity(parent=self, model="quad", position=(PORTRAIT_X, PORTRAIT_Y), z=.41, scale=(PORTRAIT_SIZE + .008, PORTRAIT_SIZE + .008), color=theme.ACCENT)
        self.portrait = Entity(parent=self, model="quad", position=(PORTRAIT_X, PORTRAIT_Y), z=.4, scale=(PORTRAIT_SIZE, PORTRAIT_SIZE), color=color.white)
        self.character_name = Text(parent=self, text="", position=(PORTRAIT_X, PORTRAIT_Y - PORTRAIT_SIZE / 2 - .05), origin=(0, 0), scale=2.0,
                                   font=theme.TITLE_FONT, color=theme.TEXT)
        self.character_team = Text(parent=self, text="", position=(PORTRAIT_X, PORTRAIT_Y - PORTRAIT_SIZE / 2 - .1), origin=(0, 0), scale=1.0,
                                   color=theme.ACCENT_BRIGHT)
        Text(parent=self, text="Enter  PLAY", position=(LEFT - .34, -.40), origin=(-.5, 0), scale=.8, color=theme.TEXT_FAINT)
        self.enabled = False
        set_dormant(self, True)

    def _button(self, label: str, index: int, action, primary: bool = False) -> Button:
        button = Button(parent=self, text=label, position=(LEFT, BUTTON_TOP - index * BUTTON_STEP), scale=(.68, .06), model="quad",
                        color=theme.ACCENT if primary else theme.STEEL, highlight_color=theme.ACCENT_BRIGHT if primary else theme.ACCENT_HOVER,
                        text_color=theme.TEXT)
        button.text_entity.scale *= 1.05
        button.on_click = action
        return button

    def _portrait_of(self, character_id: str):
        if character_id not in self._portraits:
            path = PORTRAITS / f"{character_id.lower()}.png"
            self._portraits[character_id] = Texture(path) if path.exists() else None
        return self._portraits[character_id]

    def refresh(self) -> None:
        state = self.game.teams.state
        kit = KITS[state.player]
        texture = self._portrait_of(state.player)
        self.portrait.texture = texture
        self.portrait.color = color.white if texture is not None else theme.STEEL_DARK
        self.character_name.text = kit.display
        self.character_team.text = TEAM_LABELS[state.team_of(state.player)]
        self.play_button.text = "CONTINUE" if self.started else "PLAY"

    def set_visible(self, visible: bool) -> None:
        self.enabled = visible
        set_dormant(self, not visible)
        if visible:
            self.refresh()
