"""Omni-Man's key 4 from start to finish, and the people it brings with it, on the real game loop."""

from __future__ import annotations

import unittest
from unittest import mock

from characters.roster import KITS, SQUAD_KITS
from characters.sentry_clone import SQUAD_PALETTES
from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM
from game_fixture import FRAME
from movement.flight_physics import FlightPhase
from power_fixture import fresh_tree
from powers.common import LaunchedMotion
from powers.omni_man import (ASSAULT, BLAST_SHARE, BURN, CLOSE, FOLLOW, GRIP, IMPACTS, RUSH, SQUAD_SECONDS,
                             TripleImpactExecution)
from powers.vitals import EXPLOSION, HEAT, PHYSICAL
from test_gameplay_control_update import LiveCase

VILTRUMITES = tuple(f"VILTRUMITE_{index}" for index in range(1, 6))


class Key4Case(LiveCase):
    def start(self, distance: float = 60.0, enemy: str = "BLACK", flying_at: float | None = None):
        self.begin("GREEN", enemy, distance)
        self.tough(self.enemy)
        self.tough(self.player)
        if flying_at is not None:
            floor = self.game.world.height_at(self.enemy.x, self.enemy.z)
            self.enemy.position = (float(self.enemy.x), floor + flying_at, float(self.enemy.z))
            self.enemy.flight.phase = FlightPhase.CRUISE
        self.frames(1)
        self.summon = self.player.powers.abilities["squad_summon"]
        self.key4 = self.player.powers.abilities["speed_execution"]

    def press(self) -> TripleImpactExecution:
        self.game.input("4")
        self.game.input("4 up")
        self.assertIsInstance(self.player.motion, TripleImpactExecution, "at once")
        self.assertTrue(self.combat.time_stopped, "at once")
        return self.player.motion

    def finish(self, motion, limit: float = 40.0) -> list:
        phases = []
        for _ in range(round(limit / FRAME)):
            if self.player.motion is not motion:
                return phases
            if not phases or phases[-1] != motion.phase:
                phases.append(motion.phase)
            self.assertTrue(self.combat.time_stopped)
            self.game.update(FRAME)
        self.fail(f"never finished: {phases}")

    def assert_handed_back(self) -> None:
        self.assertIsNone(self.player.motion)
        self.assertFalse(self.combat.time_stopped)
        self.assertFalse(self.game.hud.vision_overlay.enabled)
        self.assertEqual(len(self.combat._beams), self.beams_free)
        self.assertFalse(self.key4.flames.entity.visible)


