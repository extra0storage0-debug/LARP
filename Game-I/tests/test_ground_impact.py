"""F for all five, on the real game loop: flight or a super jump on the ground, a slam in the air."""

from __future__ import annotations

import unittest
from unittest import mock

from ursina import held_keys

from characters.roster import KITS
from config.character_roster import ENEMY_TEAM, MY_TEAM
from game_fixture import FRAME
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from power_fixture import fresh_tree
from powers.common import LaunchedMotion, launch_character
from powers.ground_impact import STYLES, ImpactDive, ImpactDiveMotion
from powers.vitals import EXPLOSION
from test_gameplay_control_update import LiveCase

FLYERS = ("WHITE", "BLACK", "YELLOW", "GREEN")
ALL = (*FLYERS, "RED")


def foe_of(character_id: str) -> str:
    return "WHITE" if character_id != "WHITE" else "BLACK"


class FCase(LiveCase):
    def start(self, character_id: str, distance: float = 700.0):
        self.begin(character_id, foe_of(character_id), distance)
        self.tough(self.enemy)
        self.tough(self.player)
        self.frames(1)

    def height(self) -> float:
        return float(self.player.y) - self.game.world.height_at(self.player.x, self.player.z) - .25

    def f(self) -> None:
        self.game.input("f")
        self.game.input("f up")

    def into_the_air(self, seconds: float = 1.0) -> None:
        """F on the ground for all five, and the character is on its way up."""
        self.f()
        self.seconds(seconds)
        self.assertGreater(self.height(), 1.5)

    def slam(self) -> ImpactDiveMotion:
        """F, in the air. Knocked flying, a flyer's F is a recovery into flight, so this is the slam AI and Soldier Boy have."""
        if self.player.motion is not None and self.player.motion.knocked_down and self.player.kit.can_fly:
            self.player.powers.abilities["impact_dive"].press()
        else:
            self.f()
        motion = self.player.motion
        self.assertIsInstance(motion, ImpactDiveMotion)
        return motion

    def until_done(self, motion, limit: float = 40.0) -> None:
        for _ in range(round(limit / FRAME)):
            if self.player.motion is not motion:
                return
            self.game.update(FRAME)
        self.fail("the slam never ended")

    def tearDown(self) -> None:
        held_keys["f"] = 0
        held_keys["w"] = 0
        held_keys["shift"] = 0


