"""One shared headless game: Ursina allows one application per process."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

from config.sentry_profiles import ENEMY
from movement.flight_physics import FlightPhase, Vec3 as SimVec3

FRAME = 1.0 / 60.0
_game = None
_folder = None


def shared_game():
    """Build the game once; nothing it does may touch the player's real saves."""
    global _game, _folder
    if _game is None:
        _folder = Path(tempfile.mkdtemp(prefix="sentry_tests_"))
        os.environ["SENTRY_DESTRUCTION_SAVE"] = str(_folder / "destruction.json")
        os.environ["SENTRY_PROFILE_FILE"] = str(_folder / "profiles.json")
        os.environ["SENTRY_ROSTER_FILE"] = str(_folder / "roster.json")
        os.environ["SENTRY_POWER_FILE"] = str(_folder / "powers.json")
        from main import build_game
        from ursina import application
        import game.game_manager as manager
        manager.save_settings = lambda _settings: None
        _app, _game = build_game("none")
        application.time_scale = 1
        _game.sentry_config.config_path = _folder / "sentry_settings.json"
    return _game


def reset_game(*, ai_powers: bool = False):
    """Back to the default roster and settings, on the ground at the island's centre."""
    game = shared_game()
    teams = game.teams
    game.sentry_config.reset()
    game.profiles._values = {name: {} for name in game.profiles._values}
    # Movement and menu tests run undisturbed; the AI combat tests switch this back on.
    game.profiles.set(ENEMY, "ai_uses_powers", 1 if ai_powers else 0, notify=False)
    world = game.world
    world.terrain_impacts.clear()
    world._terrain_impacts_by_chunk.clear()
    world._sync_native_craters()
    if any(getattr(item, "health", None) is not None and item.health.broken
           or not hasattr(item, "health") for item in game.landmarks.items):
        game.landmarks.restore_all()
    teams.state.assignment["YELLOW"] = "my_team"
    teams.swap("YELLOW", save=False)
    teams.state.reset_all()
    teams._apply_roster()
    game.combat.settings.reset_all()
    game.combat.targets.enabled = True
    game.combat.reset_world_state()
    game.apply_sentry_config()
    for character in teams.characters.values():
        character.powers.hard_reset()
        character.release_motion()
        character.knock = SimVec3()
        character._ai_move = None
        character._ai_next_attack = 0.0
    teams.attack_tokens.holders.clear()
    game.camera_impulse = 0.0
    ground = game.world.height_at(0.0, 0.0) + .25
    for index, character in enumerate(teams.characters.values()):
        character.position = (index * 30.0, ground, 40.0) if character is not game.sentry \
            else (0.0, ground, 0.0)
        character.flight.phase = FlightPhase.GROUNDED
        character.flight.velocity = SimVec3()
        character.ground.velocity = SimVec3()
        character.jump_height = character.jump_velocity = 0.0
        character.intent = None
    game.paused = False
    game.hud.set_paused(False)
    if game.team_panel.visible:
        game.team_panel.close()
        game._close_menu()
    if game.power_panel.visible:
        game.power_panel.pending.clear()
        game.power_panel.close()
        game._close_menu()
    if game.settings_page.enabled:
        game.settings_page.close()
    return game


def run_frames(game, count: int) -> None:
    for _ in range(count):
        game.update(FRAME)
