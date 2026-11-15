"""Mark, and only Mark, guards Omni-Man: attacked, grabbed, surrounded and critically hurt, on the real game loop."""

from __future__ import annotations

import unittest

from config.character_roster import ENEMY_TEAM, MY_TEAM
from game_fixture import FRAME
from movement.flight_physics import Vec3 as SimVec3
from powers.aiming import center_of, trace
from powers.common import LungeMotion
from test_gameplay_control_update import LiveCase


class GuardCase(LiveCase):
    def squad_with(self, player: str = "GREEN", enemy: str = "WHITE", distance: float = 50.0):
        self.begin(player, enemy, distance)
        self.leader = self.teams.characters["GREEN"]
        self.tough(self.enemy)
        if self.leader is not self.player:
            self.tough(self.leader)
        self.tough(self.player)
        self.combat.ai_powers_enabled = False  # the enemy does what each test tells it to
        self.teams.deploy_squad(self.leader)
        self.teams._apply_roster()
        self.mark = next(member for member in self.teams.summons if member.palette.name == "INVINCIBLE")
        self.others = [member for member in self.teams.summons if member is not self.mark]
        for member in self.teams.summons:  # sturdy enough for the test to watch what they choose
            self.tough(member)
        self.addCleanup(lambda: self.teams.withdraw_squad(list(self.teams.summons)))

    def gap(self, a, b) -> float:
        return (center_of(a) - center_of(b)).length()

    def more_enemies(self, *ids) -> list:
        bodies = []
        for index, character_id in enumerate(ids):
            self.teams.state.assignment[character_id] = ENEMY_TEAM
            self.teams._apply_roster()
            body = self.teams.characters[character_id]
            self.tough(body)
            body.powers.hard_reset()
            bodies.append(body)
        return bodies


class RoleTests(GuardCase):
    def test_exactly_one_guards_and_it_is_by_role_every_time_the_squad_comes(self):
        self.squad_with()
        for _ in range(3):
            guards = [member for member in self.teams.summons if member.guards_leader]
            self.assertEqual([member.palette.name for member in guards], ["INVINCIBLE"])
            self.assertIs(self.teams._bodyguard(), guards[0])
            self.teams.withdraw_squad(list(self.teams.summons))
            self.assertIsNone(self.teams._bodyguard())
            self.teams.deploy_squad(self.leader)
            self.teams._apply_roster()

    def test_out_of_any_order_it_is_still_him(self):
        self.squad_with()
        self.teams.summons.reverse()
        self.assertEqual(self.teams._bodyguard().palette.name, "INVINCIBLE")
        self.teams.withdraw_squad(list(self.teams.summons))
        self.teams.deploy_squad(self.leader, viltrumites=2, mark=False)
        self.teams._apply_roster()
        self.assertIsNone(self.teams._bodyguard(), "no Mark, no bodyguard: nobody else is promoted")
        self.frames(10)