class SlamTests(FCase):
    def test_all_five_go_up_with_f_and_come_down_with_f_and_can_do_it_again(self):
        for character_id in ALL:
            with self.subTest(character_id):
                self.start(character_id)
                for _ in range(3):
                    self.assertEqual(self.player.movement_state, "GROUNDED")
                    self.into_the_air()
                    self.assertEqual(self.player.movement_state,
                                     "SUPER_JUMPING" if character_id == "RED" else "FLYING")
                    motion = self.slam()
                    self.assertEqual(self.player.movement_state, "DIVING")
                    self.until_done(motion)
                    self.assertEqual(self.player.movement_state, "GROUNDED")
                    self.assertIs(self.player.flight.phase, FlightPhase.GROUNDED, "flight is off")
                    self.assertLess(abs(self.height()), .6, "standing on the ground")
                    self.assertEqual(self.player.jump_height, 0.0)
                    self.frames(5)
                    self.assertLess(abs(self.height()), .6, "and stays there")

    def test_it_really_accelerates_and_moves_step_by_step(self):
        for character_id in ALL:
            with self.subTest(character_id):
                self.start(character_id)
                self.into_the_air(1.5)
                motion = self.slam()
                last = float(self.player.y)
                speeds = []
                while self.player.motion is motion and not motion.impacted:
                    self.game.update(FRAME)
                    if not motion.impacted:
                        speeds.append((last - float(self.player.y)) / FRAME)
                        last = float(self.player.y)
                self.assertGreater(speeds[-1], speeds[0] if len(speeds) > 1 else -1.0)
                self.assertLessEqual(max(speeds), motion.ability.p("speed") + 1.0, "no teleporting")
                self.until_done(motion)

    def test_a_real_blast_with_damage_knockback_and_a_crater(self):
        for character_id in ALL:
            with self.subTest(character_id):
                self.start(character_id)
                self.into_the_air()
                x, z = float(self.player.x), float(self.player.z)
                self.stand(self.enemy, x + 20.0, z)
                self.enemy.vitals.resistance = 0.0
                self.enemy.flight.phase = FlightPhase.GROUNDED
                craters = len(self.game.world.terrain_impacts)
                with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
                    self.until_done(self.slam())
                self.assertEqual(blast.call_count, 1)
                self.assertEqual(blast.call_args.kwargs["kind"], EXPLOSION)
                self.assertGreater(self.enemy.vitals.damage_taken, 0.0, "real damage")
                self.assertGreater(self.enemy.moving_velocity.length() + self.enemy.knock.length(), 0.0, "knockback")
                self.assertGreater(len(self.game.world.terrain_impacts), craters, "the ground gives")

    def test_it_breaks_the_things_around_it(self):
        for character_id in ALL:
            with self.subTest(character_id):
                self.start(character_id)
                tree = fresh_tree(self.game, minimum=8.0)
                tree_id = tree.tree_id
                self.stand(self.player, float(tree.x) + 12.0, float(tree.z))
                self.into_the_air()
                self.until_done(self.slam())
                state = self.game.world.tree_states.get(tree_id, {})
                self.assertTrue(state.get("destroyed") or tree.is_empty() or tree.tree_health < tree.tree_max_health)

    def test_each_has_its_own_colours(self):
        self.assertEqual(set(STYLES), set(KITS))
        white, black, yellow, green, red = (STYLES[c].tint for c in ("WHITE", "BLACK", "YELLOW", "GREEN", "RED"))
        self.assertGreater(white[2], white[0], "blue-white")
        self.assertTrue(black[0] > 200 and black[1] < 100, "red")
        self.assertTrue(yellow[0] > 200 and yellow[1] > 150 and yellow[2] < 120, "gold")
        self.assertGreater(red[1], red[0], "green-tinged")
        self.assertIsNone(green, "Omni-Man's is plain force and dust")
        self.assertGreater(STYLES["GREEN"].dust_puffs, STYLES["WHITE"].dust_puffs)

    def test_the_blast_uses_their_colours(self):
        for character_id in ALL:
            with self.subTest(character_id):
                self.start(character_id)
                self.into_the_air()
                with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
                    self.until_done(self.slam())
                self.assertEqual(blast.call_args.kwargs["tint"], STYLES[character_id].tint)

    def test_allies_are_safe(self):
        self.start("YELLOW")
        ally = self.teams.characters["GREEN"]
        self.teams.state.assignment["GREEN"] = MY_TEAM
        self.teams._apply_roster()
        self.into_the_air()
        self.stand(ally, float(self.player.x) + 10.0, float(self.player.z))
        ally.vitals.damage_taken = 0.0
        self.until_done(self.slam())
        self.assertEqual(ally.vitals.damage_taken, 0.0)
        self.assertEqual(self.player.vitals.damage_taken, 0.0, "nor themselves")


