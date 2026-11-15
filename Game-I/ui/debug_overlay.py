"""Optional readouts; nothing here runs while its toggle is off."""

from __future__ import annotations

from ursina import Text, camera, color

from ui.enemy_team_ui import _DefaultShader

REFRESH_SECONDS = .25
INDICATOR_TOGGLES = ("show_fps", "show_collision_info", "show_debug_info")


class DebugOverlay:
    def __init__(self, game) -> None:
        self.game = game
        self._timer = 0.0
        self._frames = 0
        self._elapsed = 0.0
        self._fps = 0.0
        self._panel = None

    def _text_panel(self) -> Text:
        if self._panel is None:
            with _DefaultShader():
                self._panel = Text(parent=camera.ui, text="", position=(.40, .38), scale=.72,
                                   origin=(-.5, .5), color=color.rgb32(186, 240, 196))
        return self._panel

    def update(self, dt: float) -> None:
        tuning = self.game.tuning
        self._frames += 1
        self._elapsed += dt
        self._timer += dt
        if self._timer >= REFRESH_SECONDS:
            self._timer = 0.0
            self._refresh_text(tuning)

    def _refresh_text(self, tuning) -> None:
        if self._elapsed > 0.0:
            self._fps = self._frames / self._elapsed
        self._frames, self._elapsed = 0, 0.0
        if not any(tuning.flag(key, False) for key in INDICATOR_TOGGLES):
            if self._panel is not None and self._panel.text:
                self._panel.text = ""
            return
        self._text_panel().text = "\n".join(self.lines(tuning))

    def lines(self, tuning) -> list[str]:
        """The enabled readouts, each toggle independent of the others."""
        game = self.game
        sentry = game.sentry
        lines = []
        if tuning.flag("show_fps", False):
            lines.append(f"FPS {self._fps:.0f}")
        if tuning.flag("show_collision_info", False):
            ground = game.world.height_at(sentry.x, sentry.z)
            trees = sum(1 for _ in game.world._nearby_tree_colliders(sentry.x, sentry.z, 1))
            lines.append(f"GROUND {ground:.1f} m  CLEARANCE {sentry.y - ground:.1f} m")
            lines.append(f"TREES NEARBY {trees}")
        if tuning.flag("show_debug_info", False):
            world = game.world
            lines.append(f"CHUNKS {len(world.chunks)}  EFFECTS {len(world.effects)}")
            lines.append(f"PHASE {sentry.flight.phase.name}  "
                         f"POS {sentry.x:.0f},{sentry.y:.0f},{sentry.z:.0f}")
        return lines
