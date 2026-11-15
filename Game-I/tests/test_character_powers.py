"""Every ability of all five characters, through the same keys a player presses."""

import unittest
import unittest.mock

from characters.roster import ROSTER_IDS
from config.power_schema import SLOT_ABILITIES
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from power_fixture import PowerCase, fresh_tree, object_of
from powers.vitals import ENERGY, HEAT, PHYSICAL


class SupermanTests(PowerCase, unittest.TestCase):
    PLAYER = "WHITE"
    DIRECT = {"2": "freeze_breath", "3": "super_breath", "4": "kryptonian_vision", "r": "solar_overcharge"}

    def test_heat_vision_toggles_and_damages_continuously(self):
        beam = self.ability("heat_vision")
        self.tap("1")
        self.assertTrue(beam.active, "still on after the key comes up")
        self.seconds(1.0)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.tap("1")
        self.assertFalse(beam.active)
        taken = self.enemy.vitals.damage_taken
        self.seconds(.3)
        self.assertEqual(self.enemy.vitals.damage_taken, taken, "stops when switched off")

    def test_heat_vision_damage_and_range_values_change_the_result(self):
        def fire():
            self.tap("1")
            self.seconds(1.0)
            self.tap("1")
        self.set("heat_vision", "damage", 100)
        base = self.damage_of(fire)
        self.set("heat_vision", "damage", 200)
        self.assertAlmostEqual(self.damage_of(fire), base * 2.0, delta=base * .25)
        self.set("heat_vision", "range", 10)
        self.manual()
        self.assertEqual(self.damage_of(fire), 0.0, "the enemy is now out of range")

    def test_heat_vision_burns_a_tree(self):
        self.manual()
        tree = fresh_tree(self.game, minimum=8.0)
        self.aim_at = SimVec3(tree.x, tree.y, tree.z)
        self.player.position = (tree.x, tree.y - 1.0, tree.z - 8.0)
        self.tap("1")
        self.seconds(.3)
        self.tap("1")
        self.assertLess(tree.tree_health, tree.tree_max_health)

    def test_heat_vision_that_fells_a_tree_does_not_crash_lighting_it(self):
        self.manual()
        self.set("heat_vision", "damage", 3000)
        tree = fresh_tree(self.game, minimum=8.0)
        self.aim_at = SimVec3(tree.x, tree.y, tree.z)
        self.player.position = (tree.x, tree.y - 1.0, tree.z - 8.0)
        self.tap("1")
        self.seconds(1.0)
        self.tap("1")
        self.assertTrue(tree.is_empty() or tree.tree_health <= 0.0, "the beam did fell it")
        self.assertNotIn(tree, self.combat.elements.burning)

    def test_heat_vision_scorches_and_cuts_the_ground(self):
        self.manual()
        self.aim_at = SimVec3(0.0, self.game.world.height_at(0.0, 12.0), 12.0)
        craters = len(self.game.world.terrain_impacts)
        self.tap("1")
        self.seconds(.5)
        self.tap("1")
        self.assertTrue(self.combat.elements.scorches)
        self.assertGreater(len(self.game.world.terrain_impacts), craters)

    def test_freeze_breath_toggles_slows_and_freezes(self):
        self.place_enemy("BLACK", 10.0)
        self.set("freeze_breath", "speed", 10)
        self.tap("2")
        self.seconds(.3)
        self.assertTrue(self.ability("freeze_breath").active)
        self.assertTrue(self.enemy.vitals.has("slowed"))
        self.assertFalse(self.enemy.vitals.has("frozen"), "slowly, at low Speed")
        self.set("freeze_breath", "speed", 400)
        self.seconds(.4)
        self.tap("2")
        self.assertFalse(self.ability("freeze_breath").active)
        self.assertTrue(self.enemy.vitals.has("frozen"))
        self.assertTrue(self.enemy.vitals.immobile)

    def test_freeze_breath_freezes_a_tree_and_extinguishes_it(self):
        self.manual()
        elements = self.combat.elements
        tree = fresh_tree(self.game, minimum=8.0)
        elements.ignite_tree(tree)
        self.player.position = (tree.x, tree.y - 1.0, tree.z - 8.0)
        self.aim_at = SimVec3(tree.x, tree.y, tree.z)
        self.tap("2")
        self.seconds(.3)
        self.tap("2")
        self.assertNotIn(tree, elements.burning)
        self.assertIn(tree, elements.frozen)
        self.assertEqual(elements.damage_scale_for(tree, PHYSICAL), 2.0)

    def test_freeze_breath_makes_ice_on_ground(self):
        self.manual()
        self.set("freeze_breath", "range", 40)
        self.aim_at = SimVec3(0.0, self.game.world.height_at(0.0, 15.0), 15.0)
        self.tap("2")
        self.seconds(.3)
        self.tap("2")
        self.assertTrue(self.combat.elements.ice)

    def test_super_breath_pushes_enemies_and_objects(self):
        self.place_enemy("BLACK", 10.0)
        self.tap("3")
        self.seconds(.4)
        self.tap("3")
        self.assertGreater(self.enemy.knock.z, 1.0)
        self.manual()
        boulder = object_of(self.game, "Boulder")
        self.player.position = (boulder.x, boulder.y, boulder.z - 8.0)
        self.aim_at = SimVec3(boulder.x, boulder.y, boulder.z)
        self.tap("3")
        self.seconds(.4)
        self.tap("3")
        self.assertGreater(boulder.velocity.length(), 1.0)

    def test_super_breath_damage_sets_its_force(self):
        self.place_enemy("BLACK", 10.0)
        self.set("super_breath", "damage", 1)
        self.tap("3")
        self.seconds(.2)
        self.tap("3")
        weak = self.enemy.knock.z
        self.enemy.knock = SimVec3()
        self.set("super_breath", "damage", 2000)
        self.tap("3")
        self.seconds(.2)
        self.tap("3")
        self.assertGreater(self.enemy.knock.z, weak * 2.0)

    def test_vision_cycles_every_mode_with_distinct_feedback(self):
        vision = self.ability("kryptonian_vision")
        seen = []
        for _ in range(4):
            self.tap("4")
            seen.append(vision.mode)
            self.assertTrue(self.game.hud.vision_overlay.enabled)
        self.assertEqual(seen, ["xray", "telescopic", "infrared", "microscopic"])
        self.tap("4")
        self.assertEqual(vision.mode, "off")
        self.assertFalse(self.game.hud.vision_overlay.enabled)

    def test_xray_marks_an_enemy_within_range_and_ghosts_buildings(self):
        self.tap("4")
        self.frames(2)
        self.assertGreater(self.combat.markers.showing, 0)
        vision = self.ability("kryptonian_vision")
        self.assertTrue(vision._ghosted, "buildings turn see-through")
        self.set("kryptonian_vision", "range", 5)
        self.frames(2)
        self.assertEqual(self.combat.markers.showing, 0, "Range limits it")
        for _ in range(4):
            self.tap("4")
        self.assertFalse(vision._ghosted, "and solid again afterwards")

    def test_telescopic_zoom_narrows_the_view_and_returns(self):
        self.tap("4")
        self.tap("4")
        self.assertLess(self.game.camera.vision_zoom, 1.0)
        for _ in range(3):
            self.tap("4")
        self.assertEqual(self.game.camera.vision_zoom, 1.0)

    def test_infrared_shows_fires(self):
        self.remove_enemy()
        tree = fresh_tree(self.game, minimum=1.0)
        self.combat.elements.ignite_tree(tree)
        for _ in range(3):
            self.tap("4")
        self.frames(1)
        self.assertGreater(self.combat.markers.showing, 0)

    def test_microscopic_inspects_the_target(self):
        self.place_enemy("BLACK", 10.0)
        for _ in range(4):
            self.tap("4")
        self.frames(1)
        self.assertIn("HOMELANDER", self.ability("kryptonian_vision").inspected)

    def test_solar_overcharge_blasts_at_once_empowers_and_toggles_off(self):
        solar = self.ability("solar_overcharge")
        self.place_enemy("BLACK", 15.0)
        self.assertEqual(self.player.powers.attack_scale, 1.0)
        self.tap("r")
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0, "no gathering time")
        self.assertTrue(solar.active)
        self.assertGreater(self.player.powers.attack_scale, 1.0)
        self.seconds(30.0)
        self.assertTrue(solar.active, "it does not run out")
        self.tap("r")
        self.assertFalse(solar.active)
        self.assertEqual(self.player.powers.attack_scale, 1.0)


