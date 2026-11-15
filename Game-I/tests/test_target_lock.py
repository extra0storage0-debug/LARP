"""The player's manual target lock: Q, the mouse wheel, the camera, the indicator and attacks."""

from __future__ import annotations

from math import acos, degrees
import unittest
from unittest import mock

from ursina import camera, held_keys

from characters.civilian import Civilian
from characters.roster import ROSTER_IDS
from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM
from game_fixture import FRAME
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers.aiming import center_of
from powers.common import LaunchedMotion
from powers.vitals import PHYSICAL
from test_gameplay_control_update import LiveCase

FLYERS = ("WHITE", "BLACK", "YELLOW", "GREEN")


class LockCase(LiveCase):
    def begin(self, *args, **kwargs):
        game = super().begin(*args, **kwargs)
        self.targets = self.combat.targets
        return game

    def add_enemy(self, character_id: str, x: float, z: float):
        self.teams.state.assignment[character_id] = ENEMY_TEAM
        self.teams._apply_roster()
        character = self.teams.characters[character_id]
        self.stand(character, x, z)
        character.powers.hard_reset()
        return character

    def view_error(self, target=None) -> float:
        """Degrees between the middle of the screen and the target."""
        target = target if target is not None else self.targets.manual
        point = self.targets.point_of(target)
        eye, ahead = camera.world_position, camera.forward
        offset = SimVec3(point.x - eye.x, point.y - eye.y, point.z - eye.z).normalized()
        return degrees(acos(max(-1.0, min(1.0, offset.x * ahead.x + offset.y * ahead.y + offset.z * ahead.z))))

    def settle(self, seconds: float = 2.0) -> None:
        self.seconds(seconds)


class ControlTests(LockCase):
    def test_q_turns_it_on_and_off_and_no_longer_dashes(self):
        self.begin("WHITE")
        self.game.input("q")
        self.game.input("q up")
        self.assertIs(self.targets.manual, self.enemy)
        self.assertIsNone(self.player.motion, "no dash")
        self.game.input("q")
        self.assertIsNone(self.targets.manual)

    def test_it_never_replaces_a_chosen_target_with_a_nearer_one(self):
        self.begin("WHITE", distance=800.0)
        self.game.input("q")
        chosen = self.targets.manual
        near = self.add_enemy("GREEN", 5.0, 5.0)
        self.frames(30)
        self.assertIs(self.targets.manual, chosen)
        self.assertIsNot(near, chosen)
        self.assertIs(self.combat.shown_target, chosen)

    def test_wheel_cycles_both_ways_and_wraps_without_unlocking(self):
        self.begin("WHITE", distance=50.0)
        self.add_enemy("GREEN", 50.0, 0.0)
        self.add_enemy("BLACK", -50.0, 0.0)
        self.game.input("q")
        seen = [self.targets.manual]
        for _ in range(3):
            self.game.input("scroll up")
            seen.append(self.targets.manual)
        self.assertEqual(len({*seen[:3]}), 3, "reaches each one")
        self.assertIs(seen[3], seen[0], "and wraps round")
        for _ in range(3):
            self.game.input("scroll down")
        self.assertIs(self.targets.manual, seen[0])
        self.game.input("scroll up")
        self.game.input("scroll down")
        self.assertIs(self.targets.manual, seen[0], "down undoes up")

    def test_wheel_zooms_only_while_unlocked(self):
        self.begin("WHITE")
        rig = self.game.camera
        before = rig.zoom
        self.game.input("scroll down")
        self.assertGreater(rig.zoom, before)
        zoom = rig.zoom
        self.game.input("q")
        self.game.input("scroll down")
        self.assertEqual(rig.zoom, zoom)
        self.game.input("q")
        self.game.input("scroll up")
        self.assertLess(rig.zoom, zoom)

    def test_nothing_to_lock(self):
        self.begin("WHITE")
        self.teams.state.assignment[self.enemy.character_id] = AVAILABLE
        self.teams._apply_roster()
        with mock.patch.object(self.game.world, "civilians", []):
            self.game.input("q")
        self.assertIsNone(self.targets.manual)
        self.assertEqual(self.game._notification, "NO TARGET TO LOCK")

    def test_a_menu_or_pause_blocks_the_keys(self):
        self.begin("WHITE")
        self.game.input("escape")
        self.game.input("q")
        self.assertIsNone(self.targets.manual)
        self.game.input("escape")