class SequenceTests(Key4Case):
    def test_every_phase_in_order(self):
        self.start()
        phases = self.finish(self.press())
        self.assertEqual(phases, [RUSH, FOLLOW, RUSH, FOLLOW, RUSH, FOLLOW, ASSAULT, CLOSE, BURN, GRIP, "aftermath"])
        self.assert_handed_back()

    def test_three_separate_impacts_at_three_places_in_three_directions(self):
        self.start()
        with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
            motion = self.press()
            self.finish(motion)
        self.assertEqual(motion.impacts, 3)
        points = motion.impact_points
        for first, second in ((0, 1), (1, 2), (0, 2)):
            self.assertGreater((points[first] - points[second]).length(), 20.0, "somewhere else entirely")
            a, b = motion.throw_directions[first], motion.throw_directions[second]
            self.assertLess(a.x * b.x + a.y * b.y + a.z * b.z, .7, "and off in another direction")
        explosions = [call for call in blast.call_args_list if call.kwargs["kind"] == EXPLOSION]
        self.assertEqual(len(explosions), 3)
        self.assertEqual([call.args[1] for call in explosions], points, "exactly where each one landed")
        self.assertEqual(len({call.args[2] for call in explosions}), 3, "and each its own size")

    def test_it_is_caught_in_the_air_each_time(self):
        self.start()
        motion = self.press()
        impacts = 0
        while motion.impacts < len(IMPACTS):
            self.game.update(FRAME)
            if motion.impacts != impacts:
                impacts = motion.impacts
                self.assertIsInstance(self.enemy.motion, LaunchedMotion)
                self.assertFalse(self.enemy.motion.landed)
            elif isinstance(self.enemy.motion, LaunchedMotion):
                self.assertFalse(self.enemy.motion.landed, "it never reaches the ground between hits")
        self.player.release_motion()

    def test_range_sets_the_size_of_the_explosions(self):
        self.start()
        self.combat.settings.set("GREEN", "speed_execution", "range", 500)
        with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
            self.finish(self.press())
        self.assertAlmostEqual(blast.call_args_list[0].args[2], 50.0, delta=.1)

    def test_damage_is_real_and_every_part_of_it_is_there(self):
        self.start()
        self.combat.settings.set("GREEN", "speed_execution", "damage", 2000)
        self.enemy.vitals.resistance = 0.0
        total = 2000.0 * self.player.powers.strength
        with mock.patch.object(self.combat, "hit_character", wraps=self.combat.hit_character) as hit:
            motion = self.press()
            self.finish(motion)
            kinds = [call.args[3] for call in hit.call_args_list if call.args[1] is self.enemy]
        self.assertGreaterEqual(kinds.count(PHYSICAL), 3 + 10)
        self.assertGreaterEqual(kinds.count(HEAT), 8, "the fire, in ticks")
        taken = self.enemy.vitals.damage_taken
        self.assertAlmostEqual(taken, total * .9, delta=total * .05, msg="all but the landing so far")
        self.assertGreater(motion.fire_dealt, 0.0)
        self.run_until_settled(self.enemy, 70.0)
        self.assertAlmostEqual(self.enemy.vitals.damage_taken, total, delta=total * .05)

    def test_blast_share_goes_to_whoever_else_is_near(self):
        self.start()
        other = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.stand(other, 3.0, 62.0)
        self.tough(other)
        other.vitals.resistance = 0.0
        self.assertGreater(BLAST_SHARE, 0.0)
        self.finish(self.press())
        self.assertGreater(other.vitals.damage_taken, 0.0)

    def test_it_breaks_the_world_around_it(self):
        self.start()
        tree = fresh_tree(self.game, minimum=8.0)
        self.stand(self.enemy, tree.x + 20.0, tree.z)
        self.stand(self.player, tree.x + 20.0, tree.z - 60.0)
        tree_id = tree.tree_id
        craters = len(self.game.world.terrain_impacts)
        self.finish(self.press())
        state = self.game.world.tree_states.get(tree_id, {})
        self.assertTrue(state.get("destroyed") or tree.is_empty() or tree.tree_health < tree.tree_max_health)
        self.assertGreater(len(self.game.world.terrain_impacts), craters)

    def test_it_reaches_a_flying_enemy_too(self):
        self.start(flying_at=150.0)
        motion = self.press()
        self.finish(motion)
        self.assertEqual(motion.impacts, 3)
        self.assertLess(motion.elapsed, 12.0, "and each catch is quick, not a long chase")
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assert_handed_back()

    def test_terrain_in_the_way_does_not_stop_it(self):
        self.start()
        self.game.world.terrain_impact(self.enemy.position, radius=20.0, depth=10.0, intensity=1.0, surface="test")
        self.stand(self.enemy, float(self.enemy.x), float(self.enemy.z))
        motion = self.press()
        self.finish(motion)
        self.assertEqual(motion.impacts, 3)

    def test_the_throw_lands_with_an_impact_a_long_way_off(self):
        self.start()
        craters = len(self.game.world.terrain_impacts)
        motion = self.press()
        self.finish(motion)
        thrown = self.enemy.motion
        self.assertIsInstance(thrown, LaunchedMotion)
        self.assertGreater(thrown.velocity.length(), 200.0, "still going fast, after a third of a second of drag")
        at = (float(self.enemy.x), float(self.enemy.z))
        self.assertFalse(self.combat.time_stopped, "the world runs again while it flies")
        with mock.patch.object(self.combat, "burst", wraps=self.combat.burst) as burst:
            self.run_until_settled(self.enemy, 70.0)
        self.assertTrue(thrown.landed)
        self.assertGreaterEqual(burst.call_count, 1, "the final impact effect")
        self.assertGreater(len(self.game.world.terrain_impacts), craters)
        moved = ((float(self.enemy.x) - at[0]) ** 2 + (float(self.enemy.z) - at[1]) ** 2) ** .5
        self.assertGreater(moved, 100.0, "a considerable distance")


