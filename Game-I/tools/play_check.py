"""Play the game in a real window, on the threaded renderer: every character, every key, menus, saves. Temporary saves only.

    python tools/play_check.py [--quality medium] [--out folder] [--soak seconds]

Keys go through the handler real key presses go to. Any exception, in the game or in a Panda task, fails the run.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.dont_write_bytecode = True
_saves = Path(tempfile.mkdtemp(prefix="sentry_play_"))
os.environ["SENTRY_DESTRUCTION_SAVE"] = str(_saves / "island_destruction.json")
os.environ["SENTRY_PROFILE_FILE"] = str(_saves / "profiles.json")
os.environ["SENTRY_ROSTER_FILE"] = str(_saves / "roster.json")
os.environ["SENTRY_POWER_FILE"] = str(_saves / "powers.json")
if "--real-saves" in sys.argv:  # copies of them: what a player's game really starts from
    import shutil
    shutil.copy(ROOT / "config" / "character_roster.json", _saves / "roster.json")
    shutil.copy(ROOT / "config" / "character_powers.json", _saves / "powers.json")
    shutil.copy(ROOT / "config" / "sentry_profiles.json", _saves / "profiles.json")

CHARACTERS = {"YELLOW": "SENTRY", "WHITE": "SUPERMAN", "BLACK": "HOMELANDER", "GREEN": "OMNI-MAN", "RED": "SOLDIER BOY"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quality", default="medium")
    parser.add_argument("--out", default=str(_saves / "shots"))
    parser.add_argument("--soak", type=float, default=0.0)
    parser.add_argument("--only", default="")
    parser.add_argument("--real-saves", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    import faulthandler
    watchdog = open(out / "watchdog.txt", "w", encoding="utf-8")
    faulthandler.dump_traceback_later(45, repeat=True, file=watchdog)  # a stall in here says where it is

    import config as config_module
    preset = config_module.QUALITY_PRESETS[args.quality]
    config_module.load_settings = lambda: preset
    import game.game_manager as manager
    manager.load_settings = lambda: preset
    manager.save_settings = lambda _settings: None
    import main as game_main
    from config.character_roster import ENEMY_TEAM, MY_TEAM
    from movement.flight_physics import FlightPhase
    from panda3d.core import Filename, LVector3f, Point3
    from powers.void import is_black, is_ground_shadow
    from ursina import application, held_keys, mouse, scene

    app, game = game_main.build_game("onscreen")
    game.sentry_config.config_path = _saves / "sentry_settings.json"
    teams, combat, world = game.teams, game.combat, game.world
    results, frame_ms = [], []
    last = [time.perf_counter()]

    def tick() -> None:
        mouse.locked = False
        game.update()
        app.step()
        now = time.perf_counter()
        frame_ms.append((now - last[0]) * 1000.0)
        last[0] = now

    def run(seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            tick()

    def shot(name: str) -> None:
        for _ in range(3):
            tick()
        application.base.win.saveScreenshot(Filename.fromOsSpecific(str(out / f"{name}.png")))

    def check(name: str, passed, detail: str = "") -> None:
        results.append({"name": name, "passed": bool(passed), "detail": str(detail)})
        print(("PASS " if passed else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)

    def tap(key: str, wait: float = .05) -> None:
        game.input(key)
        run(wait)
        game.input(f"{key} up")

    def healthy() -> None:
        for body in teams.characters.values():
            body.vitals.health = body.vitals.max_health
            body.vitals.downed_for = 0.0

    def stand(body, x, z, up=0.0):
        body.motion = None if body.motion is None else body.motion
        body.position = (x, world.height_at(x, z) + .25 + up, z)

    calm = [False]

    def fight(character_id: str, enemy_id: str, distance: float = 30.0) -> None:
        teams.state.auto_target_lock = False  # a save may have it on; every scenario that wants it turns it on itself
        for other, name in CHARACTERS.items():
            teams.state.assignment[other] = MY_TEAM if other == character_id else (ENEMY_TEAM if other == enemy_id else "available")
        teams._apply_roster()
        teams.swap(character_id, save=False)
        player, enemy = teams.characters[character_id], teams.characters[enemy_id]
        player.powers.hard_reset()
        enemy.powers.hard_reset()
        player.release_motion()
        enemy.release_motion()
        player.flight.phase = FlightPhase.GROUNDED
        stand(player, 300.0, 300.0)
        stand(enemy, 300.0, 300.0 + distance)
        game.camera.yaw = 0.0
        healthy()
        if calm[0]:  # a live enemy would quite rightly throw the player about in the middle of a measurement
            enemy.vitals.add_status("frozen", 600.0)
        combat.targets.manual = None
        combat.targets.clear()
        run(.3)

    def finish_sequences(limit: float = 30.0) -> float:
        begun = time.perf_counter()
        while teams.player.motion is not None and time.perf_counter() - begun < limit:
            tick()
        return time.perf_counter() - begun

    failures = []
    scenario_worst = {}
    def guarded(name, function):
        if args.only and name not in args.only.split(","):
            return
        begin = len(frame_ms)
        try:
            function()
            scenario_worst[name] = round(max(frame_ms[begin + 1:], default=0.0), 1)
        except Exception:  # noqa: BLE001
            failures.append(name)
            check(f"{name}: no exception", False, traceback.format_exc()[-1200:])

    def scenario_basics():
        check("threaded renderer active", application.base.graphicsEngine.getThreadingModel().getModel() != "", application.base.graphicsEngine.getThreadingModel().getModel())
        check("five characters", len(teams.characters) == 5)
        check("skinned bodies in use", all(body.uses_skinned_body for body in teams.characters.values()))
        fight("WHITE", "RED")
        shot("01_game_start_superman")
        before = float(teams.player.z)
        held_keys["w"] = 1
        run(1.0)
        held_keys["w"] = 0
        check("W moves the character", abs(float(teams.player.z) - before) > 1.0, f"{abs(float(teams.player.z) - before):.1f} m")

    def scenario_flight():
        calm[0] = True
        fight("WHITE", "RED", 400.0)
        tap("f", .3)
        check("F takes off", teams.player.flight.is_flying)
        held_keys["w"] = held_keys["shift"] = 1
        game.camera.pitch = -15.0
        run(2.0)
        held_keys["w"] = held_keys["shift"] = 0
        check("flight follows aim and climbs", float(teams.player.y) > world.height_at(float(teams.player.x), float(teams.player.z)) + 5.0, f"{float(teams.player.y):.0f}")
        shot("02_flight")
        tap("f", .1)
        finish_sequences(8.0)
        check("F in the air dives and lands", not teams.player.flight.is_flying)
        game.camera.pitch = game.camera.DEFAULT_PITCH

    def scenario_soldier():
        calm[0] = False
        fight("RED", "WHITE", 400.0)
        game.input("f")
        peak, end = 0.0, time.perf_counter() + 1.0
        while time.perf_counter() < end:
            tick()
            peak = max(peak, float(teams.player.y) - world.height_at(float(teams.player.x), float(teams.player.z)))
        game.input("f up")
        check("Soldier Boy F jumps without flying", peak > 3.0 and not teams.player.flight.is_flying, f"{peak:.1f} m")
        tap("f", .1)
        finish_sequences(8.0)
        fastest = max(body.flight.config.boost_speed for body in teams.characters.values() if body.kit.can_fly)
        check("Soldier Boy runs faster than any flyer boosts", teams.player.ground.max_running_speed > fastest, f"{teams.player.ground.max_running_speed:.0f} > {fastest:.0f}")
        held_keys["w"] = held_keys["shift"] = 1
        run(1.0)
        held_keys["w"] = held_keys["shift"] = 0
        shot("03_soldier_boy_run")

    def scenario_abilities(character_id: str, enemy_id: str):
        name = CHARACTERS[character_id].lower().replace(" ", "_").replace("-", "_")
        for key in ("1", "2", "3", "4"):
            fight(character_id, enemy_id, 40.0)
            player, enemy = teams.player, teams.characters[enemy_id]
            enemy.vitals.health = enemy.vitals.max_health = 1e6
            ability = player.powers.slot(key) if hasattr(player.powers, "slot") else None
            tap(key, .5)
            shot(f"{name}_{key}")
            run(.8)
            if player.motion is not None:
                took = finish_sequences(40.0)
                check(f"{name} key {key}: sequence ends", player.motion is None, f"{took:.1f} s")
            elif key == "1":
                tap(key, .1)  # a toggle goes off again
            run(1.2)
            check(f"{name} key {key}: time is running again", not combat.time_stopped, f"{combat.time_stopped} motion {player.motion}")
            player.powers.cancel_all()
            player.release_motion()
            enemy.vitals.max_health = 1000.0
            enemy.vitals.health = 1000.0
        for key in ("=", "-"):
            if character_id != "RED":
                fight(character_id, enemy_id, 3.0)
                tap(key, .5)
                finish_sequences(4.0)
        check(f"{name}: played through", True)

    def scenario_void():
        fight("YELLOW", "WHITE", 40.0)
        tap("q", .1)  # a lock reaches further than a save's Void range may
        tap("1", .3)
        void = teams.player.powers.abilities["void_form"]
        check("Void: on, with a subject", void.active and void.subject is teams.characters["WHITE"])
        check("Void: Sentry is black", is_black(teams.player))
        check("Void: enemy is only a ground shadow", is_ground_shadow(teams.characters["WHITE"]))
        check("Void: enemy cannot move", teams.characters["WHITE"].vitals.has("restrained"))
        shot("void_1_shadow_phase")
        void.cycle = 9.9
        run(.4)
        check("Void: after 10 s Sentry is golden again", not is_black(teams.player))
        check("Void: the enemy is back, and black", is_black(teams.characters["WHITE"]) and not is_ground_shadow(teams.characters["WHITE"]))
        before = teams.characters["WHITE"].vitals.damage_taken
        run(2.0)
        check("Void: continuous damage", teams.characters["WHITE"].vitals.damage_taken > before)
        shot("void_2_corruption_phase")
        tap("1", .2)
        check("Void: off restores everyone", not is_black(teams.player) and not is_black(teams.characters["WHITE"]) and not is_ground_shadow(teams.characters["WHITE"]),
              f"active {void.active} sentry {is_black(teams.player)} enemy {is_black(teams.characters['WHITE'])} shadow {is_ground_shadow(teams.characters['WHITE'])} motion {teams.player.motion} sequence {combat.sequence_running}")

    def scenario_squad():
        fight("GREEN", "WHITE", 60.0)
        tap("1", 1.0)
        names = [member.palette.name for member in teams.summons]
        check("Squad: five Viltrumites and Mark", sum(n.startswith("VILTRUMITE") for n in names) == 5 and names.count("INVINCIBLE") == 1, names)
        mark = next(member for member in teams.summons if member.palette.name == "INVINCIBLE")
        check("Squad: Mark has 5% of Omni-Man's maximum health", abs(mark.vitals.max_health - teams.player.vitals.max_health * .05) < 1.0, f"{mark.vitals.max_health:.0f}")
        check("Squad: Mark alone guards", [member.palette.name for member in teams.summons if member.guards_leader] == ["INVINCIBLE"])
        run(3.0)
        shot("squad_fighting")
        tap("1", .2)
        check("Squad: dismissed", not teams.summons)

    def scenario_lock_and_time():
        fight("WHITE", "RED", 60.0)
        tap("q", .2)
        check("Q locks the enemy", combat.targets.manual is teams.characters["RED"])
        shot("lock_on")
        tap("q", .1)
        check("Q again releases", combat.targets.manual is None)
        game.toggle_auto_target_lock()
        run(.2)
        check("Auto Target Lock locks", combat.targets.manual is teams.characters["RED"])
        game.toggle_auto_target_lock()
        combat.targets.manual = None
        where = float(teams.characters["RED"].x), float(teams.characters["RED"].z)
        tap("t", .2)
        check("T stops time", combat.time_stopped)
        run(1.0)
        check("Time stop freezes the enemy", (float(teams.characters["RED"].x), float(teams.characters["RED"].z)) == where)
        shot("time_stop")
        combat.end_world_stop()
        run(.3)

    def scenario_menus():
        fight("WHITE", "RED", 200.0)
        for key, label in (("p", "powers"), ("m", "team"), ("tab", "status")):
            tap(key, .2)
            shot(f"menu_{label}")
            if key == "tab":
                game.input("tab up")
            else:
                tap(key, .1)
        game.input("escape")
        run(.1)
        menu = game.hud.pause_menu
        shot("menu_pause")
        menu.show_graphics()
        shot("menu_graphics")
        for quality in ("low", "ultra", "high", args.quality):
            menu.choose_quality(quality)
            run(.5)
        check("quality presets switch without error", game.settings.quality == args.quality)
        menu.choose_resolution("1280x720")
        run(.3)
        menu.choose_resolution("1600x900")
        run(.3)
        menu.show_main()
        game.input("escape")
        run(.2)
        check("pause menu closes", not game.paused)

    def scenario_destruction():
        fight("RED", "WHITE", 150.0)
        from movement.flight_physics import Vec3 as SimVec3
        craters = len(world.terrain_impacts)
        x, z = float(teams.player.x) + 40.0, float(teams.player.z) + 40.0
        combat.blast(None, SimVec3(x, world.height_at(x, z), z), 80.0, 500.0, 30.0, crater=(10.0, 1.5, "smoke"))
        run(1.0)
        shot("destruction_blast")
        check("a blast leaves a crater", len(world.terrain_impacts) > craters)

    def scenario_movement():
        calm[0] = True
        fight("WHITE", "RED", 500.0)
        player = teams.player
        visual = player.visual
        def lowest():
            return min(visual._controls[name].getPos(visual.pose_root).y for name in ("foot_l", "foot_r"))
        rest = lowest()
        player.ground.walk_speed = 7.0
        player.ground.max_running_speed = 7.0
        held_keys["w"] = 1
        run(.8)
        worst = 0.0
        end = time.perf_counter() + 2.0
        while time.perf_counter() < end:
            tick()
            worst = max(worst, abs(lowest() - rest))
        check("walking: a foot stays on the ground", worst < .12, f"{worst:.3f} off")
        game.camera.yaw = 90.0
        for index in range(4):
            run(.11)
            shot(f"gait_walk_{index}")
        held_keys["w"] = 0
        fight("WHITE", "RED", 500.0)
        player = teams.player
        held_keys["w"] = held_keys["shift"] = 1
        player.ground.max_running_speed = 26.0
        player.ground.sprint_multiplier = 26.0 / max(1.0, player.ground.walk_speed)
        run(1.0)
        game.camera.yaw = 90.0
        for index in range(4):
            run(.09)
            shot(f"gait_run_{index}")
        held_keys["w"] = held_keys["shift"] = 0
        speed_when_released = player.ground.velocity.length()
        run(.1)
        check("running: momentum carries on after letting go", player.ground.velocity.length() > 0.0, f"{speed_when_released:.1f} m/s")
        fight("WHITE", "RED", 500.0)
        player = teams.player
        peaks = []
        for release in (.06, None):
            game.input("space")
            peak, begin = 0.0, time.perf_counter()
            released = False
            while time.perf_counter() - begin < 2.6:
                tick()
                peak = max(peak, player.jump_height)
                if release is not None and not released and time.perf_counter() - begin > release:
                    game.input("space up")
                    released = True
            peaks.append(peak)
            game.input("space up")
            run(.3)
        check("jumping: a tap is lower than a press", peaks[0] < peaks[1], f"{peaks[0]:.1f} vs {peaks[1]:.1f}")
        check("jumping: comes back to the ground", player.jump_height == 0.0)
        fight("WHITE", "RED", 500.0)
        player = teams.player
        tap("f", .1)
        check("take-off: the legs gathered", player.visual._squat > .02 or player.flight.is_flying, f"{player.flight.phase} jump {player.jump_height:.2f} motion {player.motion} moved {player is teams.player} immobile {player.vitals.immobile} statuses {list(player.vitals.statuses)}")
        game.camera.pitch = -25.0
        held_keys["w"] = 1
        begin = float(player.flight.speed_mps)
        run(.4)
        early = player.flight.speed_mps
        run(1.5)
        late = player.flight.speed_mps
        check("flight: accelerates rather than jumping to speed", begin <= early <= late + 1.0 and late > 0.0, f"{begin:.0f}, {early:.0f}, {late:.0f}")
        held_keys["w"] = 0
        run(1.2)
        check("flight: air slows it when thrust stops", player.flight.speed_mps < late, f"{late:.0f} to {player.flight.speed_mps:.0f}")
        game.camera.pitch = game.camera.DEFAULT_PITCH
        tap("f", .1)
        finish_sequences(8.0)
        run(1.0)
        check("landing: back on the ground", not player.flight.is_flying and player.jump_height == 0.0)
        fight("RED", "WHITE", 8.0)
        enemy = teams.characters["WHITE"]
        enemy.flight.phase = FlightPhase.GROUNDED
        from movement.flight_physics import Vec3 as SimVec3
        from powers.common import LaunchedMotion
        enemy.vitals.max_health = enemy.vitals.health = 1e7
        enemy.release_motion()
        motion = LaunchedMotion(teams.player, enemy, SimVec3(30.0, 30.0, 0.0))
        enemy.motion = motion
        below, jump, previous = 0.0, 0.0, float(enemy.x)
        begun = time.perf_counter()
        while enemy.motion is motion and time.perf_counter() - begun < 12.0:
            tick()
            below = min(below, float(enemy.y) - world.height_at(float(enemy.x), float(enemy.z)))
            jump = max(jump, abs(float(enemy.x) - previous))
            previous = float(enemy.x)
        shot("launch_recovery")
        check("launched: never below the ground", below > -.3, f"{below:.2f}")
        check("launched: settles and recovers", enemy.motion is not motion, f"largest step {jump:.2f} m")
        enemy.vitals.max_health = enemy.vitals.health = 1000.0
        player_body = teams.player
        x, z = float(player_body.x) + 25.0, float(player_body.z)
        combat.blast(None, SimVec3(x, world.height_at(x, z), z), 30.0, 50.0, 80.0)
        run(.25)
        pieces = list(world.debris)
        run(2.0)
        below_ground = sum(float(p.y) < world.height_at(float(p.x), float(p.z)) - .3 for p in world.debris)
        check("explosion: no debris below the ground", below_ground == 0, f"{len(pieces)} pieces")

    def view(name: str, side: float, back: float, up: float = 0.0) -> None:
        """A picture from anywhere around the player, for one frame, without touching what the game's camera follows."""
        from ursina import camera, Vec3
        body = teams.player
        centre = Vec3(float(body.x), float(body.y) + 1.5 + up, float(body.z))
        ahead = body.forward
        length = max((ahead[0] ** 2 + ahead[2] ** 2) ** .5, 1e-3)
        fx, fz = ahead[0] / length, ahead[2] / length
        camera.world_position = Vec3(centre[0] + fz * side - fx * back, centre[1], centre[2] - fx * side - fz * back)
        camera.lookAt(scene, Point3(*centre), LVector3f(0.0, 1.0, 0.0))
        app.step()
        application.base.win.saveScreenshot(Filename.fromOsSpecific(str(out / f"{name}.png")))
        app.step()

    def scenario_cape():
        from characters.skinned_visual import CAPE_LENGTH
        calm[0] = True
        for character, enemy in (("BLACK", "RED"), ("WHITE", "RED"), ("YELLOW", "RED"), ("GREEN", "RED"), ("RED", "WHITE")):
            name = CHARACTERS[character].lower().replace(" ", "_").replace("-", "_")
            fight(character, enemy, 900.0)
            run(1.0)
            view(f"cape_{name}_stand_back", 0.0, 6.0)
            view(f"cape_{name}_stand_side", 6.0, 0.0)
            view(f"cape_{name}_stand_front", 0.0, -6.0)
            body = teams.player
            body.ground.max_running_speed = 9.0
            body.ground.sprint_multiplier = 9.0 / max(1.0, body.ground.walk_speed)
            held_keys["w"] = held_keys["shift"] = 1
            run(1.0)
            view(f"cape_{name}_walk_side", 6.0, 0.0)
            body.ground.max_running_speed = 26.0
            body.ground.sprint_multiplier = 26.0 / max(1.0, body.ground.walk_speed)
            run(1.0)
            view(f"cape_{name}_run_side", 6.0, 0.0)
            view(f"cape_{name}_run_back", 0.0, 7.0)
            held_keys["w"] = held_keys["shift"] = 0
            run(.4)
            chain = body.visual._chain
            reach = max(sum(v * v for v in chain.point(i)) ** .5 for i in range(6))
            check(f"{name}: cape chain holds together", reach < CAPE_LENGTH * 1.25 and all(v == v for i in range(6) for v in chain.point(i)), f"{reach:.2f} of {CAPE_LENGTH}")
            if character != "RED":
                tap("f", .2)
                game.camera.pitch = -10.0
                held_keys["w"] = 1
                run(.5)
                view(f"cape_{name}_fly_side", 7.0, 0.0)
                held_keys["shift"] = 1
                run(1.2)
                view(f"cape_{name}_boost_side", 8.0, 0.0)
                view(f"cape_{name}_boost_above", 3.0, 3.0, 5.0)
                held_keys["w"] = held_keys["shift"] = 0
                run(1.5)
                view(f"cape_{name}_hover_side", 6.0, 0.0)
                tap("f", .25)
                view(f"cape_{name}_dive_side", 8.0, 0.0)
                finish_sequences(8.0)
                view(f"cape_{name}_landed_side", 7.0, 0.0)
                run(.6)
                game.camera.pitch = game.camera.DEFAULT_PITCH
                check(f"{name}: flew, dived and landed", not body.flight.is_flying)
        calm[0] = False

    def scenario_poses():
        calm[0] = True
        flyers = (("WHITE", "RED"), ("BLACK", "RED"), ("YELLOW", "RED"), ("GREEN", "RED"))
        def feet_apart(body):
            visual = body.visual
            a = visual._controls["foot_l"].getPos(visual.pose_root)
            b = visual._controls["foot_r"].getPos(visual.pose_root)
            return (a - b).length()
        for character, enemy in flyers:
            name = CHARACTERS[character].lower().replace(" ", "_").replace("-", "_")
            fight(character, enemy, 1500.0)
            body = teams.player
            view(f"pose_{name}_stand_side", 7.0, 0.0)
            tap("f", .8)
            held_keys["w"] = held_keys["s"] = held_keys["a"] = held_keys["d"] = 0
            run(1.4)
            check(f"{name}: hover is hands on hips", body.flight_pose == "hands_on_hips", body.flight_pose)
            check(f"{name}: hover is upright", abs(body.pose_root.getP()) < 8.0, f"{body.pose_root.getP():.1f}")
            check(f"{name}: hovering, the feet are together", feet_apart(body) < .34, f"{feet_apart(body):.2f}")
            view(f"pose_{name}_hover_front", 0.0, -7.0)
            view(f"pose_{name}_hover_side", 7.0, 0.0)
            view(f"pose_{name}_hover_back", 0.0, 7.0)
            game.camera.pitch = -2.0
            held_keys["w"] = 1
            run(1.2)
            check(f"{name}: W: reaching forward", body.flight_pose == "reaching", body.flight_pose)
            check(f"{name}: forward, the feet are together", feet_apart(body) < .34, f"{feet_apart(body):.2f}")
            view(f"pose_{name}_forward_side", 8.0, 0.0)
            view(f"pose_{name}_forward_back", 0.0, 8.0)
            held_keys["w"] = 0
            run(.9)
            check(f"{name}: W released: back to hands on hips", body.flight_pose == "hands_on_hips", body.flight_pose)
            held_keys["a"] = 1
            run(.7)
            held_keys["a"] = 0
            check(f"{name}: sideways only: still hands on hips", body.flight_pose == "hands_on_hips", body.flight_pose)
            held_keys["space"] = 1
            run(.7)
            view(f"pose_{name}_ascend_side", 8.0, 0.0)
            check(f"{name}: rising on Space: controlled, feet together", body.flight_pose == "ascending" and feet_apart(body) < .34, f"{feet_apart(body):.2f}")
            held_keys["space"] = 0
            held_keys["control"] = 1
            run(.5)
            view(f"pose_{name}_descend_side", 8.0, 0.0)
            held_keys["control"] = 0
            game.camera.pitch = -65.0
            held_keys["w"] = 1
            run(.7)
            check(f"{name}: W looking up: reaching", body.flight_pose == "reaching", body.flight_pose)
            check(f"{name}: climbing, the feet are together", feet_apart(body) < .34, f"{feet_apart(body):.2f}")
            view(f"pose_{name}_climb_side", 8.0, 0.0)
            held_keys["w"] = 0
            game.camera.pitch = game.camera.DEFAULT_PITCH
            run(.4)
            tap("f", .3)
            finish_sequences(8.0)
            run(1.0)
            check(f"{name}: landed, the legs are free again", body.visual._together < .4, f"{body.visual._together:.2f}")
            view(f"pose_{name}_landed_side", 7.0, 0.0)
            # A rush: arms and body together.
            fight(character, enemy, 120.0)
            teams.characters[enemy].vitals.max_health = teams.characters[enemy].vitals.health = 1e7
            tap("2", .05)
            view(f"pose_{name}_rush_side", 8.0, 0.0)
            finish_sequences(20.0)
            teams.characters[enemy].vitals.max_health = teams.characters[enemy].vitals.health = 1000.0
        fight("RED", "WHITE", 1500.0)
        body = teams.player
        check("Soldier Boy still cannot fly", not body.flight_allowed)
        game.input("f")
        run(.5)
        view("pose_soldier_boy_jump_rising", 8.0, 0.0)
        game.input("f up")
        begin = time.perf_counter()
        while body.jump_velocity > 0.0 and time.perf_counter() - begin < 25.0:
            tick()
        run(.5)
        view("pose_soldier_boy_jump_falling", 8.0, 0.0)
        check("Soldier Boy: in the air, not striding or flying", not body.flight.is_flying and body.visual._gait < .01, f"gait {body.visual._gait:.2f}")
        calm[0] = False

    guarded("poses", scenario_poses)
    guarded("cape", scenario_cape)
    guarded("basics", scenario_basics)
    guarded("movement", scenario_movement)
    guarded("flight", scenario_flight)
    guarded("soldier boy", scenario_soldier)
    for character, enemy in (("WHITE", "RED"), ("BLACK", "RED"), ("YELLOW", "WHITE"), ("GREEN", "WHITE"), ("RED", "WHITE")):
        guarded(CHARACTERS[character], lambda c=character, e=enemy: scenario_abilities(c, e))
    guarded("void", scenario_void)
    guarded("squad", scenario_squad)
    guarded("lock and time", scenario_lock_and_time)
    guarded("destruction", scenario_destruction)
    guarded("menus", scenario_menus)
    soak = {}
    if args.soak:
        def scenario_soak():
            import ctypes
            teams.state.assignment.update({"YELLOW": MY_TEAM, "WHITE": ENEMY_TEAM, "BLACK": ENEMY_TEAM, "GREEN": ENEMY_TEAM, "RED": ENEMY_TEAM})
            teams._apply_roster()
            teams.swap("YELLOW", save=False)
            game.input("f")
            start = time.perf_counter()
            samples = []
            from tools_memory import memory_mb
            next_sample = start
            longest = [0.0]
            while time.perf_counter() - start < args.soak:
                elapsed = time.perf_counter() - start
                held_keys["w"] = 1 if int(elapsed / 20) % 2 == 0 else 0
                game.camera.yaw = (elapsed * 7.0) % 360.0
                healthy()
                tick()
                if time.perf_counter() >= next_sample:
                    samples.append(round(memory_mb(), 1))
                    next_sample += 30.0
            held_keys["w"] = 0
            soak["memory_mb_every_30_s"] = samples
            soak["entities_end"] = len(scene.entities)
            check("soak finished", True, f"{args.soak:.0f} s; memory {samples[0]} -> {samples[-1]} MB")
        guarded("soak", scenario_soak)
    ordered = sorted(frame_ms)
    summary = {"quality": args.quality, "passed": sum(r["passed"] for r in results), "failed": sum(not r["passed"] for r in results),
               "frames": len(frame_ms), "average_fps": round(1000.0 * len(frame_ms) / sum(frame_ms), 1),
               "p95_ms": round(ordered[int(len(ordered) * .95)], 1), "p99_ms": round(ordered[int(len(ordered) * .99)], 1), "worst_ms": round(ordered[-1], 1), "worst_ms_by_scenario": scenario_worst, **soak, "checks": results}
    (out / "results.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "checks"}), flush=True)
    application.base.userExit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