class AttackedTests(GuardCase):
    def test_someone_going_for_omni_man_becomes_marks_target_at_once(self):
        self.squad_with(distance=300.0)
        self.enemy.motion = LungeMotion(self.enemy.powers.abilities["melee"], self.leader, False)
        self.frames(8)
        self.assertIs(self.teams.leader_threat, self.enemy)
        self.assertIs(self.combat.targets.lock_of(self.mark), self.enemy)
        self.enemy.release_motion()

    def test_he_gets_in_between_and_the_way_is_really_blocked(self):
        self.squad_with(distance=50.0)
        self.enemy.vitals.add_status("frozen", 60.0)
        self.mark.position = (float(self.leader.x) + 30.0, float(self.leader.y) + 10.0, float(self.leader.z) - 30.0)
        for member in self.teams.summons:
            member._ai_next_attack = 1e9  # only where he goes, here
        self.seconds(4.0)
        leader_at, enemy_at = center_of(self.leader), center_of(self.enemy)
        line = (enemy_at - leader_at).normalized()
        along = (center_of(self.mark) - leader_at).dot(line) if hasattr(leader_at, "dot") else (
            (center_of(self.mark).x - leader_at.x) * line.x + (center_of(self.mark).y - leader_at.y) * line.y
            + (center_of(self.mark).z - leader_at.z) * line.z)
        self.assertGreater(along, 1.0, "on the enemy's side of him")
        self.assertLess(self.gap(self.mark, self.leader), 16.0, "and close")
        # What an attack along that line meets first is Mark, not Omni-Man.
        to_leader = (leader_at - enemy_at)
        hit = trace(self.game, enemy_at, to_leader.normalized(), to_leader.length() + 1.0, ignore=(self.enemy,),
                    radius=2.0, characters=(self.mark, self.leader), terrain=False)
        self.assertIs(hit.target, self.mark)

    def test_while_the_five_carry_on_with_their_own_fight(self):
        self.squad_with(distance=40.0)
        second = self.more_enemies("BLACK")[0]
        self.stand(second, 400.0, 400.0)
        second.vitals.add_status("frozen", 60.0)
        self.enemy.vitals.add_status("frozen", 60.0)
        self.frames(6)
        self.assertIs(self.teams.leader_threat, self.enemy)
        self.combat.targets.clear()
        self.stand(self.others[0], 395.0, 395.0)
        self.frames(30)
        self.assertIs(self.combat.targets.lock_of(self.others[0]), second, "the nearest to it, not Omni-Man's threat")
        self.assertNotIn(self.others[0], (self.teams._bodyguard(),))
        for member in self.others:
            self.assertFalse(member.guards_leader)


class GrabbedTests(GuardCase):
    def grab(self):
        self.stand(self.enemy, float(self.leader.x) + 4.0, float(self.leader.z))
        self.enemy.powers.abilities["grab"]._hold(self.leader)
        self.assertTrue(self.leader.vitals.has("held"))

    def test_he_drops_what_he_is_doing_flies_over_and_breaks_the_hold(self):
        self.squad_with(distance=300.0)
        self.mark.position = (float(self.mark.x) + 80.0, float(self.mark.y), float(self.mark.z))
        self.grab()
        grab = self.enemy.powers.abilities["grab"]
        started = self.game.elapsed
        for _ in range(round(10.0 / FRAME)):
            self.game.update(FRAME)
            if grab.held is None:
                break
        self.assertIsNone(grab.held, "Omni-Man is free")
        self.assertFalse(self.leader.vitals.has("held"))
        self.assertLess(self.game.elapsed - started, 8.0)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0, "and the one holding him was hit")

    def test_it_is_mark_who_goes_not_the_five(self):
        self.squad_with(distance=300.0)
        self.enemy.vitals.add_status("frozen", 0.0)
        self.grab()
        self.frames(3)
        self.assertTrue(self.teams.leader_in_danger)
        self.assertIs(self.teams.leader_threat, self.enemy)
        for member in self.others:
            self.assertLess(member.next_decision - self.game.elapsed, 1.0, "they decide on their usual clock")
            self.assertIsNot(self.teams._bodyguard(), member)


class SurroundedTests(GuardCase):
    def test_three_around_him_is_an_emergency_and_he_goes_in(self):
        self.squad_with(distance=25.0)
        self.bodies = self.more_enemies("BLACK", "RED")
        for body, (x, z) in zip(self.bodies, ((20.0, 0.0), (-20.0, 0.0))):
            self.stand(body, float(self.leader.x) + x, float(self.leader.z) + z)
            body.vitals.add_status("frozen", 60.0)
        self.enemy.vitals.add_status("frozen", 60.0)
        self.mark.position = (float(self.leader.x), float(self.leader.y) + 60.0, float(self.leader.z) + 60.0)
        self.frames(6)
        self.assertTrue(self.teams.leader_in_danger)
        closest = 1e9
        for _ in range(round(4.0 / FRAME)):
            self.game.update(FRAME)
            if self.teams.leader_threat is not None:
                closest = min(closest, self.gap(self.mark, self.teams.leader_threat))
        self.assertLess(closest, 8.0, "he went right in")
        hurt = [body for body in (self.enemy, *self.bodies) if body.vitals.damage_taken > 0.0]
        self.assertGreaterEqual(len(hurt), 2, "and he hit more than one of them")