class HomelanderTests(PowerCase, unittest.TestCase):
    PLAYER = "BLACK"
    ENEMY = "WHITE"
    DIRECT = {"2": "aerial_charge", "3": "enhanced_senses", "e": "grab", "r": "laser_overdrive"}

    def test_laser_modes_are_distinct_and_rmb_switches(self):
        laser = self.ability("laser_vision")
        self.assertEqual(laser.mode, "FOCUSED")
        focused = laser.beam_values()
        laser.switch_mode()
        self.assertEqual(laser.mode, "SWEEPING")
        sweeping = laser.beam_values()
        self.assertGreater(focused[0], sweeping[0])
        self.assertLess(focused[2], sweeping[2])

    def test_focused_beam_damages_and_sweep_speed_moves_it(self):
        def fire():
            self.tap("1")
            self.seconds(1.0)
            self.tap("1")
        self.assertGreater(self.damage_of(fire), 50.0)
        laser = self.ability("laser_vision")
        laser.mode = "SWEEPING"
        forward = SimVec3(0.0, 0.0, 1.0)
        aims = {round(laser.aim_offset(forward).x, 3) for _ in range(6)}
        self.assertGreater(len(aims), 3)

    def test_aerial_charge_rams_at_once_and_breaks_structures(self):
        self.press("2")
        self.assertIsNotNone(self.player.motion, "under way on the press")
        self.release("2")
        self.seconds(.6)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertIsNone(self.player.motion, "it stops at its target")
        self.manual()
        vehicle = object_of(self.game, "Vehicle")
        self.player.position = (vehicle.x, vehicle.y + 2, vehicle.z - 30.0)
        self.aim_at = SimVec3(vehicle.x, vehicle.y, vehicle.z)
        self.tap("2")
        self.seconds(.6)
        self.assertTrue(vehicle.health.broken)

    def test_pressing_a_charge_again_pulls_out(self):
        self.place_enemy(self.ENEMY, 3000.0)
        self.tap("2")
        self.assertIsNotNone(self.player.motion)
        self.tap("2")
        self.assertIsNone(self.player.motion)

    def test_senses_toggle_detect_enemies_and_zinc_blocks_xray(self):
        senses = self.ability("enhanced_senses")
        self.tap("3")
        self.seconds(30.0)
        self.assertTrue(senses.active, "unlimited duration")
        self.assertEqual(senses.detects(self.enemy), "xray")
        self.assertIn(self.enemy, senses.detected)
        vault = next(item for item in self.game.landmarks.items if getattr(item, "zinc", False))
        self.player.position = (vault.x, vault.y, vault.z - 40.0)
        self.enemy.position = (vault.x, vault.y - 1.0, vault.z)
        self.enemy.ground.velocity = SimVec3()
        self.assertIsNone(senses.detects(self.enemy), "still and behind zinc: hidden")
        self.enemy.ground.velocity = SimVec3(0.0, 0.0, 5.0)
        self.assertEqual(senses.detects(self.enemy), "hearing", "hearing is not X-ray")
        self.enemy.ground.velocity = SimVec3()
        self.tap("3")
        self.assertFalse(senses.active)

    def test_senses_range(self):
        self.set("enhanced_senses", "range", 5)
        self.assertIsNone(self.ability("enhanced_senses").detects(self.enemy))

    def test_overdrive_toggles_raises_damage_and_blasts_at_impact(self):
        def fire():
            self.tap("1")
            self.seconds(.5)
            self.tap("1")
        normal = self.damage_of(fire)
        overdrive = self.ability("laser_overdrive")
        self.tap("r")
        self.assertTrue(overdrive.engaged, "no charging")
        boosted = self.damage_of(fire)
        self.assertGreater(boosted, normal * 1.8)
        self.assertGreater(overdrive.range_scale, 1.0)
        self.tap("r")
        self.assertFalse(overdrive.engaged)

    def test_grab_card_uses_its_three_values(self):
        grab = self.ability("grab")
        self.place_enemy(self.ENEMY, 200.0)
        self.set("grab", "range", 50)
        self.tap("e")
        self.assertIsNot(grab.held, self.enemy, "out of Range")
        grab.cancel()
        self.set("grab", "range", 300)
        self.set("grab", "speed", 60)
        self.tap("e")
        self.assertIs(grab.held, self.enemy)
        self.frames(6)
        self.assertGreater(self.enemy.z, 150.0, "pulled in at Speed, not teleported")