class AssaultTests(Key4Case):
    def to_assault(self) -> TripleImpactExecution:
        motion = self.press()
        while motion.phase != ASSAULT:
            self.game.update(FRAME)
        return motion

    def test_exactly_five_viltrumites_and_invincible_and_they_appear_near_the_target(self):
        self.start()
        motion = self.to_assault()
        self.assertEqual(len(motion.squad), 6)
        self.assertEqual(sum(member.display_name == "VILTRUMITE" for member in motion.squad), 5)
        self.assertEqual(sum(member.display_name == "INVINCIBLE" for member in motion.squad), 1)
        self.frames(20)
        for member in motion.squad:
            gap = ((float(member.x) - motion.anchor.x) ** 2 + (float(member.z) - motion.anchor.z) ** 2) ** .5
            self.assertLess(gap, 13.0, "around the target")
        self.player.release_motion()

    def test_it_lasts_exactly_three_seconds(self):
        self.start()
        motion = self.to_assault()
        frames = 0
        while motion.phase == ASSAULT:
            self.game.update(FRAME)
            frames += 1
        self.assertAlmostEqual(frames * FRAME, SQUAD_SECONDS, delta=FRAME * 2)
        self.player.release_motion()

    def test_every_one_of_them_attacks_from_their_own_side_one_at_a_time(self):
        self.start()
        motion = self.to_assault()
        attackers, directions = {}, set()
        most_at_once = 0
        kinds = set()
        while motion.phase == ASSAULT:
            self.game.update(FRAME)
            if motion.attack is not None:
                member = motion.attack[0]
                attackers[id(member)] = attackers.get(id(member), 0) + 1
                kinds.add(motion.attack[1])
                dx, dz = float(member.x) - motion.anchor.x, float(member.z) - motion.anchor.z
                directions.add((dx > 0.0, dz > 0.0))
            close = sum(((float(member.x) - float(self.enemy.x)) ** 2 + (float(member.z) - float(self.enemy.z)) ** 2) ** .5
                        < 3.2 for member in motion.squad)
            most_at_once = max(most_at_once, close)
        self.assertEqual(len(attackers), 6, "all of them")
        self.assertEqual(len(kinds), 4, "punches, kicks, grapples and charges")
        self.assertGreaterEqual(len(directions), 3, "from different directions")
        self.assertLessEqual(most_at_once, 2, "they do not pile into each other")
        self.assertGreaterEqual(motion.squad_hits, 12)
        self.player.release_motion()

    def test_after_three_seconds_they_stop(self):
        self.start()
        motion = self.to_assault()
        while motion.phase == ASSAULT:
            self.game.update(FRAME)
        hits = motion.squad_hits
        self.finish(motion)
        self.assertEqual(motion.squad_hits, hits)

    def test_never_omni_man_or_each_other_or_anyone_but_the_target(self):
        self.start()
        self.teams.state.assignment["WHITE"] = MY_TEAM
        self.teams._apply_roster()
        ally = self.teams.characters["WHITE"]
        self.stand(ally, 200.0, 200.0)
        self.tough(ally)
        self.finish(self.press())
        self.assertEqual(self.player.vitals.damage_taken, 0.0)
        self.assertEqual(ally.vitals.damage_taken, 0.0)
        for member in self.teams._squad:
            self.assertEqual(member.vitals.damage_taken, 0.0)


