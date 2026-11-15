"""Bars that shrink with distance, none over the player, and the player low on the screen."""

from __future__ import annotations

import unittest

from panda3d.core import LPoint3f
from ursina import Vec3, camera, held_keys, scene

from characters.roster import ROSTER_IDS
from config.character_roster import MY_TEAM
from game.camera_manager import BODY_MIDDLE, FRAME_LOWEST_FEET, FRAME_POSITION, GROUND_CLEARANCE, screen_half_height
from game.world_raycast import world_raycast
from game_fixture import FRAME
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from test_gameplay_control_update import FLYERS, LiveCase
from ui.enemy_team_ui import (BAR_WIDTH, FADE_END, FADE_START, FAR_METRES, FAR_RATIO, MAX_SCALE, MIN_SCALE, NEAR_METRES,
                              NEAR_RATIO, TEXT_FADE_END, TEXT_FADE_START, apparent_ratio)
from ui.hud import SLOT_POSITIONS


def screen_share(point) -> float:
    """How far down the screen a world point is: 0 at the top edge, 1 at the bottom."""
    relative = camera.getRelativePoint(scene, LPoint3f(float(point[0]), float(point[1]), float(point[2])))
    return .5 - .5 * (relative.y / relative.z) / screen_half_height()


class BarCase(LiveCase):
    def setUp(self):
        self.begin("WHITE", "BLACK")
        self.tag = self.teams.tags["BLACK"]
        self.vitals = self.enemy.vitals
        self.tag.set_targeted(False)


class ScaleTests(BarCase):
    def test_it_only_ever_gets_smaller_and_has_no_steps(self):
        previous = apparent_ratio(1.0)
        for tenth in range(11, 40000):
            now = apparent_ratio(tenth / 10.0)
            self.assertLessEqual(now, previous + 1e-12)
            self.assertLess(previous - now, previous * .002, f"a jump at {tenth / 10.0} m")
            previous = now

    def test_the_size_on_screen_at_each_range(self):
        self.assertEqual(apparent_ratio(10.0), NEAR_RATIO)
        self.assertEqual(apparent_ratio(NEAR_METRES), NEAR_RATIO)
        self.assertLess(apparent_ratio(150.0), NEAR_RATIO * .7, "medium is visibly smaller")
        self.assertGreater(apparent_ratio(150.0), FAR_RATIO * 1.5, "and still on its way down")
        self.assertAlmostEqual(apparent_ratio(FAR_METRES), FAR_RATIO)
        self.assertEqual(apparent_ratio(FAR_METRES * 3.0), FAR_RATIO)

    def test_coming_close_never_makes_it_look_bigger(self):
        looks = []
        for distance in (30.0, 20.0, 12.0, 8.0):
            self.tag.update(distance, self.vitals)
            looks.append(self.tag.root.getScale().x / distance)
        self.assertLess(max(looks) - min(looks), NEAR_RATIO * .02, looks)

    def test_the_limits_hold_at_the_very_near_and_the_very_far(self):
        self.tag.update(.5, self.vitals)
        self.assertEqual(self.tag._scale, MIN_SCALE)
        self.tag.set_targeted(True)  # fades never hide this one
        self.tag.update(50000.0, self.vitals)
        self.assertLessEqual(self.tag._scale, MAX_SCALE * 1.35 + 1e-6)
        self.tag.set_targeted(False)

    def test_it_changes_smoothly_frame_to_frame_on_the_real_node(self):
        last = None
        metres = 31.0
        while metres < 2000.0:  # two per cent further each frame is a very fast retreat
            self.tag.update(metres, self.vitals)
            looks = self.tag.root.getScale().x / metres
            if last is not None:
                self.assertLess(abs(looks - last), last * .03, metres)
            last = looks
            metres *= 1.02

    def test_a_real_character_moving_away_shrinks_on_screen(self):
        looks = []
        for distance in (40.0, 200.0, 800.0):
            self.stand(self.enemy, 0.0, distance)
            self.frames(1)
            eye, body = camera.world_position, self.enemy.world_position
            looks.append(self.tag.root.getScale().x / (body - eye).length())
        self.assertGreater(looks[0], looks[1])
        self.assertGreater(looks[1], looks[2])