class SentryTests(PowerCase, unittest.TestCase):
    PLAYER = "YELLOW"
    DIRECT = {"1": "energy_projection", "2": "golden_shield", "3": "molecular_manipulation", "4": "void_tendrils",
              "r": "void_unleashed"}

    def test_each_press_fires_one_full_power_shot(self):
        projection = self.ability("energy_projection")
        before = projection.fired
        self.press("1")
        self.release("1")
        self.assertEqual(projection.fired, before + 1)
        self.assertEqual(len(self.combat.projectiles), 1)
        self.assertAlmostEqual(self.combat.projectiles[0].damage, self.combat.settings.get(
            "YELLOW", "energy_projection", "damage"))
        self.seconds(.3)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertEqual(self.combat.projectiles, [], "it is gone once it lands")

    def test_shots_follow_a_moving_target(self):
        self.set("energy_projection", "speed", 100)
        self.place_enemy("BLACK", 40.0)
        self.tap("1")
        self.frames(5)
        self.enemy.x = 12.0
        self.seconds(.6)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)

    def test_damage_and_speed_values(self):
        def shoot():
            self.tap("1")
            self.seconds(.5)
        self.set("energy_projection", "damage", 100)
        small = self.damage_of(shoot)
        self.assertGreater(small, 0.0)
        self.set("energy_projection", "damage", 400)
        self.assertGreater(self.damage_of(shoot), small * 2.0)
        self.set("energy_projection", "speed", 40)
        self.enemy.vitals.damage_taken = 0.0
        self.tap("1")
        self.seconds(.1)
        self.assertEqual(self.enemy.vitals.damage_taken, 0.0, "still in the air")
        self.assertTrue(self.combat.projectiles)

    def test_blast_radius_follows_range_and_hits_several_enemies(self):
        other = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = "enemy_team"
        self.teams._apply_roster()
        self.stand(other, 4.0, self.DISTANCE)
        other.vitals.damage_taken = 0.0
        self.tap("1")
        self.seconds(.4)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertGreater(other.vitals.damage_taken, 0.0)

    def test_shield_toggles_absorbs_and_never_runs_out(self):
        shield = self.ability("golden_shield")
        self.tap("2")
        self.assertTrue(shield.active)
        self.seconds(30.0)
        self.assertTrue(shield.active)
        health = self.player.vitals.health
        self.combat.hit_character(None, self.player, 300.0, PHYSICAL)
        self.assertGreater(self.player.vitals.health, health - 40.0, "85% absorbed")
        for _ in range(50):
            self.combat.hit_character(None, self.player, 5.0, ENERGY)
        self.assertTrue(shield.active, "it does not break")
        self.tap("2")
        self.assertFalse(shield.active)
        health = self.player.vitals.health
        self.combat.hit_character(None, self.player, 300.0, PHYSICAL)
        self.assertLess(self.player.vitals.health, health - 100.0)

    def test_shield_range_covers_allies_inside_it(self):
        ally = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = "my_team"
        self.teams._apply_roster()
        self.stand(ally, 6.0, 0.0)
        self.tap("2")
        self.combat.hit_character(None, ally, 300.0, PHYSICAL)
        covered = ally.vitals.damage_taken
        self.set("golden_shield", "range", 2)
        ally.vitals.damage_taken = 0.0
        self.combat.hit_character(None, ally, 300.0, PHYSICAL)
        self.assertGreater(ally.vitals.damage_taken, covered * 3.0)

    def test_molecular_disintegrates_at_once_and_rmb_reconstructs(self):
        molecular = self.ability("molecular_manipulation")
        self.manual()
        boulder = object_of(self.game, "Boulder")
        self.player.position = (boulder.x, boulder.y, boulder.z - 15.0)
        self.aim_at = SimVec3(boulder.x, boulder.y, boulder.z)
        boulder.take_damage(30.0)
        self.player.powers.aiming = True  # no key reaches this for a player now
        self.tap("3")
        self.player.powers.aiming = False
        self.assertEqual(molecular.reconstructed, 1)
        self.assertEqual(boulder.health.health, boulder.health.maximum_health)
        self.tap("3")
        self.assertTrue(boulder.health.broken)
        self.assertEqual(molecular.disintegrated, 1)

    def test_molecular_targets_the_nearest_enemy(self):
        self.tap("3")
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)

    def test_tendrils_toggle_extend_at_speed_and_seize_everyone_in_range(self):
        tendrils = self.ability("void_tendrils")
        other = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = "enemy_team"
        self.teams._apply_roster()
        self.stand(other, 6.0, 15.0)
        self.set("void_tendrils", "speed", 30)
        self.tap("4")
        self.assertEqual(len(tendrils.grips), 2)
        self.frames(1)
        self.assertLess(tendrils.grips[0][1], 15.0, "they grow outward over time")
        self.seconds(1.2)
        self.assertTrue(self.enemy.vitals.has("restrained"))
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.seconds(20.0)
        self.assertTrue(tendrils.active, "until switched off")
        self.tap("4")
        self.assertFalse(tendrils.active)
        self.assertEqual(tendrils.grips, [])

    def test_void_changes_appearance_strengthens_and_toggles_back(self):
        void = self.ability("void_unleashed")
        root = self.player.pose_root
        self.assertFalse(root.hasColorScale())
        self.tap("r")
        self.assertTrue(void.engaged)
        self.assertTrue(root.hasColorScale(), "a visibly different Sentry")
        self.assertGreater(self.player.powers.attack_scale, 1.0)
        self.assertGreater(self.player.powers.tendril_scale, 1.0)
        self.assertGreater(self.player.vitals.regen_scale, 1.0)
        self.assertGreater(self.player.powers.energy_scale, 1.0)
        self.seconds(30.0)
        self.assertTrue(void.engaged)
        self.tap("r")
        self.assertFalse(void.engaged)
        self.assertFalse(root.hasColorScale(), "his own look returns")
        self.assertEqual(self.player.vitals.regen_scale, 1.0)

    def test_void_shockwaves_hit_nearby_enemies(self):
        self.place_enemy("BLACK", 12.0)
        self.tap("r")
        self.seconds(.1)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)