class TargetChoiceTests(LockCase):
    def test_only_enemies_can_be_locked_never_allies_civilians_or_the_player(self):
        self.begin("WHITE")
        ally = self.teams.characters["GREEN"]
        self.teams.state.assignment["GREEN"] = MY_TEAM
        self.teams._apply_roster()
        self.stand(ally, 20.0, 0.0)
        civilian = Civilian(self.game, (15.0, 0.0, 15.0), 991)
        self.game.world.civilians.append(civilian)
        self.addCleanup(self.game.world.civilians.remove, civilian)
        self.targets.clear()
        options = self.targets.candidates()
        self.assertIn(self.enemy, options)
        self.assertNotIn(ally, options)
        self.assertNotIn(civilian, options)
        self.assertNotIn(self.player, options)

    def test_with_no_enemy_q_locks_nothing_even_beside_an_ally(self):
        self.begin("WHITE")
        ally = self.teams.characters["GREEN"]
        self.teams.state.assignment["GREEN"] = MY_TEAM
        self.teams.state.assignment[self.enemy.character_id] = AVAILABLE
        self.teams._apply_roster()
        self.stand(ally, 5.0, 5.0)
        self.targets.clear()
        self.game.input("q")
        self.assertIsNone(self.targets.manual)

    def test_the_list_is_cached_not_searched_every_frame(self):
        self.begin("WHITE")
        self.game.input("q")
        self.targets.clear()
        with mock.patch.object(self.targets, "_build_candidates", wraps=self.targets._build_candidates) as build:
            for _ in range(60):
                self.game.update(FRAME)
                self.targets.candidates()
        self.assertLessEqual(build.call_count, 3, "about once a second, for a second of frames")

    def test_the_list_refreshes_at_once_when_the_roster_changes(self):
        self.begin("WHITE")
        self.assertNotIn(self.teams.characters["GREEN"], self.targets.candidates())
        added = self.add_enemy("GREEN", 30.0, 30.0)
        self.assertIn(added, self.targets.candidates())
        self.teams.state.assignment["GREEN"] = AVAILABLE
        self.teams._apply_roster()
        self.assertNotIn(added, self.targets.candidates())


