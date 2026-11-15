"""Windowed close-ups of the five characters, from the front and the back."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
_saves = Path(tempfile.mkdtemp(prefix="sentry_lineup_"))
os.environ["SENTRY_DESTRUCTION_SAVE"] = str(_saves / "island_destruction.json")
os.environ["SENTRY_PROFILE_FILE"] = str(_saves / "profiles.json")
os.environ["SENTRY_ROSTER_FILE"] = str(_saves / "roster.json")

import main  # noqa: E402
from panda3d.core import Filename  # noqa: E402
from ursina import Vec3, application, camera  # noqa: E402

OUTPUT = ROOT / "screenshots" / "overhaul"


def run() -> None:
    app, game = main.build_game("onscreen")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    game.camera.update = lambda _dt=None: None
    team = game.teams
    lineup = list(team.characters.values())
    for tag in team.tags.values():
        tag.set_visible(False)
    for entity in (game.hud.status, game.hud.details, game.hud.help):
        entity.enabled = False
    ground = game.world.height_at(0.0, 0.0)

    def place(yaw: float) -> None:
        for index, sentry in enumerate(lineup):
            x = (index - 2) * 2.6
            sentry.position = Vec3(x, ground + .25, 0.0)
            sentry.rotation = (0, yaw, 0)

    def shoot(name: str, position, heading: float) -> None:
        camera.position = Vec3(*position)
        camera.setQuat(game.planet.surface_quaternion(None, heading, 2.0))
        for _ in range(6):
            app.step()
        application.base.win.saveScreenshot(Filename.from_os_specific(str(OUTPUT / f"{name}.png")))

    for _ in range(10):
        app.step()
    place(0.0)
    shoot("lineup_front", (0.0, ground + 2.0, 11.0), 180.0)
    shoot("head_white_green", (-.0, ground + 2.6, 3.4), 180.0)
    shoot("head_black_red", (4.0, ground + 2.6, 3.4), 180.0)
    place(0.0)
    shoot("lineup_back", (0.0, ground + 2.0, -11.0), 0.0)
    print("saved", OUTPUT, flush=True)
    os._exit(0)


if __name__ == "__main__":
    try:
        run()
    except BaseException:
        import traceback
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        os._exit(2)