class SeenByThePlayerTests(Key4Case):
    def test_he_and_the_camera_are_on_the_assault_while_it_happens(self):
        from math import atan2, degrees
        self.start()
        motion = self.press()
        while not (motion.phase == ASSAULT and motion.phase_time > .6):
            self.game.update(FRAME)
        gap = ((float(self.player.x) - float(self.enemy.x)) ** 2 + (float(self.player.y) - float(self.enemy.y)) ** 2
               + (float(self.player.z) - float(self.enemy.z)) ** 2) ** .5
        self.assertLess(gap, 20.0, "close enough to see")
        wanted = degrees(atan2(float(self.enemy.x) - float(self.player.x), float(self.enemy.z) - float(self.player.z)))
        turn = (wanted - self.game.camera.yaw + 180.0) % 360.0 - 180.0
        self.assertLess(abs(turn), 20.0, "and looking at it")
        self.player.release_motion()

    def test_the_camera_is_free_again_afterwards(self):
        self.start()
        self.finish(self.press())
        self.frames(2)
        self.assertFalse(self.game.camera.tracking)

    def test_an_ai_omni_mans_execution_leaves_the_players_camera_alone(self):
        self.begin("YELLOW", "GREEN", 60.0, ai_powers=False)
        self.tough(self.player)
        self.tough(self.enemy)
        ally = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = MY_TEAM
        self.teams._apply_roster()
        self.stand(ally, 0.0, 40.0)
        self.tough(ally)
        self.game.camera.yaw = 90.0
        with mock.patch.object(self.enemy.powers.abilities["speed_execution"], "target", return_value=ally):
            self.enemy.powers.abilities["speed_execution"].press()
        self.frames(60)
        self.assertEqual(self.game.camera.yaw, 90.0)
        self.enemy.release_motion()


class SquadManagementTests(Key4Case):
    def test_with_no_squad_out_a_temporary_one_comes_and_goes(self):
        self.start()
        motion = self.press()
        self.assertEqual(self.teams.summons, [])
        while motion.phase != ASSAULT:
            self.game.update(FRAME)
        self.assertEqual(len(motion.temporary), 6)
        self.assertEqual(len(self.teams.summons), 6)
        self.assertFalse(self.summon.active, "key 1 knows nothing about these")
        self.finish(motion)
        self.assertEqual(self.teams.summons, [], "all gone")
        self.assertTrue(all(member.parked for member in self.teams._squad))
        self.assertFalse(self.summon.active)
        self.tap("1")
        self.assertEqual(len(self.teams.summons), 6, "and key 1 works as ever")

    def test_a_squad_called_with_key_1_is_reused_and_kept(self):
        self.start()
        self.tap("1")
        called = list(self.summon.members)
        motion = self.press()
        self.finish(motion)
        self.assertEqual({id(member) for member in motion.squad}, {id(member) for member in called}, "the same six")
        self.assertEqual(motion.temporary, [])
        self.assertTrue(self.summon.active, "still called")
        self.assertEqual(self.summon.members, called)
        self.assertEqual(self.teams.summons, called)
        self.assertTrue(all(not member.parked for member in called))
        self.tap("1")
        self.assertEqual(self.teams.summons, [], "and key 1 still sends them away")

    def test_a_squad_short_of_members_is_made_up_to_six_and_only_those_leave(self):
        self.start()
        self.tap("1")
        called = list(self.summon.members)
        fallen = called[2]
        fallen.vitals.take(1e12)
        fallen.on_downed()
        self.seconds(3.5)
        self.assertEqual(len(self.summon.members), 5)
        motion = self.press()
        while motion.phase != ASSAULT:
            self.game.update(FRAME)
        self.assertEqual(len(motion.squad), 6)
        self.assertEqual(motion.temporary, [fallen])
        self.assertFalse(fallen.vitals.downed, "on their feet again")
        self.finish(motion)
        self.assertTrue(fallen.parked)
        self.assertEqual(len(self.summon.members), 5)
        self.assertEqual(self.summon.hud_state(), "5/6")

    def test_no_new_bodies_are_ever_made(self):
        self.start()
        self.finish(self.press())
        bodies = {id(member) for member in self.teams._squad}
        self.assertEqual(len(bodies), 6)
        for _ in range(3):
            self.enemy.release_motion()
            self.stand(self.enemy, float(self.player.x), float(self.player.z) + 60.0)
            self.finish(self.press())
            self.assertEqual({id(member) for member in self.teams._squad}, bodies)