class CameraTests(LockCase):
    def test_turns_smoothly_to_a_target_behind_the_camera(self):
        self.begin("WHITE", distance=-200.0)
        self.enemy.vitals.add_status("frozen", 60.0)
        rig = self.game.camera
        rig.yaw = 0.0
        self.frames(2)
        self.assertGreater(self.view_error(self.enemy), 90.0, "starts out of view")
        self.game.input("q")
        previous_yaw, previous_pitch, largest = rig.yaw, rig.pitch, 0.0
        for _ in range(180):
            self.game.update(FRAME)
            turn = abs((rig.yaw - previous_yaw + 180.0) % 360.0 - 180.0)
            largest = max(largest, turn, abs(rig.pitch - previous_pitch))
            previous_yaw, previous_pitch = rig.yaw, rig.pitch
        self.assertLessEqual(largest, 300.0 * FRAME + 1e-6, "never snaps")
        self.assertGreater(largest, 1.0)
        self.assertLess(self.view_error(), 4.0, "ends up in the middle of the screen")

    def test_near_and_very_distant_targets(self):
        for distance in (12.0, 3000.0):
            with self.subTest(distance):
                self.begin("WHITE", distance=distance)
                self.game.camera.yaw = 120.0
                self.game.input("q")
                self.settle()
                self.assertLess(self.view_error(), 8.0)

    def test_close_targets_pull_the_camera_back_to_fit_both(self):
        self.begin("WHITE", distance=6.0)
        self.enemy.vitals.add_status("frozen", 60.0)
        rig = self.game.camera
        self.seconds(1.0)
        apart = rig.distance
        self.game.input("q")
        self.settle()
        self.assertGreater(rig.distance, apart + 2.0)
        self.game.input("q")
        self.settle()
        self.assertAlmostEqual(rig.distance, apart, delta=.5)

    def test_tracks_a_flying_target_and_one_thrown_through_the_air(self):
        self.begin("BLACK", enemy="WHITE", distance=200.0)
        self.tough(self.enemy)
        self.game.input("q")
        self.settle()
        self.enemy.vitals.add_status("frozen", 3.0)
        self.enemy.flight.phase = FlightPhase.CRUISE
        self.enemy.position = (self.enemy.x, 180.0, self.enemy.z)
        self.settle()
        self.assertLess(self.view_error(), 8.0, "up in the sky")
        worst = 0.0
        self.enemy.motion = LaunchedMotion(None, self.enemy, SimVec3(60.0, 20.0, 0.0))
        for _ in range(120):
            self.game.update(FRAME)
            worst = max(worst, self.view_error())
        self.assertLess(worst, 15.0, "kept on it through the throw")

    def test_mouse_is_ignored_while_locked_and_works_again_straight_after(self):
        self.begin("WHITE")
        self.enemy.vitals.add_status("frozen", 60.0)
        rig = self.game.camera
        with mock.patch("game.camera_manager.mouse") as fake:
            fake.locked = True
            fake.velocity = (.05, 0.0)
            self.game.input("q")
            self.settle(1.5)
            locked_yaw = rig.yaw
            self.frames(20)
            self.assertAlmostEqual(rig.yaw, locked_yaw, delta=1.0, msg="the mouse does not fight the lock")
            self.game.input("q")
            self.frames(2)
            self.assertGreater(abs(rig.yaw - locked_yaw), 1.0, "free camera again")

    def test_unlocking_changes_only_the_camera_mode(self):
        self.begin("WHITE")
        self.game.input("f")
        self.seconds(1.0)
        self.game.input("q")
        self.settle(1.0)
        before = (float(self.player.x), float(self.player.y), float(self.player.z))
        phase, velocity = self.player.flight.phase, self.player.flight.velocity
        yaw, pitch = self.game.camera.yaw, self.game.camera.pitch
        self.game.input("q")
        self.assertEqual(before, (float(self.player.x), float(self.player.y), float(self.player.z)))
        self.assertIs(self.player.flight.phase, phase)
        self.assertIs(self.player.flight.velocity, velocity)
        self.assertEqual((yaw, pitch), (self.game.camera.yaw, self.game.camera.pitch), "no jump")
        self.frames(30)
        self.assertAlmostEqual(self.game.camera.yaw, yaw, delta=.01, msg="and it stays where it was left")

    def test_wasd_still_moves_and_the_character_faces_the_target(self):
        self.begin("GREEN", distance=-100.0)
        self.game.input("q")
        self.settle()
        start = float(self.player.z)
        held_keys["w"] = 1
        self.seconds(1.0)
        held_keys["w"] = 0
        self.assertLess(float(self.player.z), start - 1.0, "W walks toward the target behind the start")

    def test_camera_reset_does_not_break_a_lock(self):
        self.begin("WHITE", distance=-100.0)
        self.game.input("q")
        self.settle()
        self.game.input("c")
        self.settle()
        self.assertIsNotNone(self.targets.manual)
        self.assertLess(self.view_error(), 4.0)


class IndicatorTests(LockCase):
    def test_reticle_follows_the_target_and_hides_on_release(self):
        self.begin("WHITE", distance=40.0)
        reticle = self.combat.lock_reticle
        self.assertFalse(reticle.showing)
        self.game.input("q")
        self.assertTrue(reticle.showing)
        self.frames(1)
        self.enemy.position = (30.0, self.enemy.y, 30.0)
        self.frames(1)
        point = center_of(self.enemy)
        self.assertLess((SimVec3(*reticle.root.position) - point).length(), 2.5)
        self.game.input("q")
        self.assertFalse(reticle.showing)

    def test_name_and_health_show_and_only_the_locked_enemy_is_marked(self):
        self.begin("WHITE", distance=50.0)
        green = self.add_enemy("GREEN", 20.0, 20.0)
        self.frames(2)
        self.game.input("q")
        self.game.input("scroll up")
        locked = self.targets.manual
        self.frames(1)
        tags = self.teams.tags
        self.assertTrue(tags[locked.character_id].targeted)
        other = green if locked is self.enemy else self.enemy
        self.assertFalse(tags[other.character_id].targeted)
        line = self.game.hud._target_line(self.player)
        self.assertIn(f"LOCKED: {locked.display_name}", line)
        self.assertIn("HP", line)
        self.game.input("q")
        self.assertNotIn("LOCKED", self.game.hud._target_line(self.player))


