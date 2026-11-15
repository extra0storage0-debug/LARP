"""The screen while the world and the bodies load. Only a real launch has one; everything else just builds."""

from __future__ import annotations

from ursina import Entity, Text, Texture, application, camera, color, scene

from config.branding import TAGLINE
from ui import theme

BAR_WIDTH = .9
_current = None


class LoadingScreen:
    def __init__(self) -> None:
        self.items = [
            Entity(parent=camera.ui, model="quad", scale=(4, 2), z=.5, color=color.white, texture=Texture(theme.BRANDING / "backdrop.jpg")),
            Entity(parent=camera.ui, model="quad", position=(0, .1), z=.4, scale=(.92, .92 * 494 / 1236), color=color.white, texture=Texture(theme.BRANDING / "logo.png")),
            Text(parent=camera.ui, text=TAGLINE, position=(0, -.15), origin=(0, 0), z=.3, scale=1.3, color=theme.TEXT_MUTED),
            Entity(parent=camera.ui, model="quad", position=(0, -.25), z=.4, scale=(BAR_WIDTH, .01), color=theme.STEEL),
        ]
        self.fill = Entity(parent=camera.ui, model="quad", origin=(-.5, 0), position=(-BAR_WIDTH / 2, -.25), z=.3, scale=(.001, .01), color=theme.ACCENT)
        self.label = Text(parent=camera.ui, text="", position=(0, -.29), origin=(0, 0), z=.3, scale=.9, color=theme.TEXT_FAINT)
        self.items += [self.fill, self.label]

    def show(self, fraction: float, label: str) -> None:
        self.fill.scale_x = max(.001, BAR_WIDTH * fraction)
        self.label.text = label
        for _ in range(2):  # a threaded draw shows what the frame before it culled
            application.base.graphicsEngine.renderFrame()

    def destroy(self) -> None:
        from ursina import destroy
        for item in self.items:
            destroy(item)


def begin() -> None:
    global _current
    scene.hide()  # half a world has shaders with nothing yet to read; only this screen is drawn until it is whole
    _current = LoadingScreen()
    _current.show(.02, "STARTING")


def report(fraction: float, label: str) -> None:
    """Called by whatever is loading. Does nothing when no screen is up, which is every test and tool."""
    if _current is not None:
        _current.show(fraction, label)


def end() -> None:
    global _current
    if _current is not None:
        _current.destroy()
        _current = None
        scene.show()
