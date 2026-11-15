import unittest

from combat.damage_system import Damageable, impact_damage
from world.destructible_props import DebrisBudget, DestructibleState
from movement.flight_physics import Vec3


class DamageTests(unittest.TestCase):
    def test_damage_clamps_at_zero_and_breaks(self):
        target = Damageable(100)
        self.assertEqual(target.apply(30), 30)
        self.assertEqual(target.apply(100), 70)
        self.assertTrue(target.broken)
        self.assertEqual(target.apply(10), 0)

    def test_applied_damage_amount_is_not_itself_a_break_signal(self):
        target = Damageable(100)
        applied = target.apply(1.0)
        self.assertEqual(applied, 1.0)
        self.assertFalse(target.broken)

    def test_impact_threshold_and_cap(self):
        self.assertEqual(impact_damage(10), 0)
        self.assertEqual(impact_damage(20), 5)
        self.assertEqual(impact_damage(1000), 300)

    def test_damaged_structure_becomes_dynamic(self):
        target = DestructibleState("tower", Damageable(20), Vec3())
        self.assertFalse(target.take_damage(5))
        self.assertTrue(target.take_damage(15, Vec3(2, 3, 4)))
        self.assertTrue(target.dynamic)
        self.assertEqual(target.velocity, Vec3(2, 3, 4))

    def test_debris_budget_limits_spawns(self):
        budget = DebrisBudget(maximum_live_pieces=10)
        self.assertEqual(budget.reserve(8), 8)
        self.assertEqual(budget.reserve(8), 2)
        budget.release(5)
        self.assertEqual(budget.live_pieces, 5)


if __name__ == "__main__":
    unittest.main()
