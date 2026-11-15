"""Capture real gameplay frames for the directional flight pose checks."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from panda3d.core import LQuaternionf, PNMImage
from ursina import application, window

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from main import build_game
from movement.flight_physics import FlightPhase, Vec3


OUTPUT = Path(__file__).resolve().parent


def capture(base, game, name: str, velocity: Vec3, move: Vec3,
            vertical: float = 0.0) -> None:
    planet, sentry = game.planet, game.sentry
    point = planet.point_from_local(0.0, 0.0, 12.0)
    sentry.position = (point.x, point.y, point.z)
    sentry.local_yaw = 0.0
    planet.orient_entity(sentry, point, sentry.local_yaw)
    sentry.flight.phase = FlightPhase.CRUISE
    sentry.flight.phase_time = 1.0
    sentry.flight.velocity = velocity
    sentry.pose_root.setQuat(LQuaternionf.identQuat())
    sentry._airflow_forward = sentry._airflow_right = 0.0
    sentry._animation_time = 0.0
    # A side-on validation view separates body facing from travel direction.
    # The gameplay camera's default framing and controls are unchanged.
    game.camera.yaw = 90.0
    game.camera.pitch = game.camera.DEFAULT_PITCH
    game.camera.distance = game.camera.DEFAULT_DISTANCE
    game.camera.pivot.position = sentry.position

    for _ in range(30):
        sentry._update_flight_posture(1.0 / 60.0, planet.normal(point),
                                    backward_intent=(move.z < 0.0),
                                    neutral_intent=(move.length() < 1e-5
                                                    and abs(vertical) < 1e-5
                                                    and name == "flight_posture_neutral.png"))
        sentry._update_airflow(1.0 / 60.0, planet.normal(point))
        sentry._deform_cape()
        for lock in sentry.hair_locks:
            lock.rotation_x = max(-12.0, min(12.0,
                                       sentry._airflow_forward * -.025))
        game.camera.update(1.0 / 60.0)
        game.environment.update(0.0)
        game.hud.update()
        base.taskMgr.step()
        base.graphicsEngine.renderFrame()

    image = PNMImage()
    if not base.win.getScreenshot(image):
        raise RuntimeError(f"Could not capture {name}")
    path = OUTPUT / name
    relative_path = Path("Documentation") / name
    if not image.write(relative_path.as_posix()):
        raise RuntimeError(f"Could not save {path}")
    print(path)


def main() -> int:
    app, game = build_game("onscreen")
    window.size = (1280, 720)
    game.paused = True
    planet, sentry = game.planet, game.sentry
    point = planet.point_from_local(0.0, 0.0, 12.0)
    up = planet.normal(point)
    forward = planet.heading(point, 0.0)
    from game.island_frame import cross
    right = cross(up, forward).normalized()

    cases = (
        ("flight_posture_neutral.png", Vec3(), Vec3(), 0.0),
        ("flight_posture_forward.png", forward * 75.0, forward, 0.0),
        ("flight_posture_backward.png", forward * -75.0, forward * -1.0, 0.0),
        ("flight_posture_ascent.png", up * 32.0, Vec3(), 1.0),
        ("flight_posture_descent.png", up * -70.0, Vec3(), -1.0),
        ("flight_posture_lateral.png", right * 50.0, right, 0.0),
    )
    try:
        for name, velocity, move, vertical in cases:
            capture(application.base, game, name, velocity, move, vertical)
    finally:
        app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