class SafetyTests(Key4Case):
    def test_a_target_dying_at_any_point_never_leaves_anything_behind(self):
        for frames_in in (1, 8, 20, 35, 60, 120, 200, 260, 300):
            with self.subTest(frames_in=frames_in):
                self.start()
                self.press()
                self.frames(frames_in)
                if self.player.motion is not None:
                    self.enemy.vitals.take(1e12)
                    self.enemy.on_downed()
                self.seconds(2.0)
                self.assert_handed_back()
                self.assertEqual(self.teams.summons, [])
                self.enemy.vitals.downed_for = 0.0
                self.enemy.vitals.health = self.enemy.vitals.max_health

    def test_a_target_despawning_part_way_is_safe(self):
        for frames_in in (5, 60, 200):
            with self.subTest(frames_in=frames_in):
                self.start()
                self.press()
                self.frames(frames_in)
                self.teams.state.assignment["BLACK"] = AVAILABLE
                self.teams._apply_roster()
                self.seconds(2.0)
                self.assert_handed_back()
                self.assertEqual(self.teams.summons, [])

    def test_switching_character_part_way_is_safe_and_keeps_a_key_1_squad(self):
        self.start()
        self.tap("1")
        called = list(self.summon.members)
        self.press()
        self.frames(100)
        omni = self.player
        self.teams.state.assignment["WHITE"] = MY_TEAM
        self.teams.swap("WHITE", save=False)
        self.assertIsNone(omni.motion)
        self.assertFalse(self.combat.time_stopped)
        self.assertEqual(self.teams.summons, called)
        self.teams.swap("GREEN", save=False)

    def test_a_manual_lock_comes_first_and_is_kept_all_the_way_through(self):
        self.start(distance=90.0)
        near = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.stand(near, 10.0, 0.0)
        self.tough(near)
        self.frames(1)
        self.game.input("q")
        while self.combat.targets.manual is not self.enemy:
            self.game.input("scroll up")
        motion = self.press()
        self.assertIs(motion.target, self.enemy)
        self.finish(motion)
        self.assertEqual(motion.impacts, 3)
        self.assertIs(self.combat.targets.manual, self.enemy)
        self.game.input("q")

    def test_nearest_without_a_lock_and_never_an_ally(self):
        self.start(distance=90.0)
        ally = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = MY_TEAM
        self.teams._apply_roster()
        self.stand(ally, 4.0, 0.0)
        self.combat.targets.clear()
        self.assertIs(self.press().target, self.enemy)
        self.player.release_motion()

    def test_keys_cannot_interrupt_it(self):
        self.start()
        motion = self.press()
        for key in ("1", "2", "3", "4", "t", "q", "="):
            self.tap(key)
            self.assertIs(self.player.motion, motion, key)
        self.assertFalse(self.summon.active)
        self.player.release_motion()
        self.assert_handed_back()

    def test_the_world_stands_still_and_then_carries_on(self):
        self.begin("GREEN", "BLACK", 60.0, ai_powers=True)
        self.tough(self.enemy)
        self.tough(self.player)
        other = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.stand(other, 400.0, 400.0)
        self.tough(other)
        self.teams._next_cinematic = 1e9
        self.frames(20)
        sky = self.game.environment._time
        self.game.input("4")
        self.game.input("4 up")
        motion = self.player.motion
        bystander = other if motion.target is not other else self.enemy
        where = (float(bystander.x), float(bystander.y), float(bystander.z))
        while self.player.motion is motion:
            self.game.update(FRAME)
            if self.player.motion is motion:
                self.assertEqual((float(bystander.x), float(bystander.y), float(bystander.z)), where)
                self.assertEqual(self.game.environment._time, sky)
        self.seconds(1.0)
        self.assertGreater(self.game.environment._time, sky)

    def test_budgets_hold_over_repeated_use(self):
        self.start()
        puffs = self.combat.puffs
        total = len(puffs.free) + len(puffs.live)
        for _ in range(3):
            self.enemy.release_motion()
            self.stand(self.enemy, float(self.player.x), float(self.player.z) + 60.0)
            self.finish(self.press())
            self.seconds(2.0)
        self.assertEqual(len(puffs.free) + len(puffs.live), total)
        self.assertEqual(len(self.combat._beams), self.beams_free)
        self.assertLessEqual(len(self.game.world.debris), self.game.world.debris_budget.maximum_live_pieces)
        self.assertEqual(len(self.teams._squad), 6)


