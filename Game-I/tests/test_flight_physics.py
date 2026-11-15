import unittest

from movement.flight_physics import (FlightDynamics, FlightPhase, Vec3,
                                     rotate_towards_degrees)
from movement.flight_steering import (direction_from_yaw_pitch, orientation_from_velocity,
                                      flight_posture, quaternion_slerp,
                                      upright_flight_yaw)


class FlightPhysicsTests(unittest.TestCase):
    def test_takeoff_transitions_to_cruise(self):
        flight = FlightDynamics()
        flight.toggle_flight()
        self.assertEqual(flight.phase, FlightPhase.TAKEOFF)
        for _ in range(8):
            flight.step(Vec3(0, 0, 1), 0, 0.1)
        self.assertEqual(flight.phase, FlightPhase.CRUISE)

    def test_acceleration_and_speed_cap(self):
        flight = FlightDynamics()
        flight.toggle_flight()
        for _ in range(100):
            flight.step(Vec3(0, 0, 1), 0, 0.05, boost=True)
        self.assertGreater(flight.speed_mps, 100)
        self.assertLessEqual(flight.speed_mps, flight.config.boost_speed + 1e-6)

    def test_braking_reduces_speed(self):
        flight = FlightDynamics()
        flight.toggle_flight()
        for _ in range(30):
            flight.step(Vec3(0, 0, 1), 0, 0.05, boost=True)
        before = flight.speed_mps
        flight.step(Vec3(), 0, 0.1, brake=True)
        self.assertLess(flight.speed_mps, before)

    def test_hands_off_cruise_holds_altitude_without_creating_forward_thrust(self):
        flight = FlightDynamics()
        flight.phase = FlightPhase.CRUISE
        gravity = Vec3(0.0, -9.80665, 0.0)
        for _ in range(120):
            flight.step(Vec3(), 0.0, 0.05, gravity=gravity)
        self.assertAlmostEqual(flight.velocity.y, 0.0, places=6)
        self.assertAlmostEqual(flight.velocity.x, 0.0, places=6)
        self.assertAlmostEqual(flight.velocity.z, 0.0, places=6)

    def test_hands_off_hover_smoothly_settles_vertical_drift(self):
        flight = FlightDynamics()
        flight.phase = FlightPhase.CRUISE
        flight.velocity = Vec3(0.0, 8.0, 0.0)
        gravity = Vec3(0.0, -9.80665, 0.0)
        previous_vertical_speed = flight.velocity.y
        for _ in range(80):
            flight.step(Vec3(), 0.0, 0.05, gravity=gravity)
            self.assertLessEqual(abs(flight.velocity.y), abs(previous_vertical_speed) + 1e-6)
            previous_vertical_speed = flight.velocity.y
        self.assertAlmostEqual(flight.velocity.y, 0.0, places=3)

    def test_dense_air_adds_drag_and_drag_fades_in_a_vacuum(self):
        sea_level = FlightDynamics()
        vacuum = FlightDynamics()
        for flight in (sea_level, vacuum):
            flight.phase = FlightPhase.CRUISE
            flight.velocity = Vec3(500.0, 0.0, 0.0)
        sea_level.step(Vec3(), 0.0, .1, boost=True, air_density=1.0)
        vacuum.step(Vec3(), 0.0, .1, boost=True, air_density=0.0)
        self.assertLess(sea_level.speed_mps, vacuum.speed_mps)

    def test_landing_waits_for_ground(self):
        flight = FlightDynamics()
        flight.toggle_flight()
        flight.phase = FlightPhase.CRUISE
        flight.toggle_flight()
        for _ in range(3):
            flight.step(Vec3(), 0, 0.05, ground_distance=4.0)
        self.assertEqual(flight.phase, FlightPhase.LANDING)
        flight.step(Vec3(), 0, 0.05, ground_distance=0.0)
        self.assertEqual(flight.phase, FlightPhase.GROUNDED)

    def test_ground_impact_only_starts_in_flight(self):
        flight = FlightDynamics()
        self.assertFalse(flight.start_ground_impact())
        flight.toggle_flight()
        self.assertTrue(flight.start_ground_impact())
        self.assertEqual(flight.phase, FlightPhase.GROUND_IMPACT)

    def test_yaw_and_pitch_set_flight_direction(self):
        forward = direction_from_yaw_pitch(90.0, 0.0)
        self.assertAlmostEqual(forward.x, 1.0, places=6)
        self.assertAlmostEqual(forward.z, 0.0, places=6)
        climb = direction_from_yaw_pitch(0.0, 30.0)
        self.assertGreater(climb.y, 0.0)
        self.assertAlmostEqual(climb.length(), 1.0, places=6)

    def test_flight_velocity_steers_toward_heading_without_snapping(self):
        flight = FlightDynamics()
        flight.toggle_flight()
        flight.phase = FlightPhase.CRUISE
        flight.velocity = Vec3(10.0, 0.0, 0.0)
        flight.step(Vec3(0.0, 0.0, 1.0), 0.0, 0.1)
        self.assertGreater(flight.velocity.z, 0.0)
        self.assertGreater(flight.velocity.x, 0.0)
        self.assertLess(flight.velocity.x, 10.0)

    def test_airborne_steering_turns_coasting_velocity_without_forward_thrust(self):
        flight = FlightDynamics()
        flight.toggle_flight()
        flight.phase = FlightPhase.CRUISE
        flight.velocity = Vec3(10.0, 0.0, 0.0)
        flight.step(Vec3(), 0.0, 0.1, steering_direction=Vec3(0.0, 0.0, 1.0))
        self.assertGreater(flight.velocity.z, 0.0)
        self.assertLess(flight.velocity.length(), 10.0)

    def test_backward_flight_reverses_travel_direction_and_boosts(self):
        flight = FlightDynamics()
        flight.phase = FlightPhase.CRUISE
        backward = Vec3(0.0, 0.0, -1.0)
        for _ in range(50):
            flight.step(backward, 0.0, 0.05,
                        steering_direction=backward, air_density=0.0)
        self.assertLess(flight.velocity.z, 0.0)
        self.assertGreater(flight.speed_mps, 10.0)
        for _ in range(50):
            flight.step(backward, 0.0, 0.05, boost=True,
                        steering_direction=backward, air_density=0.0)
        self.assertLess(flight.velocity.z, 0.0)
        self.assertGreater(flight.speed_mps, flight.config.cruise_speed)
        self.assertLessEqual(flight.speed_mps, flight.config.boost_speed + 1e-6)

    def test_backward_input_reverses_existing_forward_momentum_smoothly(self):
        flight = FlightDynamics()
        flight.phase = FlightPhase.CRUISE
        flight.velocity = Vec3(0.0, 0.0, flight.config.cruise_speed)
        backward = Vec3(0.0, 0.0, -1.0)
        for _ in range(100):
            flight.step(backward, 0.0, 0.05,
                        steering_direction=backward, air_density=0.0)
        self.assertLess(flight.velocity.z, 0.0)
        self.assertLessEqual(flight.speed_mps, flight.config.cruise_speed + 1e-6)

    def test_flight_posture_separates_backward_facing_from_travel(self):
        forward = Vec3(0.0, 0.0, 1.0)
        up = Vec3(0.0, 1.0, 0.0)
        backward = flight_posture(Vec3(0.0, 0.0, -30.0), forward, up,
                                  backward_intent=True)
        backward_diagonal = flight_posture(Vec3(0.0, 20.0, -30.0),
                                           forward, up, backward_intent=True)
        self.assertEqual(backward, (0.0, 0.0))
        self.assertEqual(backward_diagonal, (0.0, 0.0))

    def test_neutral_intent_stays_upright_while_coasting(self):
        forward = Vec3(0.0, 0.0, 1.0)
        up = Vec3(0.0, 1.0, 0.0)
        coast = flight_posture(Vec3(0.0, 0.0, 75.0), forward, up,
                               neutral_intent=True)
        self.assertEqual(coast, (0.0, 0.0))

    def test_flight_posture_handles_forward_vertical_and_lateral_vectors(self):
        forward = Vec3(0.0, 0.0, 1.0)
        up = Vec3(0.0, 1.0, 0.0)
        self.assertGreater(flight_posture(Vec3(0, 0, 30), forward, up)[0], 80.0)
        self.assertLess(flight_posture(Vec3(0, 30, 0), forward, up)[0], 0.0)
        # Radial vectors on the planet can carry signed -0.0 tangent axes.
        self.assertGreater(flight_posture(Vec3(-0.0, -30, -0.0),
                                          forward, up)[0], 90.0)
        self.assertLess(flight_posture(Vec3(25, 0, 20), forward, up)[1], 0.0)
        self.assertGreater(flight_posture(Vec3(-25, 0, 20), forward, up)[1], 0.0)

    def test_quaternion_interpolation_uses_a_normalized_shortest_arc(self):
        identity = (1.0, 0.0, 0.0, 0.0)
        opposite_sign_identity = (-1.0, 0.0, 0.0, 0.0)
        result = quaternion_slerp(identity, opposite_sign_identity, 0.5)
        self.assertAlmostEqual(result[0], 1.0)
        self.assertAlmostEqual(sum(value * value for value in result), 1.0)

    def test_body_orientation_tracks_flight_velocity_and_wraps_smoothly(self):
        yaw, pitch = orientation_from_velocity(Vec3(0.0, 8.0, 8.0))
        self.assertAlmostEqual(yaw, 0.0)
        self.assertLess(pitch, 0.0)
        self.assertAlmostEqual(rotate_towards_degrees(359.0, 1.0, 1.0), 360.0)
        self.assertAlmostEqual(rotate_towards_degrees(725.0, 1.0, 5.0), 721.0)

    def test_upright_flight_yaw_faces_horizontal_motion_but_holds_during_vertical_motion(self):
        self.assertAlmostEqual(upright_flight_yaw(Vec3(10, 20, 0), 35.0), 90.0)
        self.assertAlmostEqual(upright_flight_yaw(Vec3(10, 20, 0), 725.0), 810.0)
        self.assertAlmostEqual(upright_flight_yaw(Vec3(0, 30, 0), 35.0), 35.0)


if __name__ == "__main__":
    unittest.main()
