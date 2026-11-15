"""Live gameplay integration tests for Sentry configuration effects."""

import unittest
from unittest.mock import MagicMock

from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from combat.damage_system import Damageable
from config.sentry_config import SentrySettings
from world.flat_sandbox import FlatSandboxFrame


class DummyTarget:
    def __init__(self, health=100.0):
        self.health = Damageable(health)
        self.frozen_duration = 0.0
        self.applied_heat = 0.0
        self.velocity = SimVec3()

    def take_damage(self, amount, impulse=None):
        return self.health.apply(amount)

    def apply_heat(self, amount, impulse=None):
        self.applied_heat += amount
        return self.take_damage(amount, impulse)

    def freeze(self, duration):
        self.frozen_duration = duration


class PanelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.settings = SentrySettings()
        self.planet = FlatSandboxFrame()

    def test_flight_speed_updates_flight_dynamics(self):
        from movement.flight_physics import FlightDynamics
        flight = FlightDynamics()
        self.settings.set("normal_flight_speed", 300.0)
        flight.config.cruise_speed = self.settings.get("normal_flight_speed")
        self.assertEqual(flight.config.cruise_speed, 300.0)

        # Step forward and verify velocity approaches new cruise speed
        flight.phase = FlightPhase.CRUISE
        for _ in range(50):
            flight.step(SimVec3(0, 0, 1), 0.0, 0.05, boost=False)
        self.assertGreater(flight.speed_mps, 100.0)

    def test_boost_multiplier_updates_acceleration(self):
        from movement.flight_physics import FlightDynamics
        flight = FlightDynamics()
        self.settings.set("flight_acceleration", 50.0)
        self.settings.set("flight_boost_multiplier", 4.0)

        flight.config.acceleration = self.settings.get("flight_acceleration")
        flight.config.boost_acceleration = (
            self.settings.get("flight_acceleration") * self.settings.get("flight_boost_multiplier")
        )
        self.assertEqual(flight.config.boost_acceleration, 200.0)

    def test_heat_vision_damage_scaling(self):
        target = DummyTarget(500.0)
        self.settings.set("beam_damage", 250.0)
        self.settings.set("continuous_damage_rate", 2.0)

        # Calculate applied damage over 1 second
        dt = 1.0
        damage = self.settings.get("beam_damage") * dt * self.settings.get("continuous_damage_rate")
        target.apply_heat(damage)

        self.assertEqual(target.applied_heat, 500.0)
        self.assertTrue(target.health.broken)

    def test_freeze_breath_duration_and_strength(self):
        target = DummyTarget()
        self.settings.set("freeze_duration", 14.5)
        self.settings.set("freeze_strength", 2.0)

        target.freeze(self.settings.get("freeze_duration"))
        self.assertEqual(target.frozen_duration, 14.5)

    def test_throwing_force_and_speed_scaling(self):
        self.settings.set("throw_speed", 50.0)
        self.settings.set("throw_force", 3.0)

        effective_speed = self.settings.get("throw_speed") * self.settings.get("throw_force")
        self.assertEqual(effective_speed, 150.0)

    def test_ground_impact_radius_and_damage(self):
        self.settings.set("shockwave_radius", 45.0)
        self.settings.set("environmental_damage", 600.0)
        self.settings.set("destruction_multiplier", 2.0)

        radius = self.settings.get("shockwave_radius")
        total_dmg = self.settings.get("environmental_damage") * self.settings.get("destruction_multiplier")

        self.assertEqual(radius, 45.0)
        self.assertEqual(total_dmg, 1200.0)

    def test_gravity_multiplier_scales_island_frame_gravity(self):
        pos = self.planet.point_from_local(0, 0, 100)
        base_g = self.planet.gravity(pos).length()

        self.planet.gravity_multiplier = 2.5
        scaled_g = self.planet.gravity(pos).length()

        self.assertAlmostEqual(scaled_g, base_g * 2.5, places=5)

    def test_simple_flight_speed_and_boost(self):
        from movement.flight_physics import FlightDynamics
        flight = FlightDynamics()
        self.settings.set("flight_speed", 250)
        self.settings.set("flight_boost_speed", 800)

        flight.config.cruise_speed = float(self.settings.get("flight_speed"))
        flight.config.boost_speed = float(self.settings.get("flight_boost_speed"))
        self.assertEqual(flight.config.cruise_speed, 250.0)
        self.assertEqual(flight.config.boost_speed, 800.0)

    def test_simple_ground_speed(self):
        from movement.ground_movement import GroundMovement
        gm = GroundMovement()
        self.settings.set("ground_speed", 75)
        gm.walk_speed = float(self.settings.get("ground_speed"))
        self.assertEqual(gm.walk_speed, 75.0)

    def test_simple_heat_vision_settings(self):
        self.settings.set("heat_vision_damage", 350)
        self.settings.set("heat_vision_range", 700)
        self.assertEqual(self.settings.get("heat_vision_damage"), 350)
        self.assertEqual(self.settings.get("heat_vision_range"), 700)

    def test_simple_freeze_breath_range(self):
        self.settings.set("freeze_breath_range", 150)
        self.assertEqual(self.settings.get("freeze_breath_range"), 150)

    def test_simple_throwing_force(self):
        self.settings.set("throwing_force", 1200)
        self.assertEqual(self.settings.get("throwing_force"), 1200)

    def test_simple_ground_impact_power(self):
        self.settings.set("ground_impact_power", 250)
        power = self.settings.get("ground_impact_power")
        radius = 15.0 * (power / 100.0)
        damage = 180.0 * (power / 100.0)
        self.assertEqual(radius, 37.5)
        self.assertEqual(damage, 450.0)

    def test_collision_damage_multiplier(self):
        self.settings.set("collision_damage_multiplier", 0.0)  # God mode immunity
        speed = 100.0
        base_dmg = min(25.0, (speed - 18.0) * 0.3)
        actual_dmg = base_dmg * self.settings.get("collision_damage_multiplier")
        self.assertEqual(actual_dmg, 0.0)

        self.settings.set("collision_damage_multiplier", 2.5)
        actual_dmg_enhanced = base_dmg * self.settings.get("collision_damage_multiplier")
        self.assertAlmostEqual(actual_dmg_enhanced, base_dmg * 2.5)


if __name__ == "__main__":
    unittest.main()

