"""The player flies exactly where the centre of the screen points."""

from __future__ import annotations

from math import acos, degrees
import unittest
import unittest.mock

from ursina import camera, held_keys

from game_fixture import FRAME
from movement.flight_physics import FlightConfig, FlightDynamics, FlightPhase, Vec3 as SimVec3
from test_gameplay_control_update import FLYERS, LiveCase


def angle_between(a, b) -> float:
    a, b = a.normalized(), b.normalized()
    return degrees(acos(max(-1.0, min(1.0, a.x * b.x + a.y * b.y + a.z * b.z))))


class AimCase(LiveCase):
    def airborne(self, character_id: str, height: float = 250.0, distance: float = 4000.0):
        self.begin(character_id, enemy="RED", distance=distance)
        self.enemy.vitals.add_status("frozen", 600.0)
        player = self.player
        player.position = (float(player.x), float(player.y) + height, float(player.z))
        player.flight.phase = FlightPhase.CRUISE
        player.flight.velocity = SimVec3()
        self.rig = self.game.camera
        self.addCleanup(self._reset_keys)
        return player

    def _reset_keys(self) -> None:
        for key in ("w", "s", "a", "d", "shift", "space", "control"):
            held_keys[key] = 0

    def aim(self, yaw: float, pitch: float) -> None:
        self.rig.yaw, self.rig.pitch = yaw, pitch

    def aim_vector(self):
        return self.rig.aim_direction(SimVec3(self.player.x, self.player.y, self.player.z))

    def fly(self, seconds: float, *keys) -> SimVec3:
        """Hold keys for a while and return how far the body actually went."""
        for key in keys or ("w",):
            held_keys[key] = 1
        start = SimVec3(float(self.player.x), float(self.player.y), float(self.player.z))
        self.seconds(seconds)
        for key in keys or ("w",):
            held_keys[key] = 0
        return SimVec3(float(self.player.x), float(self.player.y), float(self.player.z)) - start


AIMS = {"straight ahead": (0.0, 0.0), "at the sky": (0.0, -89.0), "at the ground": (0.0, 89.0),
        "up and right": (40.0, -35.0), "down and left": (-70.0, 30.0), "up and behind": (160.0, -60.0),
        "down and behind": (200.0, 50.0)}


class DirectionTests(AimCase):
    def test_each_flyer_goes_where_the_screen_centre_points(self):
        for character_id in FLYERS:
            for name, (yaw, pitch) in AIMS.items():
                with self.subTest(f"{character_id} {name}"):
                    self.airborne(character_id, height=300.0)
                    self.aim(yaw, pitch)
                    moved = self.fly(1.0)
                    self.assertGreater(moved.length(), 10.0)
                    self.assertLess(angle_between(moved, self.aim_vector()), 1.5)
                    self.assertLess(angle_between(self.player.flight.velocity, self.aim_vector()), 1.0)

    def test_the_aim_is_the_cameras_real_forward_vector(self):
        self.airborne("WHITE")
        for yaw, pitch in AIMS.values():
            self.aim(yaw, pitch)
            self.frames(1)
            actual = SimVec3(camera.forward.x, camera.forward.y, camera.forward.z)
            self.assertLess(angle_between(actual, self.aim_vector()), .1)

    def test_s_flies_the_opposite_way_along_the_aim(self):
        self.airborne("BLACK")
        self.aim(30.0, -40.0)
        moved = self.fly(1.0, "s")
        self.assertGreater(angle_between(moved, self.aim_vector()), 178.0)

    def test_pitch_cannot_go_over_the_top(self):
        self.airborne("YELLOW")
        self.rig.pitch = 500.0
        self.frames(1)
        self.assertEqual(self.rig.pitch, 89.0)
        self.rig.pitch = -500.0
        self.frames(1)
        self.assertEqual(self.rig.pitch, -89.0)