class ReleaseTests(LockCase):
    def test_death_releases_and_abilities_fall_back_to_the_nearest_enemy(self):
        self.begin("WHITE", distance=50.0)
        other = self.add_enemy("GREEN", 80.0, 0.0)
        self.game.input("q")
        while self.targets.manual is not self.enemy:
            self.game.input("scroll up")
        self.combat.hit_character(None, self.enemy, 1e9, PHYSICAL)
        self.frames(1)
        self.assertIsNone(self.targets.manual)
        self.assertFalse(self.combat.lock_reticle.showing)
        self.assertEqual(self.game._notification, "TARGET LOST")
        self.assertIs(self.player.powers.abilities["heat_vision"].target(), other)
        self.assertFalse(self.game.camera.tracking and self.targets.locked_point() is not None)

    def test_despawning_releases(self):
        self.begin("WHITE")
        self.game.input("q")
        self.teams.state.assignment[self.enemy.character_id] = AVAILABLE
        self.teams._apply_roster()
        self.frames(1)
        self.assertIsNone(self.targets.manual)

    def test_a_team_change_releases_the_lock_and_stops_attacks_on_them(self):
        self.begin("WHITE")
        self.game.input("q")
        self.teams.state.assignment[self.enemy.character_id] = MY_TEAM
        self.teams._apply_roster()
        self.frames(1)
        self.assertIsNone(self.targets.manual)
        self.assertIsNone(self.player.powers.abilities["heat_vision"].target())

    def test_switching_character_keeps_the_lock_unless_it_is_now_yourself(self):
        self.begin("WHITE")
        self.game.input("q")
        self.teams.state.assignment["GREEN"] = MY_TEAM
        self.teams.swap("GREEN", save=False)
        self.frames(1)
        self.assertIs(self.targets.manual, self.enemy, "still valid from the new body")
        self.assertIs(self.game.sentry.powers.abilities["melee"].target(), self.enemy)
        self.teams.swap(self.enemy.character_id, save=False)
        self.assertIsNone(self.targets.manual, "never the player's own character")
        self.frames(2)

    def test_leaving_the_screen_does_not_lose_it(self):
        self.begin("WHITE", distance=30.0)
        self.game.input("q")
        self.settle(.5)
        self.enemy.position = (2000.0, self.enemy.y, -2000.0)
        self.frames(1)
        self.assertIs(self.targets.manual, self.enemy)


class AttackTests(LockCase):
    def far_and_near(self, player: str):
        self.begin(player, enemy="BLACK" if player != "BLACK" else "WHITE", distance=300.0)
        self.far = self.enemy
        near_id = next(c for c in ROSTER_IDS if c not in (player, self.far.character_id, "RED"))
        self.near = self.add_enemy(near_id, 10.0, 10.0)
        self.tough(self.far)
        self.tough(self.near)
        self.frames(1)
        self.targets.clear()
        self.game.input("q")
        while self.targets.manual is not self.far:
            self.game.input("scroll up")

    def test_every_characters_targeted_abilities_go_for_the_locked_enemy_not_the_nearest(self):
        table = {"WHITE": ("heat_vision", "high_speed_attack", "time_stop", "ground_execution", "melee"),
                 "BLACK": ("laser_vision", "high_speed_attack", "time_stop", "neck_laser_execution", "melee"),
                 "YELLOW": ("chest_beam", "high_speed_attack", "time_stop", "melee"),
                 "GREEN": ("flight_charge", "high_speed_attack", "time_stop", "shockwave_punch", "melee")}
        for player, abilities in table.items():
            with self.subTest(player):
                self.far_and_near(player)
                for name in abilities:
                    self.assertIs(self.player.powers.abilities[name].target(300.0 + 50.0), self.far, name)
                self.assertIs(self.player.powers.abilities[abilities[0]].aim()[2], self.far)

    def test_soldier_boys_bombs_go_for_the_locked_enemy(self):
        self.begin("RED", enemy="BLACK", distance=60.0)
        near = self.add_enemy("GREEN", 8.0, 8.0)
        self.tough(self.enemy)
        self.tough(near)
        self.frames(1)
        self.game.input("q")
        while self.targets.manual is not self.enemy:
            self.game.input("scroll up")
        self.tap("1")
        for _ in range(300):
            self.game.update(FRAME)
            if self.enemy.vitals.damage_taken > 0.0:
                break
        self.tap("1")
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)

    def test_the_real_beam_hits_the_locked_enemy(self):
        self.far_and_near("WHITE")
        self.settle()
        self.tap("1")
        self.seconds(.5)
        self.tap("1")
        self.assertGreater(self.far.vitals.damage_taken, 0.0)
        self.assertEqual(self.near.vitals.damage_taken, 0.0)

    def test_the_real_punch_on_2_hits_the_locked_enemy(self):
        self.far_and_near("GREEN")
        self.tap("2")
        for _ in range(60):
            self.game.update(FRAME)
            if self.far.vitals.damage_taken > 0.0:
                break
        self.assertGreater(self.far.vitals.damage_taken, 0.0)
        self.assertEqual(self.near.vitals.damage_taken, 0.0)

    def test_area_attacks_stay_centred_on_the_character(self):
        self.begin("YELLOW", distance=100.0)
        self.tough(self.enemy)
        self.game.input("q")
        with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
            self.ability("massive_blast").press() if hasattr(self, "ability") else self.player.powers.abilities["massive_blast"].press()
        origin = blast.call_args.args[1]
        here = center_of(self.player)
        self.assertLess(abs(origin.x - here.x) + abs(origin.z - here.z), 2.0)

    def test_an_ally_in_the_way_of_the_lock_is_never_attacked(self):
        self.begin("WHITE", distance=50.0)
        ally = self.teams.characters["GREEN"]
        self.teams.state.assignment["GREEN"] = MY_TEAM
        self.teams._apply_roster()
        self.stand(ally, 5.0, 5.0)
        self.tough(self.enemy)
        self.game.input("q")
        self.game.input("scroll up")
        self.assertIs(self.targets.manual, self.enemy)
        self.assertIs(self.player.powers.abilities["heat_vision"].target(), self.enemy)
        self.tap("1")
        self.seconds(.3)
        self.tap("1")
        self.assertEqual(ally.vitals.damage_taken, 0.0)

    def test_a_locked_enemy_out_of_range_is_not_swapped_for_someone_nearer(self):
        self.far_and_near("WHITE")
        ability = self.player.powers.abilities["melee"]
        self.combat.settings.set("WHITE", "melee", "range", 100)
        self.assertIsNone(ability.target())
        self.tap("=")
        self.assertEqual(self.near.vitals.damage_taken, 0.0)

    def test_ai_ignores_the_players_lock(self):
        self.begin("WHITE", distance=50.0)
        self.game.input("q")
        self.assertIs(self.targets.lock_of(self.enemy), self.player)