class AppearanceTests(unittest.TestCase):
    def test_five_viltrumites_and_invincible_are_all_there(self):
        self.assertEqual(set(SQUAD_KITS), {*VILTRUMITES, "INVINCIBLE"})
        self.assertEqual({palette.name for palette in SQUAD_PALETTES}, set(SQUAD_KITS))

    def test_every_one_has_their_own_skin_face_build_and_outfit(self):
        kits = [SQUAD_KITS[name] for name in VILTRUMITES]
        self.assertEqual(len({kit.skin for kit in kits}), 5, "skin tones")
        self.assertEqual(len({kit.body_scale for kit in kits}), 5, "builds")
        self.assertEqual(len({kit.parts for kit in kits}), 5, "faces, hair and uniforms")

    def test_faces_and_hair_really_differ_part_by_part(self):
        heads = []
        for name in VILTRUMITES:
            heads.append({(part[0], part[2], part[3]) for part in SQUAD_KITS[name].parts
                          if part[0] == "body" and part[2][1] > 2.15})
        for first in range(5):
            for second in range(first + 1, 5):
                self.assertGreater(len(heads[first] ^ heads[second]), 8, (first, second))

    def test_they_are_in_white_not_omni_mans_red(self):
        palette = {palette.name: palette for palette in SQUAD_PALETTES}
        for name in VILTRUMITES:
            for role in ("suit", "suit_light", "suit_shadow", "accent", "trim", "cape"):
                red, green, blue = getattr(palette[name], role)
                self.assertLess(max(red, green, blue) - min(red, green, blue), .06, f"{name} {role} is a neutral")
                self.assertGreater(min(red, green, blue), .6, f"{name} {role} is pale")
            for part in SQUAD_KITS[name].parts:
                red, green, blue = part[4]
                self.assertFalse(red > .55 and green < .25 and blue < .25, f"{name}: no red on the costume")
        omni = {part[4] for part in KITS["GREEN"].parts}
        self.assertTrue(omni - {part[4] for name in VILTRUMITES for part in SQUAD_KITS[name].parts},
                        "not simply his parts")

    def test_invincible_is_nothing_like_them(self):
        palette = {palette.name: palette for palette in SQUAD_PALETTES}["INVINCIBLE"]
        red, green, blue = palette.suit_light
        self.assertTrue(red > .8 and green > .6 and blue < .3, "yellow")
        red, green, blue = palette.suit
        self.assertTrue(blue > red * 2.0, "blue")
        kit = SQUAD_KITS["INVINCIBLE"]
        self.assertFalse(kit.cape)
        self.assertTrue(any(part[0] == "face" for part in kit.parts), "his goggles")

    def test_the_others_are_untouched(self):
        for kit in KITS.values():
            self.assertIsNone(kit.skin)