class ResponseTests(AimCase):
    def test_a_turn_of_the_camera_changes_direction_at_once(self):
        for start, finish in (((0.0, 0.0), (90.0, 0.0)), ((0.0, 0.0), (0.0, -80.0)), ((0.0, 0.0), (180.0, 0.0))):
            with self.subTest(f"{start} to {finish}"):
                self.airborne("GREEN", height=300.0)
                self.aim(*start)
                self.fly(1.5)
                held_keys["w"] = 1
                self.aim(*finish)
                self.seconds(.4)
                self.assertLess(angle_between(self.player.flight.velocity, self.aim_vector()), 8.0)
                held_keys["w"] = 0

    def test_shift_goes_faster_without_changing_direction_and_slows_smoothly(self):
        self.airborne("WHITE", height=300.0)
        self.aim(25.0, 0.0)
        self.fly(1.0)
        cruise = self.player.flight.speed_mps
        self.assertGreater(self.fly(2.0, "w", "shift").length(), cruise * 2.0)
        boosted = self.player.flight.speed_mps
        self.assertGreater(boosted, cruise * 1.5)
        self.assertLess(angle_between(self.player.flight.velocity, self.aim_vector()), 1.0)
        held_keys["w"] = 1
        previous = boosted
        for _ in range(30):
            self.game.update(FRAME)
            speed = self.player.flight.speed_mps
            self.assertLess(previous - speed, 3.0, "no sudden stop when the boost ends")
            previous = speed
        held_keys["w"] = 0

    def test_letting_go_coasts_to_a_hover_without_falling(self):
        self.airborne("BLACK", height=300.0)
        self.aim(0.0, 0.0)
        self.fly(1.0)
        moving = self.player.flight.speed_mps
        self.seconds(.2)
        self.assertLess(self.player.flight.speed_mps, moving)
        self.assertGreater(self.player.flight.speed_mps, moving * .5, "not an instant stop")
        self.seconds(6.0)
        height = float(self.player.y)
        self.seconds(1.0)
        self.assertLess(self.player.flight.speed_mps, 5.0)
        self.assertAlmostEqual(float(self.player.y), height, delta=2.0)

    def test_space_and_ctrl_do_not_override_the_aim_but_still_work_on_their_own(self):
        self.airborne("YELLOW", height=300.0)
        self.aim(0.0, 0.0)
        moved = self.fly(1.0, "w", "space")
        self.assertLess(angle_between(moved, self.aim_vector()), 1.0)
        moved = self.fly(1.0, "w", "control")
        self.assertLess(angle_between(moved, self.aim_vector()), 1.0)
        self.seconds(4.0)
        self.assertGreater(self.fly(1.0, "space").y, 1.0)
        self.seconds(2.0)
        self.assertLess(self.fly(1.0, "control").y, -1.0)

    def test_the_same_journey_at_any_frame_rate(self):
        results = {}
        for fps in (30, 60, 120):
            flight = FlightDynamics(FlightConfig())
            flight.phase = FlightPhase.CRUISE
            position = SimVec3()
            aim = SimVec3(.6, .64, .48).normalized()
            for _ in range(2 * fps):
                velocity = flight.step(aim, 0.0, 1.0 / fps, aimed=True)
                position = position + velocity * (1.0 / fps)
            results[fps] = position
        for fps in (30, 120):
            self.assertLess((results[fps] - results[60]).length(), results[60].length() * .03)
            self.assertLess(angle_between(results[fps], SimVec3(.6, .64, .48)), .01)