class InputTests(FCase):
    def test_extra_presses_during_a_slam_change_nothing(self):
        for character_id in ALL:
            with self.subTest(character_id):
                self.start(character_id)
                self.into_the_air()
                motion = self.slam()
                with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
                    while self.player.motion is motion:
                        self.f()
                        self.assertIs(self.player.motion, motion)
                        self.game.update(FRAME)
                self.assertEqual(blast.call_count, 1, "one blast")

    def test_a_double_tap_is_not_a_slam_from_nowhere(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.start(character_id)
                self.f()
                self.assertTrue(self.player.flight.is_flying)
                self.f()  # the same frame: not off the ground yet
                self.assertIsNone(self.player.motion)
                self.assertTrue(self.player.flight.is_flying, "still taking off")

    def test_ctrl_still_lands_softly_near_the_ground(self):
        self.start("WHITE")
        self.into_the_air(.3)
        held_keys["control"] = 1
        self.seconds(5.0)
        held_keys["control"] = 0
        self.assertIs(self.player.flight.phase, FlightPhase.GROUNDED)
        self.assertIsNone(self.player.motion)

    def test_f_does_nothing_in_the_middle_of_a_sequence(self):
        self.start("YELLOW", distance=60.0)
        self.tap("3")
        motion = self.player.motion
        self.assertIsNotNone(motion)
        self.f()
        self.assertIs(self.player.motion, motion)
        self.player.release_motion()

    def test_while_frozen_or_held_f_does_nothing(self):
        self.start("WHITE")
        self.player.vitals.add_status("frozen", 5.0)
        self.f()
        self.assertFalse(self.player.flight.is_flying)
        self.assertIsNone(self.player.motion)

    def test_keys_1_to_4_t_and_q_are_as_they_were(self):
        for character_id, keys in (("WHITE", ("heat_vision", "high_speed_attack", "time_stop", "ground_execution")),
                                   ("BLACK", ("laser_vision", "high_speed_attack", "time_stop", "neck_laser_execution")),
                                   ("YELLOW", ("void_form", "high_speed_attack", "time_stop", "void_nuclear_execution")),
                                   ("GREEN", ("squad_summon", "high_speed_attack", "time_stop", "speed_execution")),
                                   ("RED", ("radiation_blast", "flying_punch", "aerial_grab_blast", "radioactive_execution"))):
            self.start(character_id)
            slots = self.player.powers.slots
            self.assertEqual(tuple(slots[key].ability_id for key in "1234"), keys)
            self.assertEqual(slots["t"].ability_id, "world_stop")
            self.assertNotIn("f", slots)
            self.assertNotIn("impact_dive", [slot.ability_id for slot in slots.values()])

    def test_it_is_not_on_the_power_menu(self):
        from config.power_schema import SCHEMA
        for character_id in ALL:
            self.assertNotIn("impact_dive", [card.ability_id for card in SCHEMA[character_id]])

    def test_a_character_switch_mid_dive_leaves_them_on_their_feet(self):
        self.start("WHITE")
        self.into_the_air(1.5)
        body = self.player
        self.slam()
        self.frames(2)
        self.teams.state.assignment["YELLOW"] = MY_TEAM
        self.teams.swap("YELLOW", save=False)
        self.assertIsNone(body.motion)
        self.assertIs(body.flight.phase, FlightPhase.GROUNDED)
        self.frames(3)
        self.assertLess(float(body.y) - self.game.world.height_at(body.x, body.z), 1.0)
        self.teams.swap("WHITE", save=False)


class TerrainTests(FCase):
    def building(self):
        return next(obj for obj in self.game.world.objects
                    if obj.anchored and not obj.health.broken and not getattr(obj, "is_traffic", False)
                    and abs(obj.scale_y) > 6.0 and abs(obj.scale_x) > 6.0 and abs(obj.scale_z) > 6.0)

    def test_coming_down_on_a_building_that_holds_never_leaves_them_inside_it(self):
        for character_id in ("WHITE", "RED"):
            with self.subTest(character_id):
                self.start(character_id)
                self.combat.settings.set(character_id, "impact_dive", "damage", 1)
                building = self.building()
                x, z = float(building.x), float(building.z)
                top = float(building.y) + abs(building.scale_y) * .5
                self.stand(self.player, x, z)
                self.player.position = (x, top + 60.0, z)
                if character_id == "RED":
                    self.player.jump_height = 60.0
                    self.player.jump_velocity = -1.0
                else:
                    self.player.flight.phase = FlightPhase.CRUISE
                self.frames(1)
                self.until_done(self.slam())
                self.assertIs(self.player.flight.phase, FlightPhase.GROUNDED)
                self.assertLess(abs(self.height()), .6)
                if not building.health.broken:
                    inside = (abs(float(self.player.x) - x) < abs(building.scale_x) * .5
                              and abs(float(self.player.z) - z) < abs(building.scale_z) * .5)
                    self.assertFalse(inside, "beside it, not inside it")
                held = (float(self.player.x), float(self.player.z))
                held_keys["w"] = 1
                self.seconds(.5)
                held_keys["w"] = 0
                self.assertNotEqual(held, (float(self.player.x), float(self.player.z)), "and free to walk away")

    def test_uneven_ground_and_craters_are_handled(self):
        for character_id in ALL:
            with self.subTest(character_id):
                self.start(character_id)
                for _ in range(3):  # each one comes down in the crater the one before made
                    self.into_the_air()
                    self.until_done(self.slam())
                    self.assertLess(abs(self.height()), .6)
                    self.assertIs(self.player.flight.phase, FlightPhase.GROUNDED)

    def test_from_a_very_long_way_up_soldier_boy_lands_the_same(self):
        self.start("RED")
        self.player.position = (float(self.player.x), 5000.0, float(self.player.z))
        self.player.jump_height = 4990.0
        self.player.jump_velocity = 10.0
        self.frames(1)
        motion = self.slam()
        self.until_done(motion, 30.0)
        self.assertLess(abs(self.height()), .6)
        self.assertEqual(self.player.vitals.damage_taken, 0.0)

    def test_low_altitude_is_enough_only_above_the_minimum(self):
        self.start("WHITE")
        self.player.flight.phase = FlightPhase.CRUISE
        self.player.position = (float(self.player.x), float(self.player.y) + .3, float(self.player.z))
        self.f()
        self.assertIsNone(self.player.motion)
        self.player.flight.phase = FlightPhase.GROUNDED


class ForcedFallTests(FCase):
    def thrown(self, rise: float = 60.0) -> None:
        launch_character(self.enemy, self.player, SimVec3(18.0, rise, 0.0))
        self.seconds(.6)
        self.assertIsInstance(self.player.motion, LaunchedMotion)
        self.assertGreater(self.height(), 3.0)

    def test_all_five_break_a_throw_blast_the_ground_and_get_control_back(self):
        for character_id in ALL:
            with self.subTest(character_id):
                self.start(character_id, 40.0)
                self.thrown()
                self.enemy.position = (self.player.x + 8.0, self.game.world.height_at(self.player.x + 8.0, self.player.z) + .25,
                                       self.player.z)
                self.enemy.vitals.add_status("frozen", 60.0)
                before = self.enemy.vitals.damage_taken
                craters = len(self.game.world.terrain_impacts)
                motion = self.slam()
                self.assertTrue(motion.ballistic)
                self.assertEqual(self.player.movement_state, "DIVING")
                self.assertGreaterEqual(motion.speed, 120.0)
                self.until_done(motion)
                self.assertTrue(motion.impacted)
                self.assertGreater(self.enemy.vitals.damage_taken, before, "real damage")
                self.assertGreater(len(self.game.world.terrain_impacts), craters, "real destruction")
                self.assertEqual(self.player.movement_state, "GROUNDED")
                self.assertAlmostEqual(self.height(), 0.0, delta=.5)
                self.assertAlmostEqual(self.player.pose_root.getP(), 0.0, places=3)
                self.f()  # and it is theirs again: flight, or for Soldier Boy the jump
                self.seconds(.6)
                self.assertEqual(self.player.movement_state, "SUPER_JUMPING" if character_id == "RED" else "FLYING")

    def test_it_is_one_blast_however_often_f_is_pressed_and_never_flight(self):
        for character_id in ALL:
            with self.subTest(character_id):
                self.start(character_id, 300.0)
                self.thrown()
                with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
                    motion = self.slam()
                    for _ in range(round(30.0 / FRAME)):
                        if self.player.motion is not motion:
                            break
                        self.f()
                        self.assertIs(self.player.motion, motion, "the dive is not restarted")
                        self.assertFalse(self.player.flight.is_flying)
                        self.game.update(FRAME)
                    self.assertEqual(blast.call_count, 1)

    def test_the_air_left_after_a_throw_runs_out(self):
        self.start("WHITE", 300.0)
        self.thrown(90.0)
        self.player.release_motion()
        self.assertGreater(self.player.jump_height, 1.5)
        self.f()
        self.assertTrue(self.player.flight.is_flying, "a flyer recovers into flight")
        self.start("RED", 300.0)
        self.thrown(90.0)
        self.player.release_motion()
        self.assertGreater(self.player.jump_height, 1.5)
        motion = self.slam()
        self.assertFalse(self.player.flight.is_flying, "and he never flies: he slams")
        self.until_done(motion)
        self.assertTrue(motion.impacted)

    def test_held_frozen_and_down_it_does_nothing(self):
        for status in ("held", "frozen"):
            with self.subTest(status):
                self.start("WHITE", 300.0)
                self.thrown()
                throw = self.player.motion
                self.player.vitals.add_status(status, 5.0)
                self.f()
                self.assertIs(self.player.motion, throw)
                self.player.vitals.clear_status(status)
        self.start("WHITE", 300.0)
        self.thrown()
        throw = self.player.motion
        self.player.vitals.health = 1.0
        self.combat.hit_character(self.enemy, self.player, 1e9, "physical")
        self.f()
        self.assertIs(self.player.motion, throw, "the fallen simply fall")
        self.player.vitals.downed_for = .01

    def test_no_second_slam_once_on_the_ground_skidding(self):
        self.start("RED", 300.0)
        launch_character(self.enemy, self.player, SimVec3(60.0, 0.0, 0.0))
        for _ in range(240):
            self.game.update(FRAME)
            if self.player.motion is None or self.player.motion.landed:
                break
        if self.player.motion is not None:
            throw = self.player.motion
            self.f()
            self.assertIs(self.player.motion, throw)

    def test_caught_on_the_way_down_it_lets_go_without_a_jump_to_the_ground(self):
        self.start("WHITE", 300.0)
        self.thrown(90.0)
        motion = self.slam()
        self.player.vitals.add_status("held", 1.0)
        height = self.height()
        self.frames(1)
        self.assertIsNot(self.player.motion, motion)
        self.assertGreater(self.height(), height - 1.0, "still up there, in the grip")
        self.assertFalse(motion.impacted)
        self.player.vitals.clear_status("held")

    def test_thrown_again_in_the_dive_it_is_thrown_from_where_it_was(self):
        self.start("WHITE", 300.0)
        self.thrown(90.0)
        self.slam()
        height = self.height()
        launch_character(self.enemy, self.player, SimVec3(0.0, 40.0, 0.0))
        self.assertGreater(self.height(), height - 1.0)
        self.assertIsInstance(self.player.motion, LaunchedMotion)

    def test_an_enemys_sequence_throws_finish_first_then_f_works_and_time_resumes(self):
        for attacker, ability_id in (("GREEN", "high_speed_attack"), ("WHITE", "high_speed_attack"), ("RED", "flying_punch"),
                                     ("BLACK", "high_speed_attack")):
            with self.subTest(attacker):
                self.begin("YELLOW", attacker, 30.0)
                self.tough(self.enemy)
                self.tough(self.player, 1e12)
                self.frames(1)
                self.enemy.powers.abilities[ability_id].press()
                sequence = self.enemy.motion
                self.assertIsNotNone(sequence)
                dived = None
                for _ in range(round(45.0 / FRAME)):
                    if self.enemy.motion is not sequence and not self.combat.time_stopped:
                        break
                    was_thrown = getattr(sequence, "thrown", True)
                    self.f()
                    if isinstance(self.player.motion, ImpactDiveMotion) and dived is None:
                        dived = self.player.motion
                        self.assertTrue(was_thrown, "not while the sequence still has hold of the fight")
                    self.game.update(FRAME)
                self.assertFalse(self.combat.time_stopped, "time resumes")
                self.assertIsNot(self.enemy.motion, sequence)
                self.f()  # if it ended the moment they were thrown, this is the first chance
                if isinstance(self.player.motion, ImpactDiveMotion):
                    dived = self.player.motion
                self.seconds(6.0)  # a thrown body bounces before it settles
                self.assertFalse(self.player.vitals.has("held"))
                if not self.player.flight.is_flying:  # pressing F on the ground is taking off, as it should be
                    self.assertLess(self.height(), 1.0)
                if dived is not None:
                    self.assertTrue(dived.impacted)

    def test_ai_on_the_way_down_uses_the_same_dive_sometimes(self):
        self.begin("WHITE", "BLACK", 200.0, ai_powers=True)
        self.tough(self.enemy)
        self.tough(self.player)
        used = 0
        for _ in range(12):
            launch_character(self.player, self.enemy, SimVec3(0.0, 80.0, 0.0))
            for _ in range(round(6.0 / FRAME)):
                self.game.update(FRAME)
                if isinstance(self.enemy.motion, ImpactDiveMotion):
                    used += 1
                    motion = self.enemy.motion
                    self.assertFalse(self.enemy.flight.is_flying)
                    for _ in range(round(10.0 / FRAME)):
                        if self.enemy.motion is not motion:
                            break
                        self.game.update(FRAME)
                    self.assertTrue(motion.impacted)
                    break
                if self.enemy.motion is None:
                    break
            self.enemy.release_motion()
        self.assertGreater(used, 0)


class SoldierBoyTests(FCase):
    def test_f_on_the_ground_is_a_huge_physical_leap_and_never_flight(self):
        self.start("RED")
        y = float(self.player.y)
        self.f()
        self.assertFalse(self.player.flight.is_flying)
        self.frames(1)
        self.assertLess(float(self.player.y) - y, 8.0, "it starts from where he stands")
        highest = 0.0
        for _ in range(round(25.0 / FRAME)):
            self.game.update(FRAME)
            highest = max(highest, self.height())
            self.assertIs(self.player.flight.phase, FlightPhase.GROUNDED)
            self.assertEqual(self.player.flight.velocity.length(), 0.0)
            if highest > 1000.0:
                break
        self.assertGreater(highest, 1000.0)
        self.until_done(self.slam())

    def test_holding_f_drives_it_on_and_space_in_the_air_still_goes_higher(self):
        self.start("RED")
        self.f()
        self.seconds(3.0)
        tap = self.player.jump_velocity
        self.until_done(self.slam())
        self.game.input("f")
        held_keys["f"] = 1
        self.seconds(3.0)
        held_keys["f"] = 0
        self.game.input("f up")
        self.assertGreater(self.player.jump_velocity, tap + 100.0)
        y = float(self.player.y)
        self.game.input("space")
        held_keys["space"] = 1
        self.seconds(.8)
        held_keys["space"] = 0
        self.game.input("space up")
        self.assertGreater(float(self.player.y), y + 100.0)
        self.until_done(self.slam())

    def test_he_steers_in_the_leap(self):
        self.start("RED")
        self.f()
        self.frames(5)
        z = float(self.player.z)
        held_keys["w"] = 1
        self.seconds(1.0)
        held_keys["w"] = 0
        self.assertGreater(float(self.player.z), z + 5.0)
        self.until_done(self.slam())

    def test_his_stats_are_not_changed_by_any_of_it(self):
        self.start("RED")
        self.combat.apply_settings()
        vitals = self.player.vitals
        before = (vitals.max_health, vitals.resistance, vitals.impact_resistance, vitals.regen,
                  self.player.powers.strength)
        self.into_the_air()
        self.until_done(self.slam())
        held_keys["w"] = held_keys["shift"] = 1
        self.seconds(1.0)
        held_keys["w"] = held_keys["shift"] = 0
        self.assertEqual(before, (vitals.max_health, vitals.resistance, vitals.impact_resistance, vitals.regen,
                                  self.player.powers.strength))


class SpeedTests(FCase):
    def fastest_flight(self) -> float:
        return max(max(body.flight.config.boost_speed, body.flight.config.cruise_speed)
                   for body in self.teams.characters.values() if body.kit.can_fly)

    def run_for(self, seconds: float) -> float:
        held_keys["w"] = held_keys["shift"] = 1
        top = 0.0
        last = (float(self.player.x), float(self.player.z))
        for _ in range(round(seconds / FRAME)):
            self.game.update(FRAME)
            now = (float(self.player.x), float(self.player.z))
            top = max(top, ((now[0] - last[0]) ** 2 + (now[1] - last[1]) ** 2) ** .5 / FRAME)
            last = now
        held_keys["w"] = held_keys["shift"] = 0
        return top

    def test_he_is_set_faster_than_anyone_flies_boosted(self):
        self.start("RED")
        self.frames(1)
        self.assertGreater(self.player.ground.max_running_speed, self.fastest_flight())

    def test_he_really_covers_the_ground_that_fast(self):
        self.start("RED")
        self.stand(self.player, -4000.0, -4000.0)
        self.frames(1)
        self.assertGreater(self.run_for(2.5), self.fastest_flight())
        self.assertLess(self.player.jump_height, 1.0)
        self.assertFalse(self.player.flight.is_flying)

    def test_it_stays_true_whatever_flight_settings_are_changed_to(self):
        self.start("RED")
        self.teams.state.settings("WHITE")["flight_speed"] = "FAST" if False else self.teams.state.settings("WHITE")["flight_speed"]
        for character in self.teams.characters.values():
            if character.kit.can_fly:
                character.flight.config.boost_speed = 12345.0
        self.frames(1)
        self.assertGreater(self.player.ground.max_running_speed, 12345.0)

    def test_only_his_ground_speed(self):
        self.start("RED")
        self.frames(1)
        self.assertFalse(self.player.flight.allowed)
        red_flight = self.player.flight.config.boost_speed
        white = self.teams.characters["WHITE"]
        self.assertLess(white.ground.max_running_speed, self.player.ground.max_running_speed)
        self.assertEqual(self.player.flight.config.boost_speed, red_flight)

    def test_he_stops_again_when_he_lets_go(self):
        self.start("RED")
        self.stand(self.player, -4000.0, -4000.0)
        self.run_for(1.0)
        self.seconds(1.0)
        self.assertLess(self.player.ground.velocity.length(), 1.0)

    def test_walking_is_still_walking(self):
        self.start("RED")
        self.frames(1)
        held_keys["w"] = 1
        z = float(self.player.z)
        self.seconds(.5)
        held_keys["w"] = 0
        self.assertLess(float(self.player.z) - z, self.player.ground.walk_speed)

    def test_at_that_speed_a_vehicle_on_the_ground_is_hit_and_not_run_through(self):
        self.start("RED")
        vehicle = next(item for item in self.game.landmarks.items
                       if getattr(item, "explosive", False) and not item.health.broken)
        x, z = float(vehicle.x), float(vehicle.z)
        self.stand(self.player, x, z - 150.0)
        self.frames(1)
        before = vehicle.health.health
        self.run_for(1.2)
        self.assertLess(vehicle.health.health, before, "it was struck, at any frame rate")

    def test_at_that_speed_a_tree_is_not_run_through(self):
        self.start("RED")
        tree = fresh_tree(self.game, minimum=8.0)
        self.stand(self.player, float(tree.x), float(tree.z) - 150.0)
        self.frames(1)
        self.run_for(1.0)
        self.assertLess(float(self.player.z), float(tree.z) + 1.0, "stopped by it")

    def test_ai_soldier_boy_runs_at_it_too(self):
        self.begin("YELLOW", "RED", 3000.0, ai_powers=False)
        self.tough(self.player)
        red = self.enemy
        red.intent = None
        red.next_decision = 0.0
        z = float(red.z)
        top = 0.0
        last = (float(red.x), float(red.z))
        for _ in range(round(3.0 / FRAME)):
            self.game.update(FRAME)
            now = (float(red.x), float(red.z))
            top = max(top, ((now[0] - last[0]) ** 2 + (now[1] - last[1]) ** 2) ** .5 / FRAME)
            last = now
        self.assertGreater(top, red.ground.walk_speed)
        self.assertLess(abs(float(red.z) - float(self.player.z)), abs(z - float(self.player.z)))
        self.assertGreater(red.ground.max_running_speed, self.fastest_flight())
        self.assertFalse(red.flight.is_flying)


class AITests(FCase):
    def test_ai_uses_the_same_slam_for_all_five(self):
        for character_id in ALL:
            with self.subTest(character_id):
                self.begin("YELLOW" if character_id != "YELLOW" else "WHITE", character_id, 30.0, ai_powers=True)
                self.tough(self.player)
                self.tough(self.enemy)
                self.teams._next_cinematic = 1e12
                ai = self.enemy
                floor = self.game.world.height_at(ai.x, ai.z)
                ai.position = (float(self.player.x) + 5.0, floor + 60.0, float(self.player.z))
                if character_id == "RED":
                    ai.jump_height = 60.0
                    ai.jump_velocity = 1.0
                else:
                    ai.flight.phase = FlightPhase.CRUISE
                ai._ai_next_attack = 0.0
                ai.intent = None
                self.teams.attack_tokens.holders.clear()
                with mock.patch.object(ai._rng, "random", return_value=0.0):
                    self.game.update(FRAME)
                motion = ai.motion
                self.assertIsInstance(motion, ImpactDiveMotion)
                self.assertIsInstance(motion.ability, ImpactDive)
                before = self.player.vitals.damage_taken
                grounded = False
                for _ in range(round(10.0 / FRAME)):
                    if ai.motion is not motion:
                        break
                    self.game.update(FRAME)
                    if motion.impacted and ai.motion is motion:
                        grounded = ai.flight.phase is FlightPhase.GROUNDED
                self.assertTrue(grounded, "on the ground afterwards: what it does next is its own choice")
                self.assertIsNot(ai.motion, motion)
                self.assertTrue(motion.impacted, "it hit the ground")
                self.assertGreater(self.player.vitals.damage_taken, before)

    def test_the_squad_does_not_have_it(self):
        self.begin("GREEN", "BLACK", 100.0)
        self.tap("1")
        for member in self.teams.summons:
            self.assertNotIn("impact_dive", member.powers.abilities)

    def test_the_ai_jump_and_slam_never_turn_into_flight_for_him(self):
        self.begin("YELLOW", "RED", 60.0, ai_powers=True)
        self.tough(self.player)
        self.tough(self.enemy)
        for _ in range(round(30.0 / FRAME)):
            self.game.update(FRAME)
            self.player.vitals.health = self.player.vitals.max_health
            self.assertFalse(self.enemy.flight.is_flying)


if __name__ == "__main__":
    unittest.main()