class PowersOfTheSquadTests(Key4Case):
    def test_they_have_their_own_grapple_and_throw_with_real_damage(self):
        self.start(distance=8.0)
        self.tap("1")
        member = self.summon.members[0]
        self.assertIn("grab", member.powers.abilities)
        self.assertIn("melee", member.powers.abilities)
        self.assertIn("flight_charge", member.powers.abilities)
        grab = member.powers.abilities["grab"]
        self.enemy.vitals.resistance = 0.0
        grab.press()
        self.assertIs(grab.held, self.enemy)
        self.frames(5)
        self.assertTrue(self.enemy.vitals.has("held"))
        grab.release()
        self.assertIsNone(grab.held)
        self.assertFalse(self.enemy.vitals.has("held"))
        self.assertGreater(self.enemy.moving_velocity.length(), 1.0, "thrown")

    def test_ai_grapples_of_its_own_accord(self):
        self.start(distance=20.0)
        self.tap("1")
        grabs = []
        for member in self.summon.members:
            ability = member.powers.abilities["grab"]

            def spy(ability=ability, real=ability.press):
                grabs.append(ability)
                return real()
            ability.press = spy
        self.seconds(40.0)
        for member in self.summon.members:
            member.powers.abilities["grab"].__dict__.pop("press", None)
        self.assertGreater(len(grabs), 0)

    def test_they_share_his_traits(self):
        self.start()
        self.tap("1")
        member = self.summon.members[0]
        self.assertEqual(member.vitals.resistance, self.player.vitals.resistance)
        self.assertEqual(member.vitals.knockback_resistance, self.player.vitals.knockback_resistance)
        self.assertTrue(member.flight_allowed)