class OmniManTests(PowerCase, unittest.TestCase):
    PLAYER = "GREEN"
    DIRECT = {"1": "flight_charge", "2": "ground_slam", "4": "shockwave_punch", "e": "grab", "r": "dive_bomb"}

    def test_has_no_beams_or_projectiles(self):
        abilities = self.player.powers.abilities
        self.assertEqual({name for name in abilities if "vision" in name or "projection" in name}, set())
        self.assertEqual(self.combat.projectiles, [])

    def test_charge_hits_at_full_damage_from_any_distance(self):
        def charge(distance):
            self.place_enemy("BLACK", distance)
            self.player.position = (0.0, self.player.y, 0.0)
            def run():
                self.tap("1")
                self.seconds(.8)
            value = self.damage_of(run)
            self.player.release_motion()
            self.stand(self.player, 0.0, 0.0)
            return value
        near, far = charge(8.0), charge(120.0)
        self.assertGreater(near, 0.0)
        self.assertAlmostEqual(far, near, delta=near * .05)

    def test_charge_into_the_ground_makes_a_crater(self):
        self.manual()
        craters = len(self.game.world.terrain_impacts)
        self.player.flight.phase = FlightPhase.CRUISE
        self.player.y += 40.0
        self.aim_at = SimVec3(self.player.x, self.game.world.height_at(self.player.x, 30.0) - 1.0, 30.0)
        self.tap("1")
        self.seconds(.5)
        self.assertGreater(len(self.game.world.terrain_impacts), craters)

    def test_charge_with_nothing_ahead_ends_at_the_edge_of_the_world(self):
        self.remove_enemy()
        self.aim_at = SimVec3(0.0, 2000.0, 2000.0)
        self.tap("1")
        self.seconds(8.0)
        self.assertIsNone(self.player.motion)

    def test_slam_goes_to_the_nearest_enemy_from_the_ground_and_shakes_it(self):
        self.place_enemy("BLACK", 60.0)
        craters = len(self.game.world.terrain_impacts)
        self.tap("2")
        self.assertIsNotNone(self.player.motion)
        self.seconds(1.5)
        self.assertIsNone(self.player.motion)
        self.assertIs(self.player.flight.phase, FlightPhase.GROUNDED)
        self.assertLess(abs(self.player.z - 60.0), 6.0, "beside the enemy, not on top")
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertGreater(len(self.game.world.terrain_impacts), craters)

    def test_slam_impact_point_is_kept_on_land(self):
        from powers.omni_man import impact_point_near
        self.enemy.position = (4900.0, 5.0, 4900.0)
        point = impact_point_near(self.ability("ground_slam"), self.enemy)
        self.assertTrue(self.game.world.contains_position(point.x, point.z))
        self.assertAlmostEqual(point.y, self.game.world.height_at(point.x, point.z) + .25)

    def test_slam_range_sets_its_radius(self):
        self.place_enemy("BLACK", 18.0)
        self.set("ground_slam", "range", 10)
        self.tap("2")
        self.seconds(1.2)
        self.assertEqual(self.enemy.vitals.damage_taken, 0.0, "out of Range: it comes straight down")

    def test_shockwave_punch_strikes_on_the_press(self):
        punch = self.ability("shockwave_punch")
        self.place_enemy("BLACK", 5.0)
        self.set("shockwave_punch", "damage", 20)
        self.tap("4")
        self.assertEqual(punch.strikes, 1)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertGreater(self.enemy.knock.length(), 1.0)

    def test_dive_bomb_rises_and_impacts_beside_the_nearest_enemy(self):
        self.place_enemy("BLACK", 30.0)
        ground = self.player.y
        craters = len(self.game.world.terrain_impacts)
        self.tap("r")
        highest = ground
        for _ in range(240):
            self.frames(1)
            highest = max(highest, self.player.y)
            if self.player.motion is None:
                break
        self.assertGreater(highest, ground + 60.0)
        self.assertIsNone(self.player.motion)
        self.assertAlmostEqual(self.player.z, 30.0, delta=6.0)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertGreater(len(self.game.world.terrain_impacts), craters)

    def test_dive_bomb_with_no_enemy_goes_where_you_aim(self):
        self.remove_enemy()
        self.aim_at = SimVec3(0.0, self.game.world.height_at(0.0, 40.0), 40.0)
        self.tap("r")
        for _ in range(240):
            self.frames(1)
            if self.player.motion is None:
                break
        self.assertAlmostEqual(self.player.z, 40.0, delta=2.0)