class TimeAndSequenceTests(LockCase):
    def test_camera_keeps_tracking_during_the_t_stop(self):
        self.begin("BLACK", enemy="WHITE", distance=120.0)
        self.game.input("q")
        self.tap("t")
        rig = self.game.camera
        rig.yaw += 90.0
        self.settle()
        self.assertTrue(self.combat.world_stopped)
        self.assertLess(self.view_error(), 6.0)
        held_keys["w"] = 1
        self.seconds(1.0)
        held_keys["w"] = 0
        self.assertLess(self.view_error(), 6.0, "while the player moves round a frozen target")

    def test_all_the_scripted_attacks_finish_cleanly_with_a_lock_on(self):
        for player, key in (("WHITE", "2"), ("BLACK", "3"), ("YELLOW", "3"), ("GREEN", "2"), ("WHITE", "4"),
                            ("BLACK", "4")):
            with self.subTest(f"{player} {key}"):
                self.begin(player, enemy="RED", distance=80.0)
                self.tough(self.enemy)
                self.game.input("q")
                self.settle(.5)
                self.tap(key)
                self.assertIsNotNone(self.player.motion)
                for _ in range(900):
                    self.game.update(FRAME)
                    if self.player.motion is None:
                        break
                self.assertIsNone(self.player.motion)
                self.assertFalse(self.combat.time_stopped)
                self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
                self.assertIs(self.targets.manual, self.enemy, "still locked afterwards")
                self.settle(.5)

    def test_a_fatal_attack_releases_and_time_still_resumes(self):
        self.begin("GREEN", enemy="RED", distance=40.0)
        self.combat.settings.set("GREEN", "time_stop", "damage", 20000)
        self.game.input("q")
        self.tap("3")
        for _ in range(600):
            self.game.update(FRAME)
            if self.player.motion is None:
                break
        self.frames(2)
        self.assertTrue(self.enemy.vitals.downed)
        self.assertIsNone(self.targets.manual)
        self.assertFalse(self.combat.time_stopped)

    def test_five_characters_lock_track_and_release(self):
        for player in ROSTER_IDS:
            with self.subTest(player):
                self.begin(player, enemy="BLACK" if player != "BLACK" else "RED", distance=-60.0)
                self.game.input("q")
                self.settle()
                self.assertLess(self.view_error(), 5.0)
                self.game.input("q")
                self.assertFalse(self.combat.lock_reticle.showing)
                self.assertEqual(self.player.flight.is_flying, False)


if __name__ == "__main__":
    unittest.main()
