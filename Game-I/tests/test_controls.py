import unittest
from unittest.mock import patch

from game.controls import (CONTROL_BINDINGS, KEY_ACTIONS, key_axis, movement_axes,
                           normalize_key, signed_movement_axes, vertical_axis)
from movement.flight_physics import Vec3
from movement.ground_movement import GroundMovement


from movement.flight_physics import Vec3 as FlatVec3


class ControlsTests(unittest.TestCase):
    def test_requested_event_controls_are_unique_and_exact(self):
        self.assertEqual(CONTROL_BINDINGS, {
            "move_forward": "w", "move_backward": "s", "move_left": "a",
            "move_right": "d", "rise": "space", "descend": "control",
            "flight_action": "f", "accelerate": "shift", "brake": "alt",
            "camera_left": "left arrow", "camera_right": "right arrow",
            "camera_up": "down arrow", "camera_down": "up arrow",
            "rise_alt": "home", "descend_alt": "end",
            "camera_reset": "c", "target_lock": "q", "team_manager": "m", "team_status": "tab",
            "config_panel": "p", "pause": "escape",
            "fullscreen": "k",
            "look": "mouse",
        })
        self.assertEqual(KEY_ACTIONS["f"], "flight_action")
        self.assertEqual(KEY_ACTIONS["c"], "camera_reset")
        self.assertEqual(KEY_ACTIONS["escape"], "pause")
        self.assertEqual(KEY_ACTIONS["p"], "config_panel")
        for ability_key in ("1", "2", "3", "4", "r", "t", "e", "period", "z", "b"):
            self.assertNotIn(ability_key, KEY_ACTIONS)
        self.assertNotIn("`", KEY_ACTIONS)
        self.assertNotIn("mouse1", KEY_ACTIONS)
        self.assertEqual(CONTROL_BINDINGS["brake"], "alt")

    def test_period_key_normalizes_from_punctuation_and_name(self):
        self.assertEqual(normalize_key("."), "period")
        self.assertEqual(normalize_key("period"), "period")
        self.assertEqual(normalize_key("ESC"), "escape")
        self.assertEqual(normalize_key("p"), "p")
        self.assertEqual(normalize_key("P"), "p")

    def test_turn_axis_and_vertical_axes(self):
        held = {"a": 1, "d": 0, "space": 1, "control": 0}
        self.assertEqual(key_axis(held, "d", "a"), -1.0)
        self.assertEqual(key_axis(held, "space", "control"), 1.0)
        held["d"] = 1
        self.assertEqual(key_axis(held, "d", "a"), 0.0)

    def test_camera_arrows_do_not_enter_player_movement_axes(self):
        held = {"w": 1, "a": 0, "s": 0, "d": 0,
                "left arrow": 1, "right arrow": 0, "up arrow": 1}
        self.assertEqual(movement_axes(held), (1.0, 0.0, 0.0, 0.0))
        self.assertEqual(vertical_axis(held), 0.0)

    def test_opposing_flight_inputs_cancel_without_conflicting_axes(self):
        self.assertEqual(signed_movement_axes({"w": 1, "s": 1}), (0.0, 0.0))
        self.assertEqual(signed_movement_axes({"s": 1, "a": 1}), (-1.0, -1.0))
        self.assertEqual(signed_movement_axes({"w": 1, "d": 1}), (1.0, 1.0))

    def test_backward_ground_movement_remains_supported(self):
        ground = GroundMovement()
        velocity = ground.step(Vec3(0.0, 0.0, -1.0), .1)
        self.assertLess(velocity.z, 0.0)

    def test_input_manager_maps_backward_and_lateral_flight_relative_to_heading(self):
        from game.input_manager import InputManager

        class FakePlanet:
            @staticmethod
            def normal(position):
                return Vec3(0.0, 1.0, 0.0)

            @staticmethod
            def heading(position, yaw, pitch=0.0):
                from movement.flight_steering import direction_from_yaw_pitch
                return direction_from_yaw_pitch(yaw, pitch)

        class FakeGame:
            planet = FakePlanet()

            class Character:
                x = y = z = 0.0

            sentry = Character()

            class camera:
                yaw = flight_yaw = 0.0

                @staticmethod
                def aim_direction(_position):
                    return FlatVec3(0.0, 0.0, 1.0)

        manager = InputManager(FakeGame())
        with patch("game.input_manager.held_keys", {"s": 1}):
            backward, _ = manager.movement(flying=True)
        self.assertLess(backward.z, 0.0)

        with patch("game.input_manager.held_keys", {"d": 1}):
            right, _ = manager.movement(flying=True)
        with patch("game.input_manager.held_keys", {"a": 1}):
            left, _ = manager.movement(flying=True)
        self.assertGreater(right.x, 0.0)
        self.assertLess(left.x, 0.0)

    def test_home_end_are_vertical_flight_aliases(self):
        self.assertEqual(vertical_axis({"home": 1}), 1.0)
        self.assertEqual(vertical_axis({"end": 1}), -1.0)
        self.assertEqual(vertical_axis({"home": 1, "space": 1, "end": 1}), 0.0)


if __name__ == "__main__":
    unittest.main()