class SoldierBoyTests(PowerCase, unittest.TestCase):
    PLAYER = "RED"
    DIRECT = {"1": "shield_throw", "4": "chest_blast", "e": "grab", "r": "radioactive_discharge"}

    def test_shield_throw_hits_and_comes_back(self):
        throw = self.ability("shield_throw")
        self.assertFalse(self.player.visual._shield.isHidden())
        self.set("shield_throw", "speed", 100)
        self.tap("1")
        self.assertEqual(throw.state, "flying")
        self.assertTrue(self.player.visual._shield.isHidden(), "it has left his arm")
        self.seconds(.4)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.seconds(.5)
        self.assertTrue(throw.in_hand)
        self.assertFalse(self.player.visual._shield.isHidden())

    def test_shield_recall_and_reuse_without_waiting(self):
        throw = self.ability("shield_throw")
        self.place_enemy("BLACK", 3000.0)
        self.set("shield_throw", "speed", 100)
        self.tap("1")
        self.frames(3)
        self.tap("1")
        self.assertEqual(throw.state, "returning")
        self.seconds(.3)
        self.assertTrue(throw.in_hand)
        self.tap("1")
        self.assertEqual(throw.state, "flying", "thrown again at once")

    def test_shield_can_be_walked_over_and_returns_on_its_own(self):
        throw = self.ability("shield_throw")
        self.remove_enemy()
        self.set("shield_throw", "range", 5)
        self.tap("1")
        self.seconds(.2)
        self.assertEqual(throw.state, "resting")
        self.player.position = (throw.position.x, throw.position.y - 1.4, throw.position.z)
        self.frames(1)
        self.assertTrue(throw.in_hand, "walking over it picks it up")
        self.tap("1")
        self.player.position = (0.0, self.player.y, -300.0)
        self.seconds(9.0)
        self.assertTrue(throw.in_hand, "it comes back by itself")

    def test_shield_is_a_physical_object_he_cannot_block_without(self):
        self.set("shield_throw", "speed", 50)
        self.remove_enemy()
        self.tap("1")
        self.ability("shield_defence").press()
        self.assertFalse(self.ability("shield_defence").raised)

    def test_shield_combat_is_weaker_without_the_shield(self):
        self.place_enemy("BLACK", 3.0)
        combat = self.ability("shield_combat")
        with_shield = combat.strength_scale()
        self.ability("shield_throw").state = "resting"
        self.assertLess(combat.strength_scale(), with_shield)
        self.ability("shield_throw").state = "hand"

    def test_shield_defence_toggles_and_range_sets_its_coverage(self):
        defence = self.ability("shield_defence")
        self.set("shield_defence", "range", 2)
        self.ability("shield_defence").press()
        self.assertTrue(defence.raised, "stays up after the button comes up")
        self.seconds(.5)  # past the parry window
        from_front = SimVec3(0.0, 0.0, -1.0)
        through, _knock = defence.absorb(100.0, PHYSICAL, from_front)
        self.assertAlmostEqual(through, 20.0)
        through, _knock = defence.absorb(100.0, PHYSICAL, SimVec3(0.0, 0.0, 1.0))
        self.assertEqual(through, 100.0, "at small Range it does not cover his back")
        self.set("shield_defence", "range", 12)
        through, _knock = defence.absorb(100.0, PHYSICAL, SimVec3(0.0, 0.0, 1.0))
        self.assertAlmostEqual(through, 20.0, msg="at full Range it covers all round")
        self.ability("shield_defence").press()
        self.assertFalse(defence.raised)

    def test_a_timed_parry_blocks_all_and_opens_a_counterattack(self):
        defence = self.ability("shield_defence")
        combat_ability = self.ability("shield_combat")
        normal = combat_ability.strength_scale()
        self.ability("shield_defence").press()
        self.frames(2)
        health = self.player.vitals.health
        self.combat.hit_character(self.enemy, self.player, 200.0, PHYSICAL, SimVec3(0.0, 0.0, -1.0), 40.0)
        self.assertEqual(self.player.vitals.health, health)
        self.assertEqual(defence.parries, 1)
        self.assertGreater(combat_ability.strength_scale(), normal, "counterattack window open")

    def test_chest_blast_arms_on_press_and_fires_full_output_on_release(self):
        blast = self.ability("chest_blast")
        self.place_enemy("BLACK", 12.0)
        self.press("4")
        self.assertTrue(blast.armed)
        self.assertEqual(self.enemy.vitals.damage_taken, 0.0, "nothing until release")
        with unittest.mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as spy:
            self.release("4")  # no hold at all
        origin = spy.call_args[0][1]
        self.assertAlmostEqual(origin.y, self.player.y + 1.75, places=3)
        self.assertEqual((origin.x, origin.z), (self.player.x, self.player.z))
        self.assertEqual(spy.call_args[0][3], self.combat.settings.get("RED", "chest_blast", "damage"))
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertEqual(blast.discharges, 1)

    def test_chest_blast_reaches_a_distant_target_with_a_bolt(self):
        self.place_enemy("WHITE", 900.0)
        self.press("4")
        self.release("4")
        self.assertEqual(len(self.combat.projectiles), 1)
        self.seconds(1.0)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertEqual(self.combat.projectiles, [])

    def test_nullification_takes_homelanders_powers_and_flight(self):
        self.place_enemy("BLACK", 5.0)
        black = self.enemy
        black.flight.phase = FlightPhase.CRUISE
        self.set("chest_blast", "damage", 10)
        self.tap("4")
        self.assertFalse(black.vitals.downed)
        self.assertTrue(black.vitals.nullified)
        self.assertFalse(black.flight_allowed)
        black.enforce_flight()
        self.assertIs(black.flight.phase, FlightPhase.LANDING)
        laser = black.powers.abilities["laser_vision"]
        self.assertFalse(laser.usable(quiet=True))
        self.assertTrue(black.powers.slots["+"].usable(quiet=True), "he can still throw a punch")

    def test_superman_sentry_and_omni_man_are_never_nullified(self):
        for character_id in ("WHITE", "YELLOW", "GREEN"):
            self.place_enemy(character_id, 5.0)
            self.set("chest_blast", "damage", 10)
            self.tap("4")
            self.tap("e")
            self.ability("grab").cancel()
            self.assertGreater(self.enemy.vitals.damage_taken, 0.0, character_id)
            self.assertFalse(self.enemy.vitals.nullified, character_id)
            self.teams.state.assignment[character_id] = "available"

    def test_maximum_discharge_fires_at_once_and_is_the_biggest_blast(self):
        self.place_enemy("BLACK", 30.0)
        craters = len(self.game.world.terrain_impacts)
        self.set("radioactive_discharge", "damage", 100)
        self.tap("r")
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertGreater(len(self.game.world.terrain_impacts), craters)
        self.assertTrue(self.enemy.vitals.nullified)
        self.assertEqual(self.ability("radioactive_discharge").discharges, 1)