class FadeTests(BarCase):
    def test_it_fades_smoothly_then_is_gone_then_comes_back(self):
        self.tag.update(100.0, self.vitals)
        self.assertEqual(self.tag._shown_alpha, 1.0)
        self.assertFalse(self.tag.root.isHidden())
        last = 1.0
        for metre in range(int(FADE_START), int(FADE_END), 10):
            self.tag.update(float(metre), self.vitals)
            self.assertLessEqual(self.tag._shown_alpha, last)
            self.assertLess(last - self.tag._shown_alpha, .04, metre)
            last = self.tag._shown_alpha
        self.tag.update(FADE_END + 1.0, self.vitals)
        self.assertEqual(self.tag._shown_alpha, 0.0)
        self.assertTrue(self.tag.root.isHidden(), "nothing left to draw")
        self.tag.update(100.0, self.vitals)
        self.assertEqual(self.tag._shown_alpha, 1.0)
        self.assertFalse(self.tag.root.isHidden())

    def test_the_words_go_before_the_bar_does(self):
        self.tag.update(TEXT_FADE_START - 1.0, self.vitals)
        self.assertEqual(self.tag._text_alpha, 1.0)
        self.tag.update(TEXT_FADE_END + 1.0, self.vitals)
        self.assertEqual(self.tag._text_alpha, 0.0)
        self.assertEqual(self.tag._shown_alpha, 1.0)
        self.tag.update(10.0, self.vitals)
        self.assertEqual(self.tag._text_alpha, 1.0)

    def test_the_target_stays_readable_however_far_away(self):
        self.tag.set_targeted(True)
        self.tag.update(FADE_END * 2.0, self.vitals)
        self.assertEqual(self.tag._shown_alpha, 1.0)
        self.assertEqual(self.tag._text_alpha, 1.0)
        self.assertFalse(self.tag.root.isHidden())
        self.tag.set_targeted(False)
        self.tag.update(FADE_END * 2.0, self.vitals)
        self.assertTrue(self.tag.root.isHidden())
        self.tag.update(10.0, self.vitals)


class ContentTests(BarCase):
    def test_it_faces_the_camera(self):
        self.assertTrue(self.tag.root.hasBillboard())

    def test_the_percentage_follows_health(self):
        self.tag.update(10.0, self.vitals)
        self.assertEqual(self.tag.percent.text, "100%")
        self.vitals.regen = 0.0
        self.vitals.health = self.vitals.max_health * .425
        self.tag.update(10.0, self.vitals)
        self.assertEqual(self.tag.percent.text, "43%")
        self.assertAlmostEqual(self.tag.fill.scale_x, BAR_WIDTH * .425, places=3)
        self.vitals.health = self.vitals.max_health
        self.tag.update(10.0, self.vitals)

    def test_the_name_is_the_characters(self):
        self.assertEqual(self.tag.label.text, self.enemy.display_name)


