"""Capture real gameplay lighting at day, dusk, night, high altitude, and space."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from panda3d.core import PNMImage
from ursina import application, window

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from main import build_game
from movement.flight_physics import FlightPhase


OUTPUT = Path(__file__).resolve().parent


def capture(base, game, filename: str, altitude: float, day_time: float) -> None:
    point = game.planet.point_from_local(0.0, 0.0, altitude + .25)
    game.sentry.position = (point.x, point.y, point.z)
    game.planet.orient_entity(game.sentry, point)
    game.sentry.flight.phase = (FlightPhase.GROUNDED if altitude == 0.0
                              else FlightPhase.CRUISE)
    game.sentry.flight.velocity = game.sentry.flight.velocity.__class__()

    chase = game.camera
    chase.pivot.position = (point.x, point.y, point.z)
    chase.yaw = 0.0
    chase.pitch = chase.DEFAULT_PITCH
    chase.distance = chase.DEFAULT_DISTANCE
    chase._reset_distance_timer = 0.0
    chase.update(.5)

    game.environment.elapsed = day_time
    game.environment._light_update_timer = 1.0
    game.environment._night_windows_timer = 1.0
    game.environment.update(0.0)
    game.hud.update()

    for _ in range(5):
        base.taskMgr.step()
        base.graphicsEngine.renderFrame()
    image = PNMImage()
    if not base.win.getScreenshot(image):
        raise RuntimeError(f"Could not capture {filename}")
    path = OUTPUT / filename
    relative_path = Path("Documentation") / filename
    if not image.write(relative_path.as_posix()):
        raise RuntimeError(f"Could not save {path}")
    print(path)


def main() -> int:
    app, game = build_game("onscreen")
    window.size = (1280, 720)
    game.paused = True
    try:
        for filename, altitude, day_time in (
            ("lighting_day_ground.png", 0.0, 360.0),
            ("lighting_sunset_ground.png", 0.0, 540.0),
            ("lighting_night_ground.png", 0.0, 0.0),
        ):
            capture(application.base, game, filename, altitude, day_time)
    finally:
        app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
