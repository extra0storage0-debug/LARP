"""Key 1 for Sentry and Soldier Boy: the chest beams, on the real game loop."""

from __future__ import annotations

import unittest
from unittest import mock

from ursina import held_keys

from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM
from config.power_schema import SCHEMA, SLOT_ABILITIES, ability_of
from game_fixture import FRAME
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from power_fixture import fresh_tree
from powers.aiming import center_of
from powers.base import BEAM_TRACE_INTERVAL
from powers.chest_beam import GoldenChestBeam, RadioactiveChestBeam
from powers.vitals import HEAT, PHYSICAL, RADIATION
from test_gameplay_control_update import LiveCase

BEAMERS = {"YELLOW": (GoldenChestBeam, HEAT), "RED": (RadioactiveChestBeam, RADIATION)}
OTHER_ONES = {"WHITE": "heat_vision", "BLACK": "laser_vision", "GREEN": "squad_summon"}


class BeamCase(LiveCase):
    def tap(self, key: str) -> None:
        if key == "1":  # the beams have no key of their own now; Soldier Boy's execution still uses his
            self.beam.press()
            self.beam.release()
            return
        super().tap(key)

    def start(self, character_id: str, enemy: str = "BLACK", distance: float = 60.0, tough: bool = True):
        self.begin(character_id, enemy, distance)
        self.enemy.vitals.add_status("frozen", 600.0)
        if tough:
            self.tough(self.enemy)
        self.frames(1)
        self.beam = self.player.powers.abilities["chest_beam"]
        return self.beam


class SetupTests(unittest.TestCase):
    def test_the_bomb_is_gone_and_only_these_two_changed(self):
        for character_id in BEAMERS:
            self.assertNotIn("bomb_mode", [card.ability_id for card in SCHEMA[character_id]])
        for character_id, ability_id in OTHER_ONES.items():
            self.assertEqual(SLOT_ABILITIES[character_id]["1"], ability_id)
        import powers.bombs
        self.assertFalse(hasattr(powers.bombs, "RemoteBomb"))
        self.assertEqual(SLOT_ABILITIES["YELLOW"]["4"], "void_nuclear_execution")
        self.assertEqual(SLOT_ABILITIES["RED"]["4"], "radioactive_execution")

    def test_range_damage_and_speed_are_all_configurable(self):
        for character_id in BEAMERS:
            card = ability_of(character_id, "chest_beam")
            for key in ("range", "damage", "speed"):
                self.assertIsNotNone(card.param(key), key)