class PlayerTests(LiveCase):
    def setUp(self):
        self.begin("WHITE", "BLACK")

    def everyone_else_shows(self):
        for character_id in ROSTER_IDS:
            character = self.teams.characters[character_id]
            tag = self.teams.tags[character_id]
            if character is self.game.sentry:
                self.assertTrue(tag.root.isHidden(), character_id)
            elif not character.parked:
                self.assertFalse(tag.root.isHidden(), character_id)

    def test_in_every_body_the_player_has_none_and_everyone_else_does(self):
        for character_id in ROSTER_IDS:
            self.teams.state.assignment[character_id] = MY_TEAM
        self.teams._apply_roster()
        for character_id in ROSTER_IDS:
            self.teams.swap(character_id, save=False)
            self.frames(2)
            self.assertIs(self.game.sentry, self.teams.characters[character_id])
            self.everyone_else_shows()

    def test_stays_hidden_through_damage_targets_and_distance(self):
        tag = self.teams.tags["WHITE"]
        self.player.vitals.health *= .5
        tag.set_targeted(True)
        for distance in (5.0, 500.0, 5000.0):
            tag.update(distance, self.player.vitals)
            self.assertTrue(tag.root.isHidden())
        tag.set_targeted(False)

    def test_the_old_body_gets_its_bar_back_and_shows_current_health(self):
        white = self.teams.characters["WHITE"]
        self.teams.state.assignment["GREEN"] = MY_TEAM
        self.teams._apply_roster()
        white.vitals.regen = 0.0
        white.vitals.health = white.vitals.max_health * .3
        self.frames(2)
        self.teams.swap("GREEN", save=False)
        self.frames(2)
        tag = self.teams.tags["WHITE"]
        self.assertFalse(tag.root.isHidden())
        self.assertAlmostEqual(tag.fraction, .3, delta=.02)
        self.assertEqual(tag.percent.text, "30%")
        white.powers.apply_passives()

    def test_allies_enemies_and_omni_mans_squad_show_theirs(self):
        self.teams.state.assignment["GREEN"] = MY_TEAM
        self.teams._apply_roster()
        self.frames(1)
        self.assertFalse(self.teams.tags["GREEN"].root.isHidden())
        self.assertFalse(self.teams.tags["BLACK"].root.isHidden())
        squad = self.teams.deploy_squad(self.teams.characters["GREEN"])
        self.teams._apply_roster()
        self.frames(1)
        for member in squad:
            self.assertFalse(self.teams.tag_of(member).root.isHidden())
        self.teams.withdraw_squad(list(squad))

    def test_the_hud_still_shows_the_players_health_both_ways(self):
        vitals, hud = self.player.vitals, self.game.hud
        vitals.regen = 0.0
        vitals.health = vitals.max_health * .4
        self.frames(1)
        hud.update()
        self.assertAlmostEqual(hud.health_bar._shown, .4, delta=.01)
        vitals.heal(vitals.max_health * .35)
        self.frames(1)
        hud.update()
        self.assertAlmostEqual(hud.health_bar._shown, .75, delta=.01)
        self.player.powers.apply_passives()

    def test_real_damage_reaches_the_hud_with_no_bar_over_the_head(self):
        self.tough(self.player, 1000.0)
        self.game.combat.hit_character(self.enemy, self.player, 250.0, "physical")
        self.frames(1)
        self.game.hud.update()
        self.assertLess(self.game.hud.health_bar._shown, 1.0)
        self.assertTrue(self.teams.tags["WHITE"].root.isHidden())


class FramingCase(LiveCase):
    def setUp(self):
        self.begin("WHITE", "BLACK", 200.0)
        self.tough(self.player)
        self.rig = self.game.camera
        self.rig.pitch = 10.0
        self.rig.zoom = 0.0
        self.addCleanup(self._restore_rig)

    def _restore_rig(self):
        self.rig.frame_position = FRAME_POSITION
        self.rig.zoom = 0.0
        self.rig.pitch = 10.0
        self.rig.distance = self.rig.DEFAULT_DISTANCE

    def body_share(self) -> float:
        return screen_share((self.player.x, self.player.y + BODY_MIDDLE, self.player.z))

    def feet_share(self) -> float:
        return screen_share((self.player.x, self.player.y - .25, self.player.z))

    def settle(self, seconds: float = 2.0) -> None:
        self.frames(round(seconds / FRAME))


