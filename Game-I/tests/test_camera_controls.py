import unittest

from movement.camera_controls import apply_camera_input, apply_flight_steering


class CameraControlTests(unittest.TestCase):
    def test_mouse_controls_flight_heading_and_pitch(self):
        yaw, pitch, turn = apply_camera_input(0.0, 10.0, 0.1, 0.1, 1/60, 0.0,
                                              flying=True)
        self.assertGreater(yaw, 0.0)
        self.assertLess(pitch, 10.0)
        self.assertGreater(turn, 0.0)

    def test_mouse_camera_heading_is_independent_from_lateral_flight_input(self):
        yaw, _, turn = apply_camera_input(0.0, 10.0, 0.1, 0.0, 0.1, 0.0,
                                          flying=True)
        self.assertAlmostEqual(yaw, 12.5)
        self.assertEqual(turn, 1.0)

    def test_arrow_keys_rotate_only_camera_axes_without_angle_clamps(self):
        yaw, pitch, turn = apply_camera_input(
            0.0, 10.0, 0.0, 0.0, .5, 0.0, flying=False,
            camera_x_axis=-1.0, camera_y_axis=1.0)
        self.assertAlmostEqual(yaw, -45.0)
        self.assertAlmostEqual(pitch, -22.5)
        self.assertEqual(turn, 0.0)

    def test_camera_yaw_and_pitch_accumulate_through_multiple_turns(self):
        yaw, pitch = 725.0, 179.0
        for _ in range(40):
            yaw, pitch, _ = apply_camera_input(
                yaw, pitch, .1, -.1, .1, 0.0, flying=False,
                camera_x_axis=1.0, camera_y_axis=-1.0)
        self.assertAlmostEqual(yaw, 40 * 21.5 + 725.0)
        self.assertAlmostEqual(pitch, 179.0 + 40 * 15.5)

    def test_arrow_rotation_updates_the_shared_camera_and_flight_yaw(self):
        camera_yaw, camera_pitch, _ = apply_camera_input(
            0.0, 10.0, 0.0, 0.0, .5, 0.0, flying=True,
            camera_x_axis=1.0, camera_y_axis=1.0)
        flight_yaw, flight_pitch = apply_flight_steering(
            camera_yaw, camera_pitch, 0.0, 0.0, .5, 0.0)
        self.assertEqual(camera_yaw, flight_yaw)
        self.assertAlmostEqual(camera_pitch, flight_pitch)

    def test_equal_mouse_and_arrow_motion_produce_equal_shared_yaw(self):
        mouse_yaw, mouse_pitch, _ = apply_camera_input(
            42.0, 10.0, .072, 0.0, .1, 0.0, flying=False)
        arrow_yaw, arrow_pitch, _ = apply_camera_input(
            42.0, 10.0, 0.0, 0.0, .1, 0.0, flying=False,
            camera_x_axis=1.0)
        self.assertAlmostEqual(mouse_yaw, arrow_yaw, places=6)
        self.assertAlmostEqual(mouse_pitch, arrow_pitch, places=6)


if __name__ == "__main__":
    unittest.main()
