"""AI movement decisions: formations, pursuit and steering, with no combat left in them."""

import unittest

from ai.enemy_team_ai import (PERSONALITIES, AgentView, AITuning, EnemyBrain, Personality, Role,
                              Strategy, TargetView, TeamDirector, predict_intercept, separation,
                              steer_flight, terrain_safe_altitude)
from movement.flight_physics import Vec3

NAMES = ("WHITE", "GREEN", "BLACK", "RED")


def agents(radius=50.0):
    return [AgentView(name, Vec3(index * radius - 75.0, 5.0, 30.0), Vec3())
            for index, name in enumerate(NAMES)]


class DirectorTests(unittest.TestCase):
    def setUp(self):
        self.director = TeamDirector()
        self.target = TargetView(Vec3(0, 5, 0), Vec3())

    def test_each_character_gets_a_unique_role_with_one_leader(self):
        self.director.update(0.0, agents(), self.target)
        roles = list(self.director.roles.values())
        self.assertEqual(len(roles), 4)
        self.assertEqual(len(set(roles)), 4)
        self.assertEqual(roles.count(Role.LEADER), 1)

    def test_formation_points_are_spread_around_the_target(self):
        self.director.update(0.0, agents(), self.target)
        points = [self.director.formation_point(name, self.target, 100.0) for name in NAMES]
        for index, point in enumerate(points):
            for other in points[index + 1:]:
                self.assertGreater((point - other).length(), 1.0)

    def test_far_target_switches_to_pursuit(self):
        far = [AgentView(name, Vec3(4000.0, 5.0, 0.0), Vec3()) for name in NAMES]
        self.director.update(0.0, far, self.target)
        self.assertIs(self.director.strategy, Strategy.PURSUE)

    def test_forget_removes_a_character(self):
        self.director.update(0.0, agents(), self.target)
        self.director.forget("RED")
        self.assertNotIn("RED", self.director.roles)


class BrainTests(unittest.TestCase):
    def setUp(self):
        self.director = TeamDirector()
        self.brain = EnemyBrain("WHITE", Personality(reaction=0.0), seed=3)
        self.agent = AgentView("WHITE", Vec3(0, 5, 0), Vec3(), flying=True)
        self.target = TargetView(Vec3(0, 5, 30), Vec3())

    def decide(self):
        self.director.update(1.0, [self.agent], self.target)
        return self.brain.decide(1.0, self.agent, self.target, self.director, [self.agent],
                                 flight_speed=100.0)

    def test_every_character_has_a_distinct_personality(self):
        self.assertEqual(set(PERSONALITIES), {"YELLOW", *NAMES})
        self.assertEqual(len({p.reaction for p in PERSONALITIES.values()}), 5)

    def test_intent_has_no_attack(self):
        self.assertFalse(hasattr(self.decide(), "attack"))

    def test_detection_range_hides_the_target(self):
        self.brain.tuning = AITuning(detection_range=10.0)
        self.assertEqual(self.decide().destination, self.agent.position)

    def test_ground_bound_brain_never_wants_flight(self):
        self.brain.can_fly = False
        self.target = TargetView(Vec3(0, 200, 30), Vec3(), flying=True, altitude=200.0)
        self.assertFalse(self.decide().want_flight)

    def test_flyer_follows_a_flying_target(self):
        self.target = TargetView(Vec3(0, 200, 30), Vec3(), flying=True, altitude=200.0)
        self.assertTrue(self.decide().want_flight)

    def test_no_coordination_heads_straight_for_the_target(self):
        self.brain.tuning = AITuning(coordination=0.0)
        self.director.strategy = Strategy.ENCIRCLE
        intent = self.decide()
        self.assertLess((intent.destination - self.target.position).length(), 1e-6)


class SteeringTests(unittest.TestCase):
    def test_separation_pushes_apart(self):
        a = AgentView("A", Vec3(0, 0, 0), Vec3())
        b = AgentView("B", Vec3(2, 0, 0), Vec3())
        self.assertLess(separation(a, [a, b]).x, 0.0)

    def test_intercept_leads_a_moving_target(self):
        point = predict_intercept(Vec3(), Vec3(0, 0, 100), Vec3(10, 0, 0), 50.0)
        self.assertGreater(point.x, 0.0)

    def test_steering_points_at_the_destination(self):
        command = steer_flight(Vec3(), Vec3(), Vec3(0, 0, 200), Vec3(), cruise_speed=100.0,
                               boost_speed=500.0, thrust=50.0, braking=100.0, dt=1 / 60)
        self.assertGreater(command.move.z, 0.0)

    def test_safe_altitude_clears_the_highest_point_ahead(self):
        height = terrain_safe_altitude(Vec3(), Vec3(0, 0, 100), lambda _x, z: z * .1, clearance=5.0)
        self.assertEqual(height, 100 * 1.2 * .1 + 5.0)


if __name__ == "__main__":
    unittest.main()
