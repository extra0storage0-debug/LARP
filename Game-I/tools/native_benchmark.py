"""Real frames off-screen, with and without the compiled maths: the same game, scripted the same way.

Run with no arguments: it alternates the two modes in separate processes and prints the comparison.
It opens no window and uses throwaway saves.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time as clock

ROOT = Path(__file__).resolve().parent.parent
RUNS = 3
FRAME = 1 / 60


def one_run() -> dict:
    from panda3d.core import loadPrcFileData

    sys.path.insert(0, str(ROOT))
    folder = Path(tempfile.mkdtemp())
    for name, file in (("SENTRY_DESTRUCTION_SAVE", "destruction.json"), ("SENTRY_PROFILE_FILE", "profiles.json"),
                       ("SENTRY_ROSTER_FILE", "roster.json"), ("SENTRY_POWER_FILE", "powers.json")):
        os.environ[name] = str(folder / file)
    loadPrcFileData("", "window-type offscreen\nwin-size 1600 900\naudio-library-name null\nsync-video 0\n")
    from ursina import Entity, Ursina, held_keys
    from ursina.shaders import lit_with_shadows_shader

    app = Ursina(borderless=False, fullscreen=False, development_mode=False)
    import game.art_style  # noqa: F401
    Entity.default_shader, previous = lit_with_shadows_shader, Entity.default_shader
    from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM
    from game.game_manager import GameManager
    from movement.flight_physics import FlightPhase, Vec3 as SimVec3

    started = clock.perf_counter()
    game = GameManager()
    startup = clock.perf_counter() - started
    Entity.default_shader = previous
    teams, combat = game.teams, game.combat

    def setup(enemies=()):
        combat.reset_world_state()
        for cid in teams.characters:
            teams.characters[cid].release_motion()
            teams.state.assignment[cid] = AVAILABLE
        teams.state.assignment["YELLOW"] = MY_TEAM
        teams.swap("YELLOW", save=False)
        for cid in enemies:
            teams.state.assignment[cid] = ENEMY_TEAM
        teams._apply_roster()
        player = game.sentry
        player.position = (0.0, game.world.height_at(0.0, 0.0) + .25, 0.0)
        player.flight.phase = FlightPhase.GROUNDED
        player.flight.velocity = SimVec3()
        player.powers.hard_reset()
        for cid in (*enemies, "YELLOW"):
            body = teams.characters[cid]
            body.vitals.max_health = body.vitals.health = 1e7
        game.camera.yaw, game.camera.pitch = 0.0, 5.0

    def measure(frames, during=None):
        times, updates = [], []
        for index in range(frames):
            if during:
                during(index)
            begin = clock.perf_counter()
            game.update(FRAME)
            middle = clock.perf_counter()
            app.step()
            times.append(clock.perf_counter() - begin)
            updates.append(middle - begin)
        times.sort()
        return {"mean_ms": statistics.fmean(times) * 1000.0, "update_ms": statistics.fmean(updates) * 1000.0,
                "p99_ms": times[int(len(times) * .99)] * 1000.0, "worst_ms": times[-1] * 1000.0}

    results = {"startup_s": startup}
    setup()
    measure(60)
    results["idle"] = measure(240)
    setup(("WHITE", "BLACK"))
    results["ai_fight"] = measure(420)
    setup()
    game.input("f")
    game.camera.pitch = 0.0

    def fly(_index):
        held_keys["w"] = 1

    results["fast_flight"] = measure(300, fly)
    held_keys["w"] = 0
    setup(("WHITE",))

    def explode(index):
        if index % 15 == 0:
            player = game.sentry
            combat.blast(player, SimVec3(float(player.x) + 30.0, float(player.y), float(player.z) + 30.0 + index),
                         40.0, 400.0, 80.0, crater=(8.0, 1.5, "bench"), burst_scale=1.2)

    results["destruction"] = measure(300, explode)
    return results


def compare() -> None:
    env_off = dict(os.environ, SENTRY_NO_NATIVE="1")
    env_on = {key: value for key, value in os.environ.items() if key != "SENTRY_NO_NATIVE"}
    runs = {"python": [], "rust": []}
    for index in range(RUNS * 2):  # alternating, so neither mode gets the cooler or quieter machine
        mode = "python" if index % 2 == 0 else "rust"
        output = subprocess.run([sys.executable, __file__, "--one"], cwd=ROOT, capture_output=True, text=True,
                                env=env_off if mode == "python" else env_on, timeout=900).stdout
        runs[mode].append(json.loads(output[output.rindex("RESULT ") + 7:].splitlines()[0]))
        print(f"run {index + 1}/{RUNS * 2} ({mode}) done", flush=True)
    print(f"{'':14s}{'':10s}{'python':>10s}{'rust':>10s}{'change':>9s}")
    print(f"{'startup':14s}{'seconds':10s}{statistics.median(r['startup_s'] for r in runs['python']):10.2f}"
          f"{statistics.median(r['startup_s'] for r in runs['rust']):10.2f}")
    for scene in ("idle", "ai_fight", "fast_flight", "destruction"):
        for key in ("mean_ms", "update_ms", "p99_ms", "worst_ms"):
            before = statistics.median(r[scene][key] for r in runs["python"])
            after = statistics.median(r[scene][key] for r in runs["rust"])
            print(f"{scene:14s}{key:10s}{before:10.1f}{after:10.1f}{(after / before - 1.0) * 100.0:+8.1f}%")
    (ROOT / "tools" / "native_benchmark_results.json").write_text(json.dumps(runs, indent=1), encoding="utf-8")


if __name__ == "__main__":
    if "--one" in sys.argv:
        print("RESULT " + json.dumps(one_run()), flush=True)
        os._exit(0)
    compare()
