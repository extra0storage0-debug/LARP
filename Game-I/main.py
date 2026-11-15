"""Launch NO LIMIT TO LARP."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

_active_game = None


def update():
    if _active_game is not None:
        _active_game.update()


def input(key):
    if _active_game is not None:
        _active_game.input(key)


def build_game(window_type: str = "onscreen"):
    global _active_game
    from config import load_settings, resolution_of
    from config.branding import GAME_TITLE

    settings = load_settings()
    # Culling and drawing each get a thread of their own: this is a one-thread game otherwise, on a ten-core CPU.
    threading_model = os.environ.get("SENTRY_THREADING", "Cull/Draw")
    if window_type == "onscreen" and threading_model:
        from panda3d.core import loadPrcFileData
        loadPrcFileData("", f"threading-model {threading_model}")
    try:
        from ursina import Entity, Ursina, camera, color, mouse, window
    except ImportError as error:
        raise RuntimeError("Ursina is not installed. Run: python -m pip install -r requirements.txt") from error

    application = Ursina(title=GAME_TITLE,
                         icon=str(Path(__file__).resolve().parent / "assets" / "branding" / "icon.ico"),
                         size=resolution_of(settings),
                         borderless=False, fullscreen=False,
                         # Vsync hides real frame cost, so benchmarks can switch it off.
                         vsync=os.environ.get("SENTRY_VSYNC") != "0",
                         development_mode=False, show_ursina_splash=False,
                         window_type=window_type)
    if window_type == "none" and not hasattr(camera, "_clip_plane_far"):
        camera._clip_plane_far = 1000
    import game.art_style  # noqa: F401  (must style the lit shader before it compiles)
    from ursina.shaders import lit_with_shadows_shader
    from ui import loading_screen
    if window_type == "onscreen":  # after the shader is styled, and before anything takes long
        loading_screen.begin()
    previous_default_shader = Entity.default_shader
    Entity.default_shader = lit_with_shadows_shader
    window.color = color.rgb32(0, 0, 0)

    from game.game_manager import GameManager
    try:
        game = GameManager()
    finally:
        # Keep HUD/camera UI entities on Ursina's screen-space default shader.
        Entity.default_shader = previous_default_shader
    _active_game = game
    loading_screen.end()
    if window_type == "onscreen":
        game.world.async_chunks = True
        sys.setswitchinterval(.002)  # a worker thread must never hold the game up for long
        mouse.locked = True
        mouse.visible = False

    return application, game


def run_smoke_test(app, game) -> None:
    """A quick end-to-end pass: the scene, movement, every character and a few powers."""
    from game.island_frame import IslandFrame
    from movement.flight_physics import FlightPhase, Vec3 as SimVec3

    def step(frames: int) -> None:
        for _ in range(frames):
            game.update(1.0 / 60.0)
            app.taskMgr.step()

    step(5)
    if not isinstance(game.planet, IslandFrame):
        raise RuntimeError("Island coordinate frame failed to initialize")
    if len(game.world.static_art) != 2 or game.world.ground is None or game.world.water is None:
        raise RuntimeError("Island terrain or surrounding ocean failed to initialize")
    if len(game.world.chunks) != 9:
        raise RuntimeError("The starting island district chunks did not stream")
    if not any(chunk.tree_colliders for chunk in game.world.chunks.values()):
        raise RuntimeError("Natural tree colliders did not initialize")
    if len(game.teams.characters) != 5:
        raise RuntimeError("The five characters failed to initialize")
    if not game.world.buildings or not game.landmarks.items:
        raise RuntimeError("Destructible landmarks failed to initialize")
    teams = game.teams
    before = (game.sentry.x, game.sentry.z)
    game.sentry.simulate(1.0 / 60.0, SimVec3(0.0, 0.0, 1.0), 0.0, ground_distance=0.0)
    if (game.sentry.x, game.sentry.z) == before:
        raise RuntimeError("Ground movement did not move the character")
    for character_id in teams.characters:
        teams.swap(character_id, save=False)
        if game.sentry.kit.character_id != character_id or not game.sentry.controlled:
            raise RuntimeError(f"Could not take control of {character_id}")
        for key in ("1", "1 up", "2", "2 up", "3", "3 up", "4", "4 up", "r", "r up", "e", "e up",
                    "left mouse down", "left mouse up", "right mouse down", "right mouse up"):
            game.input(key)
            step(1)
        game.sentry.powers.cancel_all()
        game.sentry.release_motion()
    quality = game.settings.quality
    game.input("1")
    game.input("2")
    if game.settings.quality != quality:
        raise RuntimeError("An ability key changed graphics quality")
    red = teams.characters["RED"]
    teams.swap("RED", save=False)
    game.input("f")
    step(2)
    if red.flight.phase is not FlightPhase.GROUNDED:
        raise RuntimeError("Soldier Boy left the ground")
    teams.swap("YELLOW", save=False)
    game.input("f")
    if not game.sentry.flight.is_flying:
        raise RuntimeError("F did not take off")
    game.input("f")
    craters = len(game.world.terrain_impacts)
    x, z = 900.0, 900.0
    game.combat.blast(None, SimVec3(x, game.world.height_at(x, z), z), 12.0, 200.0, 20.0,
                      crater=(6.0, 1.0, "smoke"))
    if len(game.world.terrain_impacts) <= craters:
        raise RuntimeError("A blast did not deform the terrain")
    step(5)
    print("Smoke test passed: island, landmarks, five characters, abilities, swapping, "
          "flight rules, quality keys and terrain damage")


def main() -> int:
    parser = argparse.ArgumentParser(description="NO LIMIT TO LARP: a physics-driven character combat sandbox")
    parser.add_argument("--smoke-test", action="store_true",
                        help="initialize the 3D scene headlessly and run a few simulation frames")
    args = parser.parse_args()
    if args.smoke_test:
        saves = Path(tempfile.mkdtemp(prefix="nltl_smoke_save_"))
        os.environ["SENTRY_DESTRUCTION_SAVE"] = str(saves / "island_destruction.json")
        os.environ["SENTRY_PROFILE_FILE"] = str(saves / "profiles.json")
        os.environ["SENTRY_ROSTER_FILE"] = str(saves / "roster.json")
        os.environ["SENTRY_POWER_FILE"] = str(saves / "powers.json")
    try:
        app, game = build_game("none" if args.smoke_test else "onscreen")
    except Exception as error:
        print(f"Game startup failed: {error}", file=sys.stderr)
        return 1

    if args.smoke_test:
        run_smoke_test(app, game)
        from ursina import application
        application.base.userExit()
        return 0

    game.show_title()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
