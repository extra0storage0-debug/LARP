"""Capture a real windowed Sentry gameplay frame for visual review."""

from __future__ import annotations

import argparse
from pathlib import Path
import time as clock
import sys

from direct.task import Task
from panda3d.core import Filename, PNMImage
from ursina import mouse
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from movement.flight_physics import FlightPhase
from main import build_game, update as _game_update

# Ursina calls __main__.update while the capture window is running.
update = _game_update


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coast", action="store_true",
                        help="capture the coastal road, beach and surrounding water")
    parser.add_argument("--sunset", action="store_true",
                        help="capture at the warm sunset phase")
    parser.add_argument("--settings", action="store_true",
                        help="capture the in-game configuration panel")
    parser.add_argument("--camera-view", choices=("normal", "above", "below", "full-orbit"),
                        default="normal", help="select a camera pose for orientation review")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    output_dir = project_root / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_name = ("settings" if args.settings else
                  "coastline" if args.coast and args.camera_view == "normal" else
                  f"camera_{args.camera_view}")
    time_name = "sunset" if args.sunset else "day"
    output_path = output_dir / f"sentry_{scene_name}_{time_name}.png"
    app, game = build_game("onscreen")
    # This capture uses the normal spawn view without external desktop mouse
    # movement changing the live camera before the first frame is saved.
    mouse.locked = False
    mouse.visible = False
    if args.settings:
        game.config_panel.open()
    if args.camera_view == "above":
        game.sentry_config.set("camera_distance", 20.0)
        game.camera.apply_settings()
        game.camera.pitch = game.camera.target_pitch = 90.0
    elif args.camera_view == "below":
        game.sentry_config.set("camera_distance", 20.0)
        game.camera.apply_settings()
        # Put Sentry in a low hover so this genuinely-underneath view remains
        # above the street surface and includes nearby city geometry.
        x, z = game.world.SPAWN_POSITION
        game.sentry.position = (x, game.world.height_at(x, z) + 40.0, z)
        game.sentry.flight.phase = FlightPhase.CRUISE
        game.camera.pivot.position = game.sentry.position
        game.camera.pitch = game.camera.target_pitch = 270.0
    elif args.camera_view == "full-orbit":
        game.camera.yaw = game.camera.target_yaw = game.camera.yaw + 360.0
    if args.camera_view != "normal":
        game.camera.update(1/60)
        heading, elevation = game.camera.orbit_angles(game.camera.yaw, game.camera.pitch)
        print(f"Camera capture pose={args.camera_view}, yaw={game.camera.yaw:.1f}, "
              f"pitch={game.camera.pitch:.1f}, orbit_heading={heading:.1f}, "
              f"elevation={elevation:.1f}, roll={camera.getR():.3f}", flush=True)
    if args.coast:
        x, z = 0.0, 2130.0
        game.sentry.position = (x, game.world.height_at(x, z) + .25, z)
        game.sentry.flight.phase = FlightPhase.CRUISE
        game.sentry.y += 15.0
        game.camera.pivot.position = game.sentry.position
        game.camera.yaw = 0.0
        game.camera.pitch = game.camera.DEFAULT_PITCH
        game.camera.distance = game.camera.DEFAULT_DISTANCE
    if args.sunset:
        game.world.elapsed = 120.0
        game.world._update_atmosphere()
    start = clock.perf_counter()

    def capture_when_ready(task):
        if clock.perf_counter() - start < 2.0:
            return Task.cont
        # Render after Ursina has stepped the camera, UI, ocean and lighting.
        app.graphicsEngine.renderFrame()
        image = PNMImage()
        captured = app.win.getScreenshot(image)
        filename = Filename.fromOsSpecific(str(output_path))
        saved = image.write(filename) if captured else False
        if not captured or not saved:
            print(f"screenshot diagnostics: window={app.win} size={app.win.getXSize()}x{app.win.getYSize()} captured={captured} image={image.getXSize()}x{image.getYSize()} written={saved}", flush=True)
            raise RuntimeError(f"Panda3D failed to save screenshot: {output_path}")
        print(f"Gameplay screenshot: {output_path}", flush=True)
        app.userExit()
        return Task.done

    app.taskMgr.add(capture_when_ready, "capture-sentry-gameplay")
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