class BeamTests(BeamCase):
    def test_each_beam_is_its_own_colour_from_the_chest_never_the_eyes(self):
        reds_and_blues = {}
        for character_id, (cls, kind) in BEAMERS.items():
            with self.subTest(character_id):
                beam = self.start(character_id)
                self.assertIsInstance(beam, cls)
                self.assertEqual(beam.KIND, kind)
                self.tap("1")
                self.assertTrue(beam.active, "at once: no charge time")
                self.frames(30)
                visual = beam.visual
                self.assertTrue(visual.cores[0].visible)
                self.assertFalse(visual.cores[1].visible, "one beam, not two eyes")
                chest = beam.beam_origin()
                body = self.player
                self.assertAlmostEqual(chest.y, float(body.y) + 1.7, delta=.4, msg="chest height")
                eye = body.eye_points()[0]
                self.assertGreater(float(eye.y) - chest.y, .3, "well below the eyes")
                self.assertLess(((chest.x - float(body.x)) ** 2 + (chest.z - float(body.z)) ** 2) ** .5, .8,
                                "on the middle of the body")
                reds_and_blues[character_id] = visual.glows[0].color
                self.assertEqual(visual.flare.color, beam.FLARE)
                self.assertLess((SimVec3(*visual.flare.position) - center_of(self.enemy)).length(), 2.5,
                                "and it reaches the target")
                self.tap("1")
        golden, green = reds_and_blues["YELLOW"], reds_and_blues["RED"]
        self.assertGreater(golden[0], golden[2], "golden")
        self.assertGreater(green[1], green[0], "green")

    def test_it_points_the_chest_at_a_target_behind_the_body(self):
        for character_id in BEAMERS:
            beam = self.start(character_id, distance=-40.0)
            self.tap("1")
            self.seconds(1.0)
            forward = self.game.planet.heading(SimVec3(self.player.x, self.player.y, self.player.z),
                                               self.player.local_yaw)
            self.assertLess(forward.z, -.9)
            self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
            self.tap("1")
            self.assertFalse(beam.active)

    def test_damage_is_real_at_the_set_rate_in_ticks_and_of_the_right_kind(self):
        for character_id, (_cls, kind) in BEAMERS.items():
            with self.subTest(character_id):
                beam = self.start(character_id)
                self.combat.settings.set(character_id, "chest_beam", "damage", 300)
                self.enemy.vitals.resistance = self.enemy.vitals.radiation_resistance = 0.0
                with mock.patch.object(self.combat, "hit_character", wraps=self.combat.hit_character) as hits:
                    self.tap("1")
                    self.seconds(1.0)
                    self.tap("1")
                self.assertAlmostEqual(self.enemy.vitals.damage_taken, 300.0, delta=45.0)
                self.assertLessEqual(hits.call_count, round(1.1 / BEAM_TRACE_INTERVAL), "ticks, not frames")
                self.assertGreaterEqual(hits.call_count, 10)
                self.assertEqual(hits.call_args.args[3], kind)
                self.assertIs(beam.owner, self.player)

    def test_range_limits_it(self):
        for character_id in BEAMERS:
            beam = self.start(character_id, distance=200.0)
            self.combat.settings.set(character_id, "chest_beam", "range", 50)
            self.tap("1")
            self.seconds(.5)
            self.assertEqual(self.enemy.vitals.damage_taken, 0.0)
            self.tap("1")
            self.combat.settings.set(character_id, "chest_beam", "range", 1000)
            self.tap("1")
            self.seconds(.5)
            self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
            self.tap("1")
            self.assertFalse(beam.active)

    def test_speed_is_how_fast_the_front_travels(self):
        for character_id in BEAMERS:
            self.start(character_id, distance=100.0)
            self.combat.settings.set(character_id, "chest_beam", "speed", 50)
            self.tap("1")
            self.seconds(1.0)
            self.assertEqual(self.enemy.vitals.damage_taken, 0.0, "only 50 m out after a second")
            self.seconds(1.5)
            self.assertGreater(self.enemy.vitals.damage_taken, 0.0, "and there by now")
            self.tap("1")

    def test_goes_for_the_nearest_enemy_and_a_locked_one_first_and_never_allies(self):
        beam = self.start("YELLOW", distance=80.0)
        near = self.teams.characters["GREEN"]
        self.teams.state.assignment["GREEN"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.stand(near, 20.0, 0.0)
        near.vitals.add_status("frozen", 600.0)
        self.tough(near)
        ally = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = MY_TEAM
        self.teams._apply_roster()
        self.stand(ally, 10.0, 0.0)  # right in the line to the nearest enemy
        ally.vitals.add_status("frozen", 600.0)
        self.tough(ally)
        self.frames(1)
        self.combat.targets.clear()
        self.tap("1")
        self.seconds(.6)
        self.assertGreater(near.vitals.damage_taken, 0.0)
        self.assertEqual(self.enemy.vitals.damage_taken, 0.0)
        self.assertEqual(ally.vitals.damage_taken, 0.0)
        self.game.input("q")
        while self.combat.targets.manual is not self.enemy:
            self.game.input("scroll up")
        taken = near.vitals.damage_taken
        self.seconds(.6)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0, "the lock comes first")
        self.assertAlmostEqual(near.vitals.damage_taken, taken, delta=taken * .2 + 50.0)
        self.tap("1")
        self.assertFalse(beam.active)

    def test_it_stops_when_nobody_is_left_and_moves_on_when_someone_is(self):
        for character_id in BEAMERS:
            with self.subTest(character_id):
                beam = self.start(character_id, tough=False)
                free = len(self.combat._beams)
                second = self.teams.characters["GREEN"]
                self.teams.state.assignment["GREEN"] = ENEMY_TEAM
                self.teams._apply_roster()
                self.stand(second, 0.0, 90.0)
                second.vitals.add_status("frozen", 600.0)
                self.tough(second)
                self.frames(1)
                self.combat.targets.clear()
                self.tap("1")
                self.seconds(.3)
                self.enemy.vitals.health = 1.0
                self.seconds(.8)
                self.assertTrue(self.enemy.vitals.downed)
                self.assertTrue(beam.active, "on to the next enemy")
                self.assertIs(beam.tracking, second)
                self.assertGreater(second.vitals.damage_taken, 0.0)
                self.teams.state.assignment["GREEN"] = AVAILABLE
                self.teams._apply_roster()
                self.seconds(.2)
                self.assertFalse(beam.active, "nobody left")
                self.assertEqual(len(self.combat._beams), free, "its visual handed back")
                self.frames(5)

    def test_with_nobody_about_it_still_works_on_the_world(self):
        beam = self.start("YELLOW")
        self.teams.state.assignment[self.enemy.character_id] = AVAILABLE
        self.teams._apply_roster()
        self.frames(1)
        tree = fresh_tree(self.game, minimum=8.0)
        self.stand(self.player, tree.x, tree.z - 10.0)
        spot = SimVec3(float(tree.x), float(tree.y), float(tree.z))
        with mock.patch.object(type(self.player), "aim_direction_from",
                               lambda owner, origin, _limit: (spot - origin).normalized()):
            self.tap("1")
            self.seconds(.6)
        self.assertTrue(tree.is_empty() or tree.tree_health < tree.tree_max_health)
        self.tap("1")
        self.assertFalse(beam.active)

    def test_it_damages_trees_and_objects_in_the_way_for_both(self):
        for character_id in BEAMERS:
            with self.subTest(character_id):
                self.start(character_id, distance=60.0)
                tree = fresh_tree(self.game, minimum=8.0)
                self.stand(self.player, tree.x, tree.z - 12.0)
                self.stand(self.enemy, tree.x, tree.z + 20.0)
                self.combat.targets.clear()
                self.frames(1)
                self.tap("1")
                self.seconds(1.0)
                self.tap("1")
                self.assertTrue(tree.is_empty() or tree.tree_health < tree.tree_max_health)

    def test_only_sentrys_burns(self):
        beam = self.start("RED")
        with mock.patch.object(self.combat, "heat_effects", wraps=self.combat.heat_effects) as heat:
            self.tap("1")
            self.seconds(.3)
            self.tap("1")
        self.assertEqual(heat.call_count, 0)
        self.assertFalse(beam.active)
        beam = self.start("YELLOW")
        with mock.patch.object(self.combat, "heat_effects", wraps=self.combat.heat_effects) as heat:
            self.tap("1")
            self.seconds(.3)
            self.tap("1")
        self.assertGreater(heat.call_count, 0)

    def test_particles_stay_within_the_pool_over_a_long_beam(self):
        beam = self.start("YELLOW")
        puffs = self.combat.puffs
        total = len(puffs.free) + len(puffs.live)
        self.tap("1")
        largest = 0
        for _ in range(round(5.0 / FRAME)):
            self.game.update(FRAME)
            largest = max(largest, len(puffs.live))
        self.assertLessEqual(largest, total)
        self.assertLessEqual(largest, 14, "a modest share of the pool")
        self.tap("1")
        self.assertFalse(beam.active)
        self.seconds(1.0)
        self.assertEqual(len(puffs.live), 0, "and they all finish")

    def test_switching_character_stops_it_and_hands_back_its_visual(self):
        beam = self.start("YELLOW")
        free = len(self.combat._beams)
        self.tap("1")
        self.frames(5)
        self.assertLess(len(self.combat._beams), free)
        self.teams.state.assignment["WHITE"] = MY_TEAM
        self.teams.swap("WHITE", save=False)
        self.assertFalse(beam.active)
        self.assertEqual(len(self.combat._beams), free)

    def test_soldier_boy_stays_on_the_ground_while_firing(self):
        self.start("RED")
        self.tap("1")
        self.seconds(1.0)
        self.assertFalse(self.player.flight.is_flying)
        self.assertLess(float(self.player.y) - self.game.world.height_at(self.player.x, self.player.z), 1.0)
        self.tap("1")

    def test_it_works_flying_and_during_a_time_stop(self):
        beam = self.start("YELLOW", distance=80.0)
        self.game.input("f")
        self.seconds(1.0)
        self.tap("t")
        self.tap("1")
        self.seconds(.6)
        self.assertTrue(self.combat.world_stopped)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.tap("1")
        self.assertFalse(beam.active)

    def test_keys_2_3_and_4_are_untouched_by_the_beam(self):
        self.start("YELLOW", distance=40.0)
        self.tap("1")
        self.seconds(.2)
        self.tap("3")
        for _ in range(600):
            self.game.update(FRAME)
            if self.player.motion is None:
                break
        self.assertIsNone(self.player.motion)
        self.assertFalse(self.combat.time_stopped)

    def test_it_damages_a_building_in_the_way_for_both(self):
        for character_id in BEAMERS:
            with self.subTest(character_id):
                self.start(character_id)
                building = next(obj for obj in self.game.world.objects
                                if obj.anchored and not obj.health.broken and not getattr(obj, "is_traffic", False)
                                and abs(obj.scale_y) > 6.0 and abs(obj.scale_z) > 4.0)
                before = building.health.health
                x, z, depth = float(building.x), float(building.z), abs(building.scale_z) * .5
                height = float(building.y)  # its collision box starts above the ground
                self.player.flight.phase = self.enemy.flight.phase = FlightPhase.CRUISE
                self.player.position = (x, height, z - depth - 15.0)
                self.enemy.position = (x, height, z + depth + 15.0)
                self.combat.targets.clear()
                self.frames(1)
                self.tap("1")
                self.seconds(1.0)
                self.tap("1")
                self.assertLess(building.health.health, before)