class FramingTests(FramingCase):
    def test_at_every_pitch(self):
        for pitch in (-5.0, 0.0, 10.0, 30.0, 60.0, 85.0, 89.0):
            self.rig.pitch = pitch
            self.settle(.3)
            self.assertAlmostEqual(self.body_share(), FRAME_POSITION, delta=.012, msg=pitch)

    def test_at_every_zoom_the_feet_stay_on_screen(self):
        for zoom in (-5.5, -3.0, 0.0, 5.0, 20.5):
            self.rig.zoom = zoom
            self.settle(2.5)
            self.assertLess(self.feet_share(), FRAME_LOWEST_FEET + .015, zoom)
            self.assertGreaterEqual(self.body_share(), .5 - .001, zoom)
            if zoom >= 0.0:
                self.assertAlmostEqual(self.body_share(), FRAME_POSITION, delta=.012, msg=zoom)

    def test_the_body_lies_in_the_lower_part_with_room_for_the_world_above(self):
        self.settle(1.0)
        head = screen_share((self.player.x, self.player.y + 2.85, self.player.z))
        self.assertGreater(head, .55, "the head is clear of the crosshair")
        self.assertLess(self.feet_share(), .95, "room under the feet")
        self.assertTrue(.65 <= self.body_share() <= .80)

    def test_running_jumping_flying_and_hovering(self):
        held_keys["w"] = held_keys["shift"] = 1
        self.settle(1.5)
        self.assertAlmostEqual(self.body_share(), FRAME_POSITION, delta=.02, msg="running")
        held_keys["w"] = held_keys["shift"] = 0
        self.settle(.5)
        self.game.input("space")
        self.game.input("space up")
        self.frames(12)
        self.assertAlmostEqual(self.body_share(), FRAME_POSITION, delta=.02, msg="jumping")
        self.settle(1.5)
        self.player.flight.phase = FlightPhase.CRUISE
        self.player.position = (self.player.x, self.player.y + 80.0, self.player.z)
        self.settle(1.0)
        self.assertAlmostEqual(self.body_share(), FRAME_POSITION, delta=.02, msg="hovering")
        held_keys["w"] = held_keys["shift"] = 1
        self.settle(2.0)
        self.assertGreater(self.player.flight.speed_mps, 50.0)
        self.assertAlmostEqual(self.body_share(), FRAME_POSITION, delta=.03, msg="fast flight")
        held_keys["w"] = held_keys["shift"] = 0

    def test_each_of_the_five_after_a_big_move_and_an_impact(self):
        for character_id in (*FLYERS, "RED"):
            self.begin(character_id, "BLACK" if character_id != "BLACK" else "WHITE", 200.0)
            self.tough(self.player)
            self.rig.pitch = 10.0
            self.settle(.5)
            self.game.toggle_flight()
            self.settle(1.5)
            airborne = self.body_share()
            self.assertAlmostEqual(airborne, FRAME_POSITION, delta=.03, msg=character_id)
            self.game.toggle_flight()
            motion = self.player.motion
            self.assertIsNotNone(motion, character_id)
            for _ in range(round(40.0 / FRAME)):
                if self.player.motion is not motion:
                    break
                self.game.update(FRAME)
                if motion.impacted:
                    self.assertTrue(0.0 < self.feet_share() < 1.0, f"{character_id} on screen at impact")
            self.settle(1.5)
            self.assertAlmostEqual(self.body_share(), FRAME_POSITION, delta=.02, msg=character_id)

    def test_following_the_camera_leaves_the_world_position_alone(self):
        self.settle(.5)
        here = (float(self.player.x), float(self.player.y), float(self.player.z))
        floor = self.game.world.height_at(here[0], here[2])
        self.assertAlmostEqual(here[1], floor + .25, places=2)
        self.settle(1.0)
        self.assertEqual((float(self.player.x), float(self.player.z)), (here[0], here[2]))
        self.assertAlmostEqual(float(self.player.y), here[1], places=3)

    def test_the_crosshair_is_still_the_way_the_camera_faces(self):
        for pitch in (-20.0, 10.0, 45.0):
            self.rig.pitch = pitch
            self.settle(.2)
            ahead = self.rig.aim_direction(SimVec3(self.player.x, self.player.y, self.player.z))
            real = camera.forward
            self.assertAlmostEqual(ahead.x * real.x + ahead.y * real.y + ahead.z * real.z, 1.0, places=4)
            eye = camera.world_position
            to_focus = self.rig.aim_target - eye
            self.assertGreater(to_focus.normalized().dot(real), .9999)

    def test_turning_goes_all_the_way_round_without_a_jump(self):
        self.settle(.5)
        last = camera.world_position
        for _ in range(240):
            self.rig.yaw += 3.0
            self.rig.pivot.rotation_y = self.rig.yaw
            self.frames(1)
            self.assertLess((camera.world_position - last).length(), 2.0)
            self.assertAlmostEqual(self.body_share(), FRAME_POSITION, delta=.012)
            last = camera.world_position

    def test_the_setting_moves_the_body_and_a_follow_height_above_default_lowers_it(self):
        self.rig.frame_position = .65
        self.settle(.3)
        self.assertAlmostEqual(self.body_share(), .65, delta=.012)
        self.rig.frame_position = FRAME_POSITION
        self.settle(.3)
        low = self.body_share()
        self.rig._follow_height += .5
        self.settle(.3)
        self.assertGreater(self.body_share(), low)
        self.rig._follow_height -= .5

    def test_the_abilities_leave_the_body_clear(self):
        half = self.game.hud.slot_row[0].SIZE[0] * .5
        self.assertEqual(len(SLOT_POSITIONS), 6)
        for x in SLOT_POSITIONS:
            self.assertGreater(abs(x) - half, .1, x)


