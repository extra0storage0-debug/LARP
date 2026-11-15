"""Auto Target Lock: key 8 runs Q's own function on a timer, and leaves manual Q alone."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config.character_roster import ENEMY_TEAM, RosterState
from game.controls import CONTROL_BINDINGS, KEY_ACTIONS, RESERVED_KEYS
from game_fixture import FRAME
from test_gameplay_control_update import LiveCase


class AutoCase(LiveCase):
    def setUp(self):
        self.begin("WHITE", "BLACK", 100.0)
        self.targets = self.combat.targets
        self.targets.manual = None
        self.targets._auto_wait = 0.0  # the game is shared between tests, and this is what starting one means
        self.tough(self.enemy)
        self.enemy.vitals.add_status("frozen", 600.0)
        self.addCleanup(self.switch, False)
        self.addCleanup(lambda: setattr(self.targets, "manual", None))

    def switch(self, on: bool) -> None:
        self.teams.state.auto_target_lock = on

    def second_enemy(self, distance: float):
        self.teams.state.assignment["GREEN"] = ENEMY_TEAM
        self.teams._apply_roster()
        other = self.teams.characters["GREEN"]
        self.stand(other, 0.0, distance)
        self.tough(other)
        other.vitals.add_status("frozen", 600.0)
        return other


class KeyTests(AutoCase):
    def press(self) -> None:
        self.game.input("8")
        self.game.input("8 up")

    def test_8_toggles_it_with_a_message_each_way_that_then_goes(self):
        self.assertFalse(self.teams.state.auto_target_lock, "off to begin with")
        self.press()
        self.assertTrue(self.teams.state.auto_target_lock)
        self.frames(2)
        self.assertEqual(self.game.hud.notification.text, "AUTO TARGET LOCK: ON", "not replaced by the lock's own message")
        self.assertIs(self.targets.manual, self.enemy, "it locks straight away")
        self.seconds(2.0)
        self.assertEqual(self.game.hud.notification.text, "", "shown briefly")
        self.press()
        self.assertFalse(self.teams.state.auto_target_lock)
        self.frames(2)
        self.assertEqual(self.game.hud.notification.text, "AUTO TARGET LOCK: OFF")

    def test_off_by_default_nothing_happens_by_itself(self):
        self.frames(round(5.0 / FRAME))
        self.assertIsNone(self.targets.manual)

    def test_the_pause_menu_toggle_is_the_same_setting_and_shows_its_state(self):
        menu = self.game.hud.pause_menu
        self.game.toggle_pause()
        self.assertIn("OFF", menu.auto_lock_button.text)
        menu.toggle_auto_lock()
        self.assertTrue(self.teams.state.auto_target_lock)
        self.assertIn("ON", menu.auto_lock_button.text)
        self.assertTrue(RosterState(self.teams.state.path).auto_target_lock)
        menu.toggle_auto_lock()
        self.assertFalse(self.teams.state.auto_target_lock)
        self.assertIn("OFF", menu.auto_lock_button.text)
        self.game.toggle_pause()

    def test_nothing_else_answers_to_8_and_it_cannot_be_given_to_anything_else(self):
        self.assertNotIn("8", CONTROL_BINDINGS.values())
        self.assertNotIn("8", KEY_ACTIONS)
        self.assertIn("8", RESERVED_KEYS)
        self.press()
        self.assertIsNone(self.player.motion)
        self.press()

    def test_typing_8_into_a_menu_field_types_an_8(self):
        panel = self.game.power_panel
        self.game.input("p")
        panel.begin_edit(panel.card_of("heat_vision").rows["damage"])
        self.press()
        self.assertEqual(panel.buffer, "8")
        self.assertFalse(self.teams.state.auto_target_lock)
        panel.editing = None
        self.game.input("p")

    def test_it_does_nothing_while_paused(self):
        self.game.toggle_pause()
        self.press()
        self.assertFalse(self.teams.state.auto_target_lock)
        self.game.toggle_pause()

    def test_it_saves_and_loads_and_an_older_save_is_off(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "roster.json"
            state = RosterState(path)
            self.assertFalse(state.auto_target_lock)
            state.auto_target_lock = True
            self.assertTrue(state.save())
            self.assertTrue(RosterState(path).auto_target_lock)
            old = json.loads(path.read_text(encoding="utf-8"))
            old.pop("auto_target_lock")
            path.write_text(json.dumps(old), encoding="utf-8")
            self.assertFalse(RosterState(path).auto_target_lock)

    def test_the_key_saves_it(self):
        self.press()
        self.assertTrue(RosterState(self.teams.state.path).auto_target_lock)
        self.press()
        self.assertFalse(RosterState(self.teams.state.path).auto_target_lock)


class TimerTests(AutoCase):
    def test_on_locks_at_once_through_q_and_never_touches_the_keyboard(self):
        self.switch(True)
        with mock.patch.object(self.targets, "toggle_manual", wraps=self.targets.toggle_manual) as q, \
                mock.patch.object(self.game, "input", wraps=self.game.input) as keys:
            self.frames(1)
        self.assertEqual(q.call_count, 1)
        keys.assert_not_called()
        self.assertIs(self.targets.manual, self.enemy)

    def test_every_four_seconds_with_one_timer_and_it_never_lets_go(self):
        self.switch(True)
        times = []
        real = self.targets.auto_lock

        def spy():
            times.append(self.game.elapsed)
            real()

        with mock.patch.object(self.targets, "auto_lock", spy):
            for _ in range(round(13.0 / FRAME)):
                self.game.update(FRAME)
                self.assertIs(self.targets.manual, self.enemy, "a toggle called blindly would let go every other time")
        self.assertEqual(len(times), 4, "at 0, 4, 8 and 12")
        for earlier, later in zip(times, times[1:]):
            self.assertAlmostEqual(later - earlier, 4.0, delta=FRAME * 1.5)

    def test_a_nearer_enemy_is_picked_up_at_the_next_tick_not_before(self):
        self.switch(True)
        self.frames(1)
        self.assertIs(self.targets.manual, self.enemy)
        nearer = self.second_enemy(30.0)
        self.frames(round(3.5 / FRAME))
        self.assertIs(self.targets.manual, self.enemy)
        self.frames(round(.7 / FRAME))
        self.assertIs(self.targets.manual, nearer)

    def test_a_target_going_down_is_replaced_at_once(self):
        other = self.second_enemy(300.0)
        self.switch(True)
        self.frames(1)
        self.assertIs(self.targets.manual, self.enemy)
        self.combat.hit_character(None, self.enemy, 1e12)
        self.frames(2)
        self.assertIs(self.targets.manual, other)
        self.enemy.vitals.downed_for = 0.0
        self.enemy.vitals.health = self.enemy.vitals.max_health

    def test_a_target_leaving_the_world_is_replaced_too(self):
        other = self.second_enemy(300.0)
        self.switch(True)
        self.frames(1)
        self.teams.state.assignment["BLACK"] = "available"
        self.teams._apply_roster()
        self.frames(2)
        self.assertIs(self.targets.manual, other)

    def test_with_nobody_left_it_waits_and_never_locks_a_civilian_or_a_friend(self):
        self.teams.state.assignment["BLACK"] = "available"
        self.teams._apply_roster()
        self.switch(True)
        self.frames(round(5.0 / FRAME))
        self.assertIsNone(self.targets.manual)
        self.teams.state.assignment["BLACK"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.frames(round(4.2 / FRAME))
        self.assertIs(self.targets.manual, self.enemy)

    def test_off_stops_it_at_once_and_leaves_the_lock_as_it_is(self):
        self.switch(True)
        self.frames(1)
        self.switch(False)
        nearer = self.second_enemy(30.0)
        self.frames(round(6.0 / FRAME))
        self.assertIs(self.targets.manual, self.enemy)
        self.assertIsNot(self.targets.manual, nearer)

    def test_a_menu_being_open_holds_it(self):
        self.game.input("p")
        self.switch(True)
        for _ in range(round(5.0 / FRAME)):
            self.game.update(FRAME)
        self.assertIsNone(self.targets.manual)
        self.game.input("p")


class ManualTests(AutoCase):
    def q(self) -> None:
        self.game.input("q")
        self.game.input("q up")

    def test_off_q_works_as_it_always_has(self):
        self.q()
        self.assertIs(self.targets.manual, self.enemy)
        self.q()
        self.assertIsNone(self.targets.manual)

    def test_on_q_still_lets_go_and_the_lock_comes_back_on_the_next_tick(self):
        self.switch(True)
        self.frames(1)
        self.q()
        self.assertIsNone(self.targets.manual, "the key still does what it does")
        self.frames(round(3.0 / FRAME))
        self.assertIsNone(self.targets.manual, "not a target lost: it waits its turn")
        self.frames(round(1.2 / FRAME))
        self.assertIs(self.targets.manual, self.enemy)

    def test_q_does_not_start_a_second_timer(self):
        self.switch(True)
        self.frames(1)
        for _ in range(6):
            self.q()
        with mock.patch.object(self.targets, "auto_lock", wraps=self.targets.auto_lock) as tick:
            self.frames(round(4.2 / FRAME))
        self.assertLessEqual(tick.call_count, 3)


if __name__ == "__main__":
    unittest.main()
