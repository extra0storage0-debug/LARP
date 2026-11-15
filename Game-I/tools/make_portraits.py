"""Render each character's head and shoulders for the switcher, from the real in-game models.

Run from the project folder: .venv\\Scripts\\python.exe tools\\make_portraits.py
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
_saves = Path(tempfile.mkdtemp(prefix="nltl_portraits_"))
os.environ["SENTRY_DESTRUCTION_SAVE"] = str(_saves / "island_destruction.json")
os.environ["SENTRY_PROFILE_FILE"] = str(_saves / "profiles.json")
os.environ["SENTRY_ROSTER_FILE"] = str(_saves / "roster.json")
os.environ["SENTRY_POWER_FILE"] = str(_saves / "powers.json")

import main  # noqa: E402
from panda3d.core import Filename  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageEnhance  # noqa: E402
from movement.flight_physics import FlightPhase  # noqa: E402
from ursina import Vec3, application, camera, color, scene, window  # noqa: E402

OUTPUT = ROOT / "assets" / "portraits"
SIZE = 512


def graded(image: Image.Image) -> Image.Image:
    """High contrast, and the sky behind the head falls away into the dark of the menus."""
    image = ImageEnhance.Contrast(image).enhance(1.18)
    pixels = np.asarray(image, dtype=np.float32)
    y, x = np.mgrid[0:SIZE, 0:SIZE] / (SIZE - 1.0) - .5
    falloff = np.clip(1.25 - ((x / .62) ** 2 + ((y - .08) / .68) ** 2), .12, 1.0)
    return Image.fromarray(np.clip(pixels * falloff[..., None], 0, 255).astype(np.uint8))


def run() -> None:
    app, game = main.build_game("onscreen")
    application.asset_folder = ROOT
    window.size = (1000, 800)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    camera.ui.hide()
    window.color = color.black
    for _ in range(30):
        game.update()
        app.step()
    spot = (0.0, 0.0)
    ground = game.world.height_at(*spot) + .25
    for index, (character_id, character) in enumerate(game.teams.characters.items()):
        for other in game.teams.characters.values():
            if other is not character:
                other.position = (400.0 + index, ground + 200.0, 400.0)
        character.position = (spot[0], ground, spot[1])
        character.setHpr(0, 0, 0)
        character.rotation = (0, 0, 0)
        character.visual.set_detail(True)
        character.pose_root.setHpr(0, 0, 0)
        character.release_motion()
        character.flight.phase = FlightPhase.GROUNDED
        game.teams.swap(character_id, save=False)  # the player's body stands idle, and nobody is fighting it
        for _ in range(40):  # long enough to settle into their idle stance, arms down and eyes open
            game.update(1.0 / 60.0)
            character.position = (spot[0], ground, spot[1])
            app.step()
        game.teams.tags[character_id].root.hide()
        top = character.visual.pose_root.getTightBounds(scene)[1].y  # the top of their head, whatever their height
        for child in scene.getChildren():  # only them, against the dark of the menus
            if child == character or child == camera:
                child.show()
            else:
                child.hide()
        camera.parent = scene
        camera.rotation = (0, 180, 0)
        camera.position = Vec3(spot[0], top - .34, spot[1] + 1.65)
        camera.fov = 40
        for _ in range(8):
            app.step()
        shot = _saves / f"{character_id}.png"
        application.base.win.saveScreenshot(Filename.from_os_specific(str(shot)))
        app.step()
        image = Image.open(shot).convert("RGB")
        width, height = image.size
        side = min(width, height)
        left, top = (width - side) // 2, (height - side) // 2
        graded(image.crop((left, top, left + side, top + side)).resize((SIZE, SIZE), Image.LANCZOS)).save(
            OUTPUT / f"{character_id.lower()}.png")
        print("wrote", character_id, flush=True)
    os._exit(0)


if __name__ == "__main__":
    try:
        run()
    except BaseException:
        import traceback
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        os._exit(2)