class WorldTests(AimCase):
    def test_diving_stops_at_the_ground(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.airborne(character_id, height=80.0)
                self.tough(self.player)
                self.aim(0.0, 89.0)
                held_keys["w"] = held_keys["shift"] = 1
                self.seconds(4.0)
                held_keys["w"] = held_keys["shift"] = 0
                floor = self.game.world.height_at(self.player.x, self.player.z)
                self.assertGreaterEqual(float(self.player.y), floor - .01, "never through the terrain")
                self.assertLess(float(self.player.y), floor + 3.0, "and it did get there")

    def test_the_ceiling_still_holds(self):
        self.airborne("WHITE", height=400.0)
        self.aim(0.0, -89.0)
        self.fly(4.0, "w", "shift")
        self.assertLessEqual(float(self.player.y), self.game.planet.MAX_FLIGHT_ALTITUDE + .01)

    def test_flying_into_a_building_is_still_stopped(self):
        from power_fixture import object_of
        self.airborne("WHITE")
        building = next(obj for obj in self.game.world.objects if obj.anchored and not obj.health.broken
                        and abs(obj.scale_x) > 8.0 and abs(obj.scale_y) > 8.0 and abs(obj.scale_z) > 8.0)
        self.assertIsNotNone(object_of)
        self.player.position = (float(building.x), float(building.y), float(building.z) - abs(building.scale_z) * .5 - 40.0)
        self.player.flight.velocity = SimVec3()
        self.aim(0.0, 0.0)
        self.fly(1.5, "w", "shift")
        self.assertTrue(float(self.player.z) < float(building.z) or building.health.broken,
                        "stopped by it, or it broke")


class LockAndStateTests(AimCase):
    def test_flying_with_a_lock_goes_to_the_target(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.airborne(character_id, height=120.0, distance=1500.0)
                self.game.input("q")
                self.assertIs(self.combat.targets.manual, self.enemy)
                self.seconds(1.5)
                def apart():
                    return ((float(self.enemy.x) - float(self.player.x)) ** 2
                            + (float(self.enemy.y) - float(self.player.y)) ** 2
                            + (float(self.enemy.z) - float(self.player.z)) ** 2) ** .5
                before = apart()
                moved = self.fly(2.0)
                self.assertLess(apart(), before - moved.length() * .95, "almost all of it spent closing")
                self.game.input("q")

    def test_unlocking_in_flight_flies_on_where_the_camera_was_left(self):
        self.airborne("GREEN", height=200.0, distance=1000.0)
        self.game.input("q")
        self.seconds(1.0)
        self.game.input("q")
        aim = self.aim_vector()
        moved = self.fly(1.0)
        self.assertLess(angle_between(moved, aim), 1.0)

    def test_f_takes_off_and_lands_back_into_ground_movement(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.begin(character_id, enemy="RED", distance=3000.0)
                self.rig = self.game.camera
                self.game.input("f")
                self.assertTrue(self.player.flight.is_flying)
                self.aim(0.0, -30.0)
                self.fly(1.5)
                self.assertGreater(float(self.player.y) - self.game.world.height_at(self.player.x, self.player.z), 3.0)
                self.game.input("f")
                for _ in range(1200):
                    self.game.update(FRAME)
                    if not self.player.flight.is_flying:
                        break
                self.assertFalse(self.player.flight.is_flying)
                self.assertTrue(self.on_ground(self.player))
                self.aim(0.0, 10.0)
                moved = self.fly(1.0)
                self.assertGreater(moved.length(), .6, "walks")
                self.assertTrue(self.on_ground(self.player))

    def test_soldier_boy_stays_on_the_ground_whatever_the_aim(self):
        self.begin("RED", enemy="BLACK", distance=3000.0)
        self.rig = self.game.camera
        self.aim(0.0, -89.0)
        self.fly(1.0, "w", "shift", "space")
        self.assertFalse(self.player.flight.is_flying)
        self.assertFalse(self.player.flight_allowed)
        self.assertLess(float(self.player.y) - self.game.world.height_at(self.player.x, self.player.z), 3.0)

    def test_ai_flight_is_left_as_it_was(self):
        self.begin("WHITE", enemy="BLACK", distance=400.0)
        flight = self.enemy.flight
        with unittest.mock.patch.object(flight, "step", wraps=flight.step) as step:
            self.seconds(3.0)
        for call in step.call_args_list:
            self.assertFalse(call.kwargs.get("aimed", False))


if __name__ == "__main__":
    unittest.main()