class CriticalTests(GuardCase):
    def test_critically_hurt_it_is_an_emergency_and_his_own_fight_stops(self):
        self.squad_with(distance=40.0)
        self.enemy.vitals.add_status("frozen", 60.0)
        second = self.more_enemies("BLACK")[0]
        self.stand(second, 800.0, 800.0)
        second.vitals.add_status("frozen", 60.0)
        self.mark.motion = LungeMotion(self.mark.powers.abilities["melee"], second, False)
        self.leader.vitals.health = self.leader.vitals.max_health * .1
        self.leader.vitals.regen = 0.0
        self.frames(8)
        self.assertTrue(self.teams.leader_in_danger)
        self.assertIsNot(getattr(self.mark.motion, "target", None), second, "that was not essential")
        self.assertIs(self.combat.targets.lock_of(self.mark), self.enemy)
        before = self.enemy.vitals.damage_taken
        self.seconds(6.0)
        self.assertGreater(self.enemy.vitals.damage_taken, before, "he really goes for them")


class RuleTests(GuardCase):
    def test_when_all_is_quiet_he_stays_by_him(self):
        self.squad_with(distance=2000.0)
        self.enemy.vitals.add_status("frozen", 60.0)
        self.mark.position = (float(self.leader.x) + 100.0, float(self.leader.y) + 30.0, float(self.leader.z))
        self.seconds(6.0)
        self.assertIsNone(self.teams.leader_threat)
        self.assertLess(self.gap(self.mark, self.leader), 20.0)

    def test_he_resumes_when_it_is_over(self):
        self.squad_with(distance=40.0)
        self.enemy.vitals.add_status("frozen", 60.0)
        self.frames(6)
        self.assertIs(self.teams.leader_threat, self.enemy)
        self.stand(self.enemy, 2000.0, 2000.0)
        self.frames(12)
        self.assertIsNone(self.teams.leader_threat)
        self.assertFalse(self.teams.leader_in_danger)

    def test_he_never_hurts_omni_man_and_no_number_changes(self):
        self.squad_with(distance=30.0)
        vitals = self.mark.vitals
        before = (vitals.max_health, vitals.resistance, vitals.regen, self.mark.powers.strength,
                  self.leader.powers.strength, self.leader.vitals.resistance)
        self.leader.vitals.damage_taken = 0.0
        self.mark._ai_next_attack = 0.0
        self.seconds(8.0)
        self.assertEqual(self.leader.vitals.damage_taken, 0.0)
        self.assertEqual((vitals.max_health, vitals.resistance, vitals.regen, self.mark.powers.strength,
                          self.leader.powers.strength, self.leader.vitals.resistance), before)

    def test_it_works_with_ai_omni_man_as_well_as_the_player_and_on_a_team_of_enemies(self):
        self.squad_with(player="YELLOW", enemy="GREEN", distance=40.0)
        self.frames(12)
        self.assertIs(self.teams.leader_threat, self.player)
        self.assertIs(self.combat.targets.lock_of(self.mark), self.player)

    def test_mark_down_and_there_is_no_error_and_nobody_is_promoted(self):
        self.squad_with(distance=40.0)
        self.combat.hit_character(None, self.mark, 1e12)
        self.mark.on_downed()
        self.frames(10)
        self.assertIsNone(self.teams._bodyguard())
        self.assertIsNone(self.teams.leader_threat)
        self.assertEqual(MY_TEAM, self.teams.state.team_of("GREEN"))


if __name__ == "__main__":
    unittest.main()