class StayingPutTests(BeamCase):
    """The beam goes out; nothing about firing it moves the one firing it."""

    def where(self) -> tuple:
        return float(self.player.x), float(self.player.y), float(self.player.z)

    def assert_at_rest(self) -> None:
        self.assertEqual(self.player.ground.velocity.length(), 0.0)
        self.assertEqual(self.player.flight.velocity.length(), 0.0)
        self.assertEqual(self.player.knock.length(), 0.0)
        self.assertEqual(self.player.jump_velocity, 0.0)

    def test_ten_seconds_of_firing_does_not_shift_the_body_at_all(self):
        for character_id in BEAMERS:
            for distance in (60.0, -40.0):  # ahead, and behind: the body turns right round for that one
                with self.subTest(character_id, distance=distance):
                    beam = self.start(character_id, distance=distance)
                    here = self.where()
                    self.tap("1")
                    self.seconds(10.0)
                    self.assertTrue(beam.active)
                    self.assertEqual(self.where(), here)
                    self.assert_at_rest()
                    self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
                    self.tap("1")
                    self.assertFalse(beam.active)

    def test_turning_the_camera_and_changing_target_do_not_shift_it_either(self):
        for character_id in BEAMERS:
            with self.subTest(character_id):
                self.start(character_id, distance=50.0)
                second = self.teams.characters["GREEN"]
                self.teams.state.assignment["GREEN"] = ENEMY_TEAM
                self.teams._apply_roster()
                self.stand(second, 40.0, 0.0)
                second.vitals.add_status("frozen", 600.0)
                self.tough(second)
                self.frames(1)
                here = self.where()
                self.tap("1")
                for _ in range(120):
                    self.game.camera.yaw += 3.0
                    self.game.update(FRAME)
                self.assertEqual(self.where(), here)
                self.game.input("q")
                for target in (second, self.enemy):
                    while self.combat.targets.manual is not target:
                        self.game.input("scroll up")
                    taken = target.vitals.damage_taken
                    self.seconds(1.0)
                    self.assertGreater(target.vitals.damage_taken, taken, "the lock comes first")
                    self.assertEqual(self.where(), here)
                self.game.input("q")
                self.assert_at_rest()
                self.tap("1")

    def test_walking_still_works_while_firing_and_afterwards(self):
        for character_id in BEAMERS:
            with self.subTest(character_id):
                self.start(character_id)
                self.tap("1")
                z = float(self.player.z)
                held_keys["w"] = 1
                self.seconds(1.0)
                held_keys["w"] = 0
                self.assertGreater(float(self.player.z) - z, 1.2, "firing does not hold the body still")
                self.tap("1")
                self.seconds(1.0)
                z = float(self.player.z)
                held_keys["w"] = 1
                self.seconds(1.0)
                held_keys["w"] = 0
                self.assertGreater(float(self.player.z) - z, 1.2)
                self.seconds(1.0)
                here = self.where()
                self.seconds(1.0)
                self.assertAlmostEqual(self.where()[2], here[2], delta=.01, msg="and it comes to rest")

    def test_a_vehicle_it_blows_up_does_not_throw_the_one_firing(self):
        for character_id in BEAMERS:
            for gap in (5.0, 15.0):
                with self.subTest(character_id, gap=gap):
                    self.start(character_id)
                    self.combat.settings.set(character_id, "chest_beam", "damage", 3000)
                    vehicle = next(item for item in self.game.landmarks.items
                                   if getattr(item, "explosive", False) and not item.health.broken)
                    self.stand(self.player, vehicle.x, vehicle.z - gap)
                    self.stand(self.enemy, vehicle.x, vehicle.z + 3.0)  # close behind it, so the beam comes down through it
                    self.player.local_yaw = self.game.camera.yaw = 0.0
                    self.combat.targets.clear()
                    self.frames(2)
                    here = self.where()
                    self.tap("1")
                    self.seconds(2.0)
                    self.assertTrue(vehicle.health.broken, "the destruction still happens")
                    self.assertEqual(self.where(), here)
                    self.assert_at_rest()
                    self.tap("1")

    def test_an_ownerless_blast_still_hurts_the_one_firing_and_throws_everyone_else(self):
        self.start("YELLOW", enemy="RED", distance=10.0)  # he cannot fly, so a push always lands in his knock
        self.tap("1")
        self.frames(1)
        hurt, thrown = self.player.vitals.damage_taken, self.enemy.knock.length()
        origin = SimVec3(float(self.player.x), float(self.player.y), float(self.player.z) + 5.0)
        self.combat.on_area_damage(origin, 200.0, 30.0, 40.0)
        self.assertGreater(self.player.vitals.damage_taken, hurt)
        self.assert_at_rest()
        self.assertGreater(self.enemy.knock.length(), thrown)

    def test_the_blast_still_throws_the_same_body_when_it_is_not_firing(self):
        self.start("YELLOW")
        origin = SimVec3(float(self.player.x), float(self.player.y), float(self.player.z) + 5.0)
        self.combat.on_area_damage(origin, 200.0, 30.0, 40.0)
        self.assertLess(self.player.knock.z, 0.0, "pushed away from the blast")

    def test_being_hit_by_an_enemy_still_knocks_the_one_firing_back(self):
        for character_id in BEAMERS:
            with self.subTest(character_id):
                self.start(character_id)
                self.tap("1")
                self.frames(1)
                self.combat.hit_character(self.enemy, self.player, 1.0, PHYSICAL, SimVec3(0.0, 0.0, -1.0), 40.0)
                self.assertLess(self.player.knock.z, 0.0, "this is the enemy's doing, not the beam's")
                self.tap("1")


if __name__ == "__main__":
    unittest.main()