class ObstacleTests(FramingCase):
    def test_the_ground_never_comes_through_at_any_pitch(self):
        for pitch in (-89.0, -60.0, -30.0, -10.0, 0.0, 30.0, 89.0):
            self.rig.pitch = pitch
            for _ in range(10):
                self.frames(1)
                self.assertGreaterEqual(self.game.planet.altitude(SimVec3(*camera.world_position)),
                                        GROUND_CLEARANCE - 1e-3, pitch)

    def test_looking_up_from_the_ground_the_body_stays_framed(self):
        for pitch in (-30.0, -60.0):
            self.rig.pitch = pitch
            self.settle(.3)
            self.assertAlmostEqual(self.body_share(), FRAME_POSITION, delta=.03, msg=pitch)

    def test_a_wall_behind_the_player_does_not_come_between_them(self):
        building = next(obj for obj in self.game.world.objects
                        if obj.anchored and not obj.health.broken and not getattr(obj, "is_traffic", False)
                        and abs(obj.scale_y) > 6.0 and abs(obj.scale_z) > 6.0 and obj.collider is not None)
        x, z = float(building.x), float(building.z)
        far_face = z + abs(building.scale_z) * .5
        self.player.position = (x, float(building.y), far_face + 4.0)
        self.player.flight.phase = FlightPhase.CRUISE
        self.player.flight.velocity = SimVec3()
        self.rig.pivot.position = self.player.position
        self.rig.pitch = 0.0
        self.player.local_yaw = self.rig.yaw = 0.0  # facing away from it, with the camera at its wall
        self.settle(.6)
        body = SimVec3(self.player.x, self.player.y + BODY_MIDDLE, self.player.z)
        eye = SimVec3(*camera.world_position)
        between = eye - body
        way = between.normalized()
        hit = world_raycast(Vec3(body.x, body.y, body.z), Vec3(way.x, way.y, way.z),
                            distance=between.length(), ignore=[self.player, self.rig.pivot])
        self.assertFalse(hit.hit, "nothing between the camera and the player")
        self.assertGreater(float(eye.z), far_face, "on the player's side of the wall")
        self.assertAlmostEqual(self.body_share(), FRAME_POSITION, delta=.04)


class LockTests(FramingCase):
    def centre_error(self) -> float:
        point = self.combat.targets.point_of(self.combat.targets.manual)
        relative = camera.getRelativePoint(scene, LPoint3f(point.x, point.y, point.z))
        return abs(relative.y / relative.z) / screen_half_height()

    def test_the_target_is_centred_and_the_player_stays_low(self):
        self.stand(self.enemy, 20.0, 60.0)
        self.game.input("q")
        self.game.input("q up")
        self.assertIs(self.combat.targets.manual, self.enemy)
        self.settle(2.0)
        self.assertLess(self.centre_error(), .02)
        self.assertAlmostEqual(self.body_share(), FRAME_POSITION, delta=.012)

    def test_a_close_target_settles_without_hunting(self):
        self.stand(self.enemy, 3.0, 9.0)
        self.game.input("q")
        self.game.input("q up")
        self.settle(2.0)
        pitches = []
        for _ in range(60):
            self.frames(1)
            pitches.append(self.rig.pitch)
        self.assertLess(max(pitches) - min(pitches), .5, "it holds still")
        self.assertLess(self.centre_error(), .05)

    def test_a_target_high_above_stays_tracked(self):
        self.stand(self.enemy, 0.0, 40.0)
        self.enemy.position = (0.0, self.enemy.y + 120.0, 40.0)
        self.enemy.flight.phase = FlightPhase.CRUISE
        self.enemy.vitals.add_status("frozen", 60.0)
        self.game.input("q")
        self.game.input("q up")
        self.settle(2.0)
        self.assertLess(self.centre_error(), .05)
        self.assertLess(self.feet_share(), 1.0)


if __name__ == "__main__":
    unittest.main()
