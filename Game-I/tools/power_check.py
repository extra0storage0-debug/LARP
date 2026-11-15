"""Who may use what, Soldier Boy's Key 2, and fighting back from a knockdown: in a real window, through the real keys.

Knockdowns come from real enemy attacks. Pictures come from the game's own window buffer, and each sequence becomes one contact sheet.

    python tools/power_check.py --out <folder> [--only WHITE,RED]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
FOLDER = Path(tempfile.mkdtemp(prefix="nltl_powers_"))
for _name, _variable in (("island_destruction.json", "SENTRY_DESTRUCTION_SAVE"), ("profiles.json", "SENTRY_PROFILE_FILE"),
                         ("roster.json", "SENTRY_ROSTER_FILE"), ("powers.json", "SENTRY_POWER_FILE")):
    os.environ[_variable] = str(FOLDER / _name)
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import main as launcher  # noqa: E402
from panda3d.core import Filename  # noqa: E402
from PIL import Image  # noqa: E402
from ursina import application, camera, window  # noqa: E402

from ai.combat_ai import MOVES  # noqa: E402
from characters.roster import KITS, ROSTER_IDS  # noqa: E402
from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM  # noqa: E402
from config.power_schema import PLAYER_ONLY_ABILITIES, SLOT_ABILITIES  # noqa: E402
from movement.flight_physics import FlightPhase, Vec3 as SimVec3  # noqa: E402
from powers.aiming import center_of  # noqa: E402
from powers.common import LaunchedMotion  # noqa: E402
from powers.soldier_boy_attacks import FlyingPunch  # noqa: E402
from powers.universal import StrikeAndBreakAway  # noqa: E402

SPOT = (300.0, 300.0)
TOUGH = 1e7


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    app, game = launcher.build_game("onscreen")
    application.asset_folder = ROOT
    window.size = (1280, 720)
    camera.ui.hide()
    teams, world, combat = game.teams, game.world, game.combat
    results: list = []

    def check(name: str, passed: bool, detail="") -> None:
        results.append({"name": name, "passed": bool(passed), "detail": str(detail)[:200]})
        print(("PASS " if passed else "FAIL ") + name + f"  {detail}", flush=True)

    def tick() -> None:
        game.update(1.0 / 60.0)
        app.step()

    def run(seconds: float) -> None:
        for _ in range(int(seconds * 60)):
            tick()

    def key(name: str) -> None:
        game.input(name)
        game.input(f"{name} up")

    def still(path: Path) -> None:
        body = teams.player
        camera.world_position = (float(body.x) + 8.0, float(body.y) + 1.6, float(body.z))
        camera.look_at((float(body.x), float(body.y) + 1.4, float(body.z)))
        camera.rotation_z = 0.0
        app.step()
        app.step()
        application.base.win.saveScreenshot(Filename.from_os_specific(str(path)))

    def sequence(name: str, seconds: float, count: int) -> None:
        frames = []
        for index in range(count):
            run(seconds / count)
            path = out / f"_{name}_{index}.png"
            still(path)
            frames.append(path)
        tiles = []
        for path in frames:
            image = Image.open(path).convert("RGB")
            width, height = image.size
            side = int(height * .92)
            tiles.append(image.crop(((width - side) // 2, (height - side) // 2, (width + side) // 2, (height + side) // 2)).resize((400, 400), Image.LANCZOS))
            path.unlink(missing_ok=True)
        columns = min(6, len(tiles))
        canvas = Image.new("RGB", (columns * 400, ((len(tiles) + columns - 1) // columns) * 400))
        for index, tile in enumerate(tiles):
            canvas.paste(tile, ((index % columns) * 400, (index // columns) * 400))
        canvas.save(out / f"{name}.png")

    def begin(character_id: str, enemy_id: str, distance: float = 40.0, *, frozen: bool = True):
        """Those two only, away from everything, and neither of them about to die."""
        combat.end_world_stop()
        combat.end_time_stop()
        for other in ROSTER_IDS:
            teams.state.assignment[other] = AVAILABLE
        teams.state.assignment[character_id] = MY_TEAM
        teams.state.assignment[enemy_id] = ENEMY_TEAM
        teams._apply_roster()
        teams.swap(character_id, save=False)
        body, enemy = teams.player, teams.characters[enemy_id]
        for one, (x, z) in ((body, SPOT), (enemy, (SPOT[0], SPOT[1] + distance))):
            one.powers.hard_reset()
            one.release_motion()
            one.flight.phase = FlightPhase.GROUNDED
            one.flight.velocity = SimVec3()
            one.ground.velocity = SimVec3()
            one.knock = SimVec3()
            one.jump_height = one.jump_velocity = 0.0
            one.position = (x, world.height_at(x, z) + .25, z)
            one.vitals.health = one.vitals.max_health = TOUGH
        game.camera.yaw = 0.0
        game.camera.pitch = game.camera.DEFAULT_PITCH
        combat.targets.manual = None
        if frozen:
            enemy.vitals.add_status("frozen", 3600.0)
        run(.1)
        return body, enemy

    def finish(limit: float = 40.0) -> bool:
        for _ in range(int(limit * 60)):
            if teams.player.motion is None and not combat.sequence_running:
                return True
            tick()
        return False

    def thrown_by_enemy(character_id: str, enemy_id: str):
        """A real blow: the enemy's own Key 2, under AI, sends the player flying."""
        body, enemy = begin(character_id, enemy_id, 40.0, frozen=False)
        enemy.powers.abilities[SLOT_ABILITIES[enemy_id]["2"]].press()
        for _ in range(300):
            tick()
            if isinstance(body.motion, LaunchedMotion):
                enemy.vitals.add_status("frozen", 3600.0)
                return body, enemy
        return None, enemy

    def foe(character_id: str) -> str:
        return "RED" if character_id != "RED" else "WHITE"

    wanted = [item for item in args.only.split(",") if item] or list(ROSTER_IDS)
    combat.ai_powers_enabled = True
    for character_id in wanted:
        name = KITS[character_id].display.lower().replace(" ", "_").replace("-", "_")
        print("=====", name, flush=True)

        # 1, 2: AI, by every route there is
        player_id = foe(character_id)
        body, ai_body = begin(player_id, character_id, 30.0, frozen=False)
        forbidden = PLAYER_ONLY_ABILITIES[character_id]
        check(f"{name}: 1-2 keys 3 and 4 are the ones AI is denied", forbidden == {SLOT_ABILITIES[character_id]["3"], SLOT_ABILITIES[character_id]["4"]}, sorted(forbidden))
        check(f"{name}: 1-2 AI is never offered them", not ({move.ability_id for move in MOVES[character_id]} & forbidden))
        for ability_id in forbidden:
            ability = ai_body.powers.abilities[ability_id]
            ability.press()
            check(f"{name}: 1-2 AI calling {ability_id} directly does nothing", ai_body.motion is None and not combat.sequence_running)
        tried, used = [], []
        spies = {}
        for ability_id, ability in ai_body.powers.abilities.items():
            real = ability.press

            def spy(ability_id=ability_id, real=real):
                (tried if ability_id in forbidden else used).append(ability_id)
                return real()
            ability.press = spy
            spies[ability_id] = ability
        body.vitals.add_status("frozen", 1.0)
        run(45.0)
        for ability in spies.values():
            del ability.press
        check(f"{name}: 1-2 45 s of real AI combat never tried them", not tried, tried)
        check(f"{name}: AI still fights with what it is allowed", bool(used), sorted(set(used)))

        # 3, 4: the player
        for number, slot in ((3, "3"), (4, "4")):
            body, enemy = begin(character_id, foe(character_id), 60.0)
            enemy.vitals.clear_status("frozen")
            before = enemy.vitals.damage_taken
            key(slot)
            started = body.motion is not None
            done = finish()
            check(f"{name}: {number} the player's Key {slot} runs and ends", started and done and not combat.time_stopped, f"damage {enemy.vitals.damage_taken - before:.0f}")
            run(.3)

        # 5-8: everyone else's Key 2
        if character_id != "RED":
            body, enemy = begin(character_id, "RED", 60.0)
            enemy.vitals.clear_status("frozen")
            key("2")
            check(f"{name}: 5-8 keeps the original Key 2", SLOT_ABILITIES[character_id]["2"] == "high_speed_attack"
                  and isinstance(body.motion, StrikeAndBreakAway) and not isinstance(body.motion, FlyingPunch), type(body.motion).__name__)
            check(f"{name}: 5-8 it stops time and ends", combat.time_stopped and finish() and not combat.time_stopped)
        else:
            # 9-12: the new one
            for label, height in (("ground", 0.0), ("air", 80.0)):
                body, enemy = begin("RED", "WHITE", 150.0)
                enemy.vitals.clear_status("frozen")
                enemy.y = float(enemy.y) + height
                if height:
                    enemy.flight.phase = FlightPhase.CRUISE
                aside = teams.characters["BLACK"]
                teams.state.assignment["BLACK"] = ENEMY_TEAM
                teams._apply_roster()
                aside.position = (SPOT[0] + 200.0, world.height_at(SPOT[0] + 200.0, SPOT[1]) + .25, SPOT[1])
                aside.vitals.health = aside.vitals.max_health = TOUGH
                run(.05)
                spot_aside = (float(aside.x), float(aside.y), float(aside.z))
                before = enemy.vitals.damage_taken
                key("2")
                check(f"soldier_boy: 9 Key 2 is the Flying Punch, {label}", isinstance(body.motion, FlyingPunch), type(body.motion).__name__)
                check(f"soldier_boy: 11 it stops the world, {label}", combat.time_stopped)
                speed, flew, last = 0.0, False, (float(body.x), float(body.y), float(body.z))
                nearest = 1e9
                frames = 0
                while isinstance(body.motion, FlyingPunch) and body.motion.connected_for is None and frames < 400:
                    tick()
                    frames += 1
                    now = (float(body.x), float(body.y), float(body.z))
                    speed = max(speed, sum((a - b) ** 2 for a, b in zip(now, last)) ** .5 * 60.0)
                    last = now
                    flew = flew or body.flight.is_flying
                    if not isinstance(enemy.motion, LaunchedMotion):
                        nearest = min(nearest, (center_of(body) - center_of(enemy)).length())
                check(f"soldier_boy: 10 the punch connects with the real target, {label}", enemy.vitals.damage_taken > before and nearest < 4.0 and isinstance(enemy.motion, LaunchedMotion),
                      f"{enemy.vitals.damage_taken - before:.0f} damage, from {nearest:.1f} m")
                check(f"soldier_boy: 9 extreme speed, {label}", speed > 500.0, f"{speed:.0f} m/s")
                check(f"soldier_boy: 11 nobody else moved in the stop, {label}", spot_aside == (float(aside.x), float(aside.y), float(aside.z)))
                ended = finish(5.0)
                check(f"soldier_boy: 11 time resumes, {label}", ended and not combat.time_stopped)
                thrown_at = float(enemy.z)
                run(.3)
                check(f"soldier_boy: 11 the world moves again, {label}", float(enemy.z) != thrown_at)
                for _ in range(300):
                    flew = flew or body.flight.is_flying
                    tick()
                check(f"soldier_boy: 12 never in flight, back on the ground, {label}", not flew and body.jump_height < .01, f"{body.jump_height:.2f} m up")
            body, enemy = begin("RED", "WHITE", 400.0)
            enemy.vitals.clear_status("frozen")
            key("2")
            sequence("soldier_boy_flying_punch", .24, 6)
            finish(5.0)
            for leave in ("target parked", "target downed"):
                body, enemy = begin("RED", "WHITE", 400.0)
                enemy.vitals.clear_status("frozen")
                key("2")
                if leave == "target parked":
                    teams.state.assignment["WHITE"] = AVAILABLE
                    teams._apply_roster()
                else:
                    enemy.vitals.downed_for = 3.0
                check(f"soldier_boy: 11 time resumes with the {leave}", finish(4.0) and not combat.time_stopped)
                enemy.vitals.downed_for = 0.0

        # 13-20: a real blow, then every key, in the air and on the ground
        body, enemy = thrown_by_enemy(character_id, foe(character_id))
        check(f"{name}: 13 knocked flying by a real enemy attack", body is not None)
        if body is None:
            continue
        finish_stop = finish  # the blow's own stop, if any, is not the player's; AI never stops time
        check(f"{name}: 13 the blow did damage, and no time stop", body.vitals.damage_taken > 0.0 and not combat.time_stopped, f"{body.vitals.damage_taken:.0f}")

        def tumbling(lying: bool = False):
            body, enemy = begin(character_id, foe(character_id), 60.0)
            from powers.common import launch_character
            launch_character(enemy, body, SimVec3(0.0, 14.0, -30.0) if lying else SimVec3(0.0, 35.0, -25.0))
            for _ in range(900):
                tick()
                motion = body.motion
                if not lying and float(body.y) - world.height_at(float(body.x), float(body.z)) > 6.0:
                    return body, enemy
                if lying and isinstance(motion, LaunchedMotion) and motion.landed:
                    return body, enemy
            return body, enemy

        for lying, where in ((False, "falling"), (True, "lying down")):
            for number, slot in ((14, "1"), (15, "2"), (16, "3"), (17, "4")):
                body, enemy = tumbling(lying)
                enemy.vitals.clear_status("frozen")
                in_tumble = isinstance(body.motion, LaunchedMotion)
                here = (float(body.x), float(body.y), float(body.z))
                ability = body.powers.slots[slot]
                before = enemy.vitals.damage_taken
                key(slot)
                moved = sum((a - b) ** 2 for a, b in zip(here, (float(body.x), float(body.y), float(body.z)))) ** .5
                started = ability.active or body.motion is not None or bool(ability.hud_state())
                number_shown = number if not lying else 19
                check(f"{name}: {number_shown} Key {slot} {where} starts at once, without a jump", in_tumble and started and moved < 1.0 and not isinstance(body.motion, LaunchedMotion),
                      f"{type(body.motion).__name__}, moved {moved:.2f} m")
                if slot in ("2", "3", "4"):
                    done = finish()
                    check(f"{name}: 20 Key {slot} {where} ends, with time running", done and not combat.time_stopped, f"damage {enemy.vitals.damage_taken - before:.0f}")
                else:
                    run(.4)
                    body.powers.cancel_all()
                    body.release_motion()
                run(1.5)
                check(f"{name}: 20 Key {slot} {where}: standing or flying properly after", abs(body.pose_root.getP()) < 60.0 and abs(body.visual.body_root.getP()) < 5.0,
                      f"pose {body.pose_root.getP():.1f}, recovery {body.visual.body_root.getP():.1f}")

        # 18: flight
        if KITS[character_id].can_fly:
            for lying, where in ((False, "falling"), (True, "lying down")):
                body, enemy = tumbling(lying)
                velocity = body.motion.velocity
                y = float(body.y)
                key("f")
                check(f"{name}: 18 F {where} goes straight to flight", body.flight.is_flying and body.motion is None and abs(float(body.y) - y) < 1.0, body.flight.phase.name)
                check(f"{name}: 18 and keeps its speed, {where}", abs(body.flight.velocity.z - velocity.z) < 1.0, f"{body.flight.velocity.z:.1f} from {velocity.z:.1f}")
                if not lying:
                    sequence(f"{name}_18_recover_into_flight", 1.2, 6)
                else:
                    run(1.2)
                check(f"{name}: 18 flying upright, {where}", body.flight.is_flying and abs(body.visual.body_root.getP()) < 5.0 and abs(body.pose_root.getP()) < 25.0,
                      f"pose {body.pose_root.getP():.1f}, {body.flight_pose}")
        else:
            body, enemy = tumbling(False)
            key("f")
            run(.3)
            check(f"{name}: 18 F while falling never flies", not body.flight.is_flying)
            finish(10.0)

        # time stop from a fall
        body, enemy = tumbling(False)
        key("t")
        check(f"{name}: T while falling stops the world", combat.world_stopped and not isinstance(body.motion, LaunchedMotion))
        spot = (float(enemy.x), float(enemy.z))
        run(.4)
        check(f"{name}: T: the enemy waits", spot == (float(enemy.x), float(enemy.z)))
        combat.end_world_stop()
        check(f"{name}: T: time resumes", not combat.time_stopped)

        # picture: fighting back from a real fall
        body, enemy = tumbling(False)
        enemy.vitals.clear_status("frozen")
        key("2")
        sequence(f"{name}_20_key_2_from_a_fall", 1.0, 6)
        finish()

        # AI is still knocked about, and gets no help
        body, enemy = begin(character_id, foe(character_id), 60.0)
        enemy.vitals.clear_status("frozen")
        from powers.common import launch_character
        launch_character(body, enemy, SimVec3(0.0, 30.0, 10.0))
        enemy.powers.press("1")
        check(f"{name}: AI is still knocked down, with no such help", isinstance(enemy.motion, LaunchedMotion))
        enemy.release_motion()

    failed = [item for item in results if not item["passed"]]
    (out / "power_results.json").write_text(json.dumps({"passed": len(results) - len(failed), "failed": len(failed), "checks": results}, indent=1), encoding="utf-8")
    print(json.dumps({"passed": len(results) - len(failed), "failed": len(failed)}), flush=True)
    os._exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