class UniversalTests(PowerCase, unittest.TestCase):
    DIRECT = {"e": "grab", "q": "dash"}
    def test_one_press_is_one_hit_however_long_it_is_held(self):
        self.place_enemy("BLACK", 3.0)
        self.set("melee", "damage", 40)
        self.game.input("=")
        self.assertEqual(self.ability("melee").attacks, 1, "the hit landed on the press itself")
        self.frames(60)
        self.game.input("=")  # a repeat with no release
        self.game.input("= up")
        self.assertEqual(self.ability("melee").attacks, 1)

    def test_melee_rushes_a_distant_enemy_at_speed_and_lands_one_blow(self):
        self.place_enemy("BLACK", 200.0)
        melee = self.ability("melee")
        self.set("melee", "speed", 300)
        self.click()
        self.assertIsNotNone(self.player.motion)
        self.assertEqual(self.enemy.vitals.damage_taken, 0.0, "not there yet")
        self.seconds(1.0)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertEqual(melee.attacks, 1)
        self.assertGreater(self.player.z, 180.0)

    def test_melee_range_stops_the_rush(self):
        self.place_enemy("BLACK", 60.0)
        self.set("melee", "range", 10)
        self.click()
        self.assertIsNone(self.player.motion)
        self.assertEqual(self.enemy.vitals.damage_taken, 0.0)

    def test_finishing_blow_on_a_weak_target(self):
        self.place_enemy("BLACK", 3.0)
        self.set("melee", "damage", 40)
        normal = self.damage_of(self.click)
        vitals = self.enemy.vitals
        vitals.health = vitals.max_health * .1
        vitals.damage_taken = 0.0
        self.click()
        self.assertGreater(vitals.damage_taken, normal * 1.5)

    def test_a_punch_looking_down_with_nobody_near_hits_the_ground(self):
        self.manual()
        self.aim_at = SimVec3(0.0, self.player.y - 20.0, 5.0)
        craters = len(self.game.world.terrain_impacts)
        self.click()
        self.assertGreater(len(self.game.world.terrain_impacts), craters)

    def test_dash_moves_dodges_and_can_be_used_again_straight_away(self):
        here = self.player.z
        self.tap("q")
        self.assertTrue(self.player.is_evading)
        self.assertEqual(self.combat.hit_character(self.enemy, self.player, 300.0, PHYSICAL), 0.0)
        self.seconds(.4)
        self.assertNotEqual(self.player.z, here)
        self.assertFalse(self.player.is_evading)
        self.tap("q")
        self.assertTrue(self.player.is_evading)

    def test_grab_and_throw_an_enemy_with_impact_damage(self):
        grab = self.ability("grab")
        self.place_enemy("BLACK", 5.0)
        self.tap("e")
        self.assertIs(grab.held, self.enemy)
        self.frames(2)
        self.assertTrue(self.enemy.vitals.has("held"))
        self.assertLess(((self.enemy.x - self.player.x) ** 2 + (self.enemy.z - self.player.z) ** 2) ** .5, 5.0)
        self.tap("e")
        self.assertIsNone(grab.held)
        self.assertGreater(self.enemy.knock.length(), 10.0)

    def test_grab_lifts_loose_objects_of_any_mass_and_refuses_buildings(self):
        grab = self.ability("grab")
        self.remove_enemy()
        vehicle = object_of(self.game, "Vehicle")
        self.player.position = (vehicle.x, vehicle.y, vehicle.z - 4.0)
        self.tap("e")
        self.assertIs(grab.held, vehicle)
        self.tap("e")
        self.assertGreater(vehicle.velocity.length(), 10.0, "thrown")
        building = object_of(self.game, "Building")
        self.player.position = (building.x, building.y, building.z - abs(building.scale_z) * .5 - 3.0)
        self.tap("e")
        self.assertIsNot(grab.held, building)
        grab.cancel()

    def test_energy_absorption_returns_health(self):
        vitals = self.player.vitals
        vitals.health = 500.0
        self.combat.hit_character(None, self.player, 100.0, PHYSICAL)
        self.assertGreater(vitals.health, 500.0 - 100.0 * .5, "sentry's 50% resistance, plus absorption")

    def test_going_down_is_not_game_over(self):
        vitals = self.player.vitals
        self.ability("void_unleashed").press()
        self.combat.hit_character(None, self.player, 1e9, PHYSICAL)
        self.assertTrue(vitals.downed)
        self.assertFalse(self.ability("void_unleashed").active)
        self.tap("q")
        self.assertIsNone(self.player.motion, "no powers while down")
        vitals.downed_for = .05
        self.seconds(.2)
        self.assertFalse(vitals.downed)
        self.assertGreater(vitals.health, 0.0)

    def test_held_keys_do_not_retrigger_press_only_abilities(self):
        self.place_enemy("BLACK", 3.0)
        for _ in range(5):
            self.game.input("q hold")
        self.assertIsNone(self.player.motion)

    def test_allies_are_never_hurt(self):
        ally = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = "my_team"
        self.teams._apply_roster()
        self.stand(ally, 3.0, 3.0)
        self.assertEqual(self.combat.hit_character(self.player, ally, 100.0), 0.0)
        self.combat.blast(self.player, SimVec3(3.0, ally.y, 3.0), 10.0, 500.0, 10.0)
        self.assertEqual(ally.vitals.damage_taken, 0.0)


class KeyMapTests(unittest.TestCase):
    def test_every_character_is_in_the_slot_table(self):
        self.assertEqual(set(SLOT_ABILITIES), set(ROSTER_IDS))


__all__ = ["HEAT"]


if __name__ == "__main__":
    unittest.main()
