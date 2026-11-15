import unittest
from movement.flight_physics import Vec3
from movement.ground_movement import GroundMovement

class GroundMovementTests(unittest.TestCase):
    def test_run_reaches_a_higher_speed_than_walk(self):
        movement = GroundMovement()
        for _ in range(30): movement.step(Vec3(0,0,1),1/60)
        walk = movement.velocity.length()
        for _ in range(30): movement.step(Vec3(0,0,1),1/60,sprint=True)
        self.assertGreater(movement.velocity.length(),walk)

    def test_diagonal_input_is_clamped(self):
        movement=GroundMovement()
        velocity=movement.step(Vec3(1,0,1),.1,sprint=True)
        self.assertLessEqual(velocity.length(),movement.max_running_speed)

if __name__ == "__main__": unittest.main()