class SquadHealthTests(Key4Case):
    def configured(self) -> float:
        return self.combat.settings.get("GREEN", "character", "health")

    def members_by_name(self):
        viltrumites = [member for member in self.summon.members if member.display_name == "VILTRUMITE"]
        mark = next(member for member in self.summon.members if member.display_name == "INVINCIBLE")
        return viltrumites, mark

    def test_a_quarter_and_a_half_of_his_maximum_at_any_setting(self):
        for health in (1000, 1250, 3777, 100000):
            with self.subTest(health=health):
                self.start()
                self.combat.settings.set("GREEN", "character", "health", health)
                self.tap("1")
                viltrumites, mark = self.members_by_name()
                self.assertEqual(len(viltrumites), 5)
                for member in viltrumites:
                    self.assertAlmostEqual(member.vitals.max_health, health * .005)
                    self.assertAlmostEqual(member.vitals.health, health * .005)
                self.assertAlmostEqual(mark.vitals.max_health, health * .05)
                self.assertAlmostEqual(mark.vitals.health, health * .05)
                self.tap("1")

    def test_it_comes_from_his_maximum_and_not_his_current_health(self):
        self.start()
        self.combat.apply_settings()
        full = self.configured()
        self.player.vitals.health = self.player.vitals.max_health * .1
        self.tap("1")
        viltrumites, mark = self.members_by_name()
        self.assertAlmostEqual(viltrumites[0].vitals.max_health, full * .005)
        self.assertAlmostEqual(mark.vitals.max_health, full * .05)

    def test_his_own_health_and_everyone_elses_stay_as_they_were(self):
        self.start()
        self.combat.apply_settings()
        before = {cid: (body.vitals.max_health, body.vitals.health, body.vitals.regen)
                  for cid, body in self.teams.characters.items()}
        self.tap("1")
        self.seconds(.2)
        self.tap("1")
        self.assertEqual(before, {cid: (body.vitals.max_health, body.vitals.health, body.vitals.regen)
                                  for cid, body in self.teams.characters.items()})

    def test_none_of_them_ever_recovers_on_its_own(self):
        self.start()
        self.tap("1")
        for member in self.summon.members:
            self.assertEqual(member.vitals.regen, 0.0)
            self.assertEqual(member.powers.absorb_rate, 0.0)
            member.vitals.take(member.vitals.max_health * 2.0 / (1.0 - member.vitals.resistance / 100.0) * .25)
        hurt = [member.vitals.health for member in self.summon.members]
        self.assertTrue(all(0.0 < health < member.vitals.max_health
                            for health, member in zip(hurt, self.summon.members)))
        self.seconds(20.0)
        for health, member in zip(hurt, self.summon.members):
            self.assertLessEqual(member.vitals.health, health)

    def test_changing_any_setting_never_refills_them(self):
        self.start()
        self.tap("1")
        member = self.summon.members[0]
        member.vitals.health = member.vitals.max_health * .4
        self.combat.apply_settings()
        self.game.apply_sentry_config()
        self.assertAlmostEqual(member.vitals.health, member.vitals.max_health * .4)
        self.assertEqual(member.vitals.regen, 0.0)
        self.combat.settings.set("GREEN", "character", "healing_speed", 100)
        self.combat.apply_settings()
        self.assertEqual(member.vitals.regen, 0.0, "his healing setting is his alone")

    def test_no_cinematic_or_time_stop_restores_them(self):
        self.start()
        self.tap("1")
        hurt = {id(member): member.vitals.max_health * .3 for member in self.summon.members}
        for member in self.summon.members:
            member.vitals.health = hurt[id(member)]
        self.tap("t")
        self.seconds(2.0)
        self.combat.end_world_stop()
        motion = self.player.powers.slots["4"]
        motion.press()
        while self.player.motion is not None:
            self.game.update(FRAME)
        for member in self.summon.members:
            self.assertLessEqual(member.vitals.health, hurt[id(member)], "a squad he called keeps its wounds")

    def test_a_new_squad_is_a_full_one_every_time(self):
        self.start()
        for _ in range(3):
            self.tap("1")
            viltrumites, mark = self.members_by_name()
            for member in viltrumites:
                self.assertAlmostEqual(member.vitals.health, self.configured() * .005)
                member.vitals.health *= .5
            self.assertAlmostEqual(mark.vitals.health, self.configured() * .05)
            self.tap("1")

    def test_they_really_lose_health_when_attacked(self):
        self.start()
        self.tap("1")
        for member in self.summon.members:
            before = member.vitals.health
            self.combat.hit_character(self.enemy, member, 50.0, PHYSICAL)
            self.assertLess(member.vitals.health, before)

    def test_the_defeated_stop_fighting_and_leave(self):
        self.begin("GREEN", "BLACK", 40.0, ai_powers=False)
        self.tough(self.enemy)
        self.tap("1")
        summon = self.player.powers.abilities["squad_summon"]
        fallen = summon.members[0]
        self.seconds(1.0)
        self.combat.hit_character(None, fallen, 1e12, PHYSICAL)  # no attacker: AI's damage has a limit per second
        self.assertTrue(fallen.vitals.downed)
        self.assertEqual(fallen.vitals.health, 0.0)
        self.assertIsNone(fallen._ai_move)
        presses = []
        melee = fallen.powers.abilities["melee"]

        def spy(real=melee.press):
            presses.append(1)
            return real()
        melee.press = spy
        fallen._ai_next_attack = 0.0
        self.seconds(2.0)
        melee.__dict__.pop("press", None)
        self.assertEqual(presses, [], "no more commands")
        self.assertFalse(fallen.vitals.health > 0.0, "not coming back")
        self.seconds(1.5)
        self.assertTrue(fallen.parked, "gone, by the same way out as any other")
        self.assertNotIn(fallen, self.combat.in_world)
        self.assertEqual(len(summon.members), 5)

    def test_a_fallen_one_does_not_get_up_again_however_long_it_is_left(self):
        self.start()
        self.tap("1")
        fallen = self.summon.members[0]
        fallen.vitals.take(1e12)
        fallen.on_downed()
        self.seconds(12.0)
        self.assertEqual(fallen.vitals.health, 0.0)
        self.assertTrue(fallen.parked)


if __name__ == "__main__":
    unittest.main()
