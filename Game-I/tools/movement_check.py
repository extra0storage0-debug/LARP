"""Section by section, in a real window and with the real input path: how every character moves, measured and photographed.

Stills come from the game's own window buffer. Each sequence is also stitched into one contact sheet.

    python tools/movement_check.py --out <folder> [--only WHITE,RED]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
FOLDER = Path(tempfile.mkdtemp(prefix="nltl_movement_"))
for _name, _variable in (("island_destruction.json", "SENTRY_DESTRUCTION_SAVE"), ("profiles.json", "SENTRY_PROFILE_FILE"),
                         ("roster.json", "SENTRY_ROSTER_FILE"), ("powers.json", "SENTRY_POWER_FILE")):
    os.environ[_variable] = str(FOLDER / _name)
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import main as launcher  # noqa: E402
from panda3d.core import Filename, LVector3f  # noqa: E402
from PIL import Image  # noqa: E402
from ursina import application, camera, held_keys, scene, window  # noqa: E402

from characters.roster import KITS, ROSTER_IDS  # noqa: E402
from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM  # noqa: E402
from movement.flight_physics import FlightPhase  # noqa: E402

SPOTS = {"WHITE": (300.0, 300.0), "BLACK": (340.0, 300.0), "YELLOW": (380.0, 300.0), "GREEN": (420.0, 300.0), "RED": (460.0, 300.0)}


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
    camera.ui.hide()  # the body, without the HUD over it
    teams, world = game.teams, game.world
    results: list = []
    numbers: dict = {}

    def check(name: str, passed: bool, detail="") -> None:
        results.append({"name": name, "passed": bool(passed), "detail": str(detail)[:200]})
        print(("PASS " if passed else "FAIL ") + name + f"  {detail}", flush=True)

    def tick() -> None:
        game.update(1.0 / 60.0)
        app.step()

    def run(seconds: float) -> None:
        for _ in range(int(seconds * 60)):
            tick()

    def set_view(side: float, behind: float, up: float = 1.4) -> None:
        body = teams.player
        camera.world_position = (float(body.x) + side, float(body.y) + up, float(body.z) - behind)
        camera.look_at((float(body.x), float(body.y) + 1.5, float(body.z)))
        camera.rotation_z = 0.0

    def still(path: Path, side: float, behind: float, up: float = 1.4) -> None:
        set_view(side, behind, up)
        app.step()
        app.step()
        application.base.win.saveScreenshot(Filename.from_os_specific(str(path)))

    def sheet(name: str, frames: list) -> None:
        tiles = [Image.open(path).convert("RGB") for path in frames]
        w, h = 400, 400
        crops = []
        for image in tiles:
            width, height = image.size
            side = int(height * .92)
            left, top = (width - side) // 2, (height - side) // 2
            crops.append(image.crop((left, top, left + side, top + side)).resize((w, h), Image.LANCZOS))
        columns = min(6, len(crops))
        rows = (len(crops) + columns - 1) // columns
        canvas = Image.new("RGB", (columns * w, rows * h))
        for index, crop in enumerate(crops):
            canvas.paste(crop, ((index % columns) * w, (index // columns) * h))
        canvas.save(out / f"{name}.png")
        for path in frames:
            path.unlink(missing_ok=True)

    def sequence(name: str, seconds: float, count: int, side: float, behind: float, up: float = 1.4) -> None:
        """Keep playing, and take ``count`` stills across the time."""
        frames = []
        for index in range(count):
            run(seconds / count)
            path = out / f"_{name}_{index}.png"
            still(path, side, behind, up)
            frames.append(path)
        sheet(name, frames)

    def begin(character_id: str) -> None:
        for other in ROSTER_IDS:
            teams.state.assignment[other] = MY_TEAM if other == character_id else AVAILABLE
        teams._apply_roster()
        teams.swap(character_id, save=False)
        body = teams.player
        body.powers.hard_reset()
        body.release_motion()
        body.flight.phase = FlightPhase.GROUNDED
        body.flight.velocity = body.flight.velocity * 0.0
        body.ground.velocity = body.ground.velocity * 0.0
        x, z = SPOTS[character_id]
        body.position = (x, world.height_at(x, z) + .25, z)
        game.camera.yaw = 0.0
        game.camera.pitch = game.camera.DEFAULT_PITCH
        held_keys.clear() if hasattr(held_keys, "clear") else None
        run(.5)

    def contacts() -> list:
        visual = teams.player.visual
        shape = visual._leg_shape
        points = []
        for name in ("foot_l", "foot_r"):
            node = visual._controls[name]
            points.append(scene.getRelativePoint(node, LVector3f(0.0, -shape.sole, -shape.heel)))
            points.append(scene.getRelativePoint(node, LVector3f(0.0, -shape.sole, shape.ball)))
        return points

    def height(point) -> float:
        return float(point.y) - world.height_at(float(point.x), float(point.z))

    def slide(seconds: float) -> tuple:
        worst, touches = 0.0, 0
        planted = [None] * 4
        floor = min(height(point) for point in contacts())
        highest = -1e9
        for _ in range(int(seconds * 60)):
            tick()
            points = contacts()
            lowest = min(height(point) for point in points)
            floor = min(floor, lowest)
            highest = max(highest, lowest)
            for index, point in enumerate(points):
                if height(point) >= floor + .035 or not teams.player.visual.foot_is_planted(index // 2):
                    planted[index] = None
                elif planted[index] is None:
                    planted[index] = (float(point.x), float(point.z))
                    touches += 1
                else:
                    worst = max(worst, ((float(point.x) - planted[index][0]) ** 2 + (float(point.z) - planted[index][1]) ** 2) ** .5)
        return worst, touches, highest - floor

    def run_speed(body, speed: float) -> None:
        body.ground.walk_speed = speed
        body.ground.sprint_multiplier = 1.0
        body.ground.max_running_speed = speed

    wanted = [item for item in args.only.split(",") if item] or list(ROSTER_IDS)
    for character_id in wanted:
        name = KITS[character_id].display.lower().replace(" ", "_").replace("-", "_")
        print("=====", name, flush=True)
        number = numbers[character_id] = {}
        begin(character_id)
        body = teams.player
        ground_top = body.own_run_speed

        # 1. standing to walking
        speeds = []
        held_keys["w"] = 1
        for _ in range(45):
            tick()
            speeds.append(body.ground.velocity.length())
        check(f"{name}: 1 speeds up from standing into a walk", speeds[3] < 1.2 < speeds[-1], f"{speeds[3]:.2f} then {speeds[-1]:.2f} m/s")
        run(.8)
        worst, touches, floating = slide(4.0)
        number["walk_slide_m"], number["walk_floating_m"] = round(worst, 3), round(floating, 3)
        check(f"{name}: 1 walking, the feet stay put", worst < .08 and touches >= 4, f"{worst:.3f} m over {touches} contacts")
        check(f"{name}: 1 walking, a foot is always on the ground", floating < .14, f"{floating:.3f} m")
        sequence(f"{name}_01_walk_side", 1.0, 6, 6.0, 0.0)
        sequence(f"{name}_01_walk_front", .9, 3, 0.0, -7.0)

        # 2. walking to running, at a speed legs can do
        run_speed(body, 12.0)
        body._outrun_everyone = lambda: None  # his top speed is over a thousand m/s: this is about what legs can do
        held_keys["shift"] = 1
        run(1.2)
        running = abs(body.visual.left_knee.rotation_x) + abs(body.visual.right_knee.rotation_x)
        worst, touches, _ = slide(3.0)
        number["run12_slide_m"] = round(worst, 3)
        check(f"{name}: 2 a run at 12 m/s does not slide", worst < .12, f"{worst:.3f} m over {touches} contacts")
        check(f"{name}: 2 running bends the knees hard", running > 30.0, f"{running:.0f} deg")
        sequence(f"{name}_02_run_side", .55, 6, 8.0, 0.0)

        # 3. running to stopping
        held_keys["shift"] = held_keys["w"] = 0
        peak = body.ground.velocity.length()
        run(.25)
        mid = body.ground.velocity.length()
        run(1.5)
        check(f"{name}: 3 slows down and stops", peak > mid > 0.0 and body.ground.velocity.length() < .05 and body.visual._gait == 0.0,
              f"{peak:.1f}, {mid:.1f}, then {body.ground.velocity.length():.2f} m/s")
        begin(character_id)

        # 4. turns
        held_keys["w"] = 1
        run(1.2)
        yaw_before = body.local_yaw
        snapped = 0.0
        last = body.local_yaw
        for _ in range(60):
            game.camera.yaw += 1.5
            tick()
            snapped = max(snapped, abs(((body.local_yaw - last + 180.0) % 360.0) - 180.0))
            last = body.local_yaw
        check(f"{name}: 4 turns smoothly walking", abs(body.local_yaw - yaw_before) > 40.0 and snapped < 7.0, f"at most {snapped:.1f} deg a frame")
        held_keys["w"] = 0
        run(.5)
        begin(character_id)

        # 5. jump and land
        game.input("space")
        run(.2)
        game.input("space up")
        peak_height = 0.0
        for _ in range(180):
            tick()
            peak_height = max(peak_height, body.jump_height)
            if peak_height > 0.0 and body.jump_height <= 0.0:
                break
        check(f"{name}: 5 jumps", peak_height > .3, f"{peak_height:.1f} m")
        run(.05)
        squat = body.visual._squat
        check(f"{name}: 5 the legs take the landing", squat > .05, f"{squat:.2f}")
        run(1.0)

        if not KITS[character_id].can_fly:
            game.input("f")
            run(.4)
            game.input("f up")
            check(f"{name}: never flies", not body.flight.is_flying)
            run(4.0)
            continue

        # 6. take-off
        begin(character_id)
        game.input("f")
        frames = []
        heights = []
        for index in range(6):
            run(.18)
            heights.append(float(body.y))
            path = out / f"_{name}_takeoff_{index}.png"
            still(path, 7.0, 0.0)
            frames.append(path)
        sheet(f"{name}_06_takeoff", frames)
        check(f"{name}: 6 takes off smoothly", body.flight.is_flying and heights[-1] > heights[0] + .3
              and max(b - a for a, b in zip(heights, heights[1:])) < 6.0, [round(h - heights[0], 1) for h in heights])
        run(1.0)

        # 7. forward flight
        game.camera.pitch = -2.0
        held_keys["w"] = 1
        speeds = []
        for _ in range(60):
            tick()
            speeds.append(body.flight.speed_mps)
        check(f"{name}: 7 builds up speed", speeds[5] < speeds[-1] * .7 and all(b >= a - 1.0 for a, b in zip(speeds, speeds[1:])), f"{speeds[5]:.0f} to {speeds[-1]:.0f} m/s")
        run(.6)
        check(f"{name}: 7 forward pose", body.flight_pose == "reaching", body.flight_pose)
        lean = abs(body.pose_root.getP())
        check(f"{name}: 7 leans along the flight", lean > 45.0, f"{lean:.0f} deg")
        sequence(f"{name}_07_forward", .6, 3, 8.0, 0.0)

        # 8. W released
        held_keys["w"] = 0
        leans = []
        for _ in range(90):
            tick()
            leans.append(abs(body.pose_root.getP()))
        check(f"{name}: 8 comes back upright smoothly", leans[-1] < 25.0 and max(abs(b - a) for a, b in zip(leans, leans[1:])) < 8.0,
              f"to {leans[-1]:.0f} deg, at most {max(abs(b - a) for a, b in zip(leans, leans[1:])):.1f} a frame")
        run(2.0)
        check(f"{name}: 8 hover: hands on hips, still", body.flight_pose == "hands_on_hips" and body.flight.speed_mps < 3.0, f"{body.flight_pose}, {body.flight.speed_mps:.1f} m/s")
        sequence(f"{name}_08_hover", .3, 3, 7.0, 0.0)

        # 9. up and down
        held_keys["space"] = 1
        before = float(body.y)
        run(.9)
        check(f"{name}: 9 rises on Space", float(body.y) > before + 1.0 and body.flight_pose == "ascending", f"{float(body.y) - before:.1f} m, {body.flight_pose}")
        sequence(f"{name}_09_ascend", .3, 3, 7.0, 0.0)
        held_keys["space"] = 0
        run(.6)
        held_keys["control"] = 1
        before = float(body.y)
        run(.8)
        check(f"{name}: 9 sinks on Ctrl", float(body.y) < before - .5 and body.flight_pose == "descending", f"{float(body.y) - before:.1f} m, {body.flight_pose}")
        sequence(f"{name}_09_descend", .3, 3, 7.0, 0.0)
        held_keys["control"] = 0
        run(.8)

        # 10. turning in flight
        held_keys["w"] = 1
        run(1.2)
        most_bank, snapped, last = 0.0, 0.0, body.local_yaw
        for _ in range(70):
            game.camera.yaw += 2.0
            tick()
            most_bank = max(most_bank, abs(body.pose_root.getR()))
            snapped = max(snapped, abs(((body.local_yaw - last + 180.0) % 360.0) - 180.0))
            last = body.local_yaw
        check(f"{name}: 10 banks into a turn, without snapping", most_bank > 3.0 and snapped < 9.0, f"bank {most_bank:.0f} deg, at most {snapped:.1f} deg a frame")
        sequence(f"{name}_10_turn", .3, 3, 0.0, 8.0, 2.0)

        # 11. boost
        held_keys["shift"] = 1
        cruise = body.flight.speed_mps
        run(1.5)
        check(f"{name}: 11 boost goes faster", body.flight.speed_mps > cruise, f"{cruise:.0f} to {body.flight.speed_mps:.0f} m/s")
        hem = body.visual._chain.point(5) if body.visual.kit.cape else None
        if hem is not None:
            check(f"{name}: 11 the cape streams behind", body.visual._chain.air_speed > 10.0, f"air {body.visual._chain.air_speed:.0f} m/s")
        sequence(f"{name}_11_boost", .4, 3, 9.0, 0.0)
        held_keys["shift"] = held_keys["w"] = 0
        run(1.5)

        # 12. landing, under control and by slamming
        held_keys["control"] = 1
        for _ in range(60 * 12):
            tick()
            if body.flight.phase is FlightPhase.GROUNDED:
                break
        held_keys["control"] = 0
        landed = body.flight.phase is FlightPhase.GROUNDED
        check(f"{name}: 12 lands on Ctrl", landed, body.flight.phase.name)
        frames = []
        for index in range(3):
            run(.2)
            path = out / f"_{name}_land_{index}.png"
            still(path, 7.0, 0.0)
            frames.append(path)
        sheet(f"{name}_12_landed", frames)
        run(.8)
        check(f"{name}: 12 back on its feet", not body.flight.is_flying and abs(body.left_leg.rotation_x) < 12.0, f"{body.left_leg.rotation_x:.1f}")

    failed = [item for item in results if not item["passed"]]
    (out / "movement_results.json").write_text(json.dumps({"passed": len(results) - len(failed), "failed": len(failed), "numbers": numbers, "checks": results}, indent=1), encoding="utf-8")
    print(json.dumps({"passed": len(results) - len(failed), "failed": len(failed), "numbers": numbers}), flush=True)
    os._exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
