"""Should debris move to a physics engine? Times Bullet (bundled with Panda3D, free) against the game's own debris step.

    python tools/physics_engine_benchmark.py

Both run the same job: N small boxes thrown up from one point, falling on ground, 60 steps a second, 6 seconds.
Only the physics is timed, with no drawing. Also records how many pieces end up below the ground.
"""

from __future__ import annotations

import json
from random import Random
import sys
import time

from panda3d.bullet import BulletBoxShape, BulletPlaneShape, BulletRigidBodyNode, BulletWorld
from panda3d.core import NodePath, Point3, Vec3

STEPS, DT = 360, 1.0 / 60.0


def launch(rng: Random) -> tuple:
    return rng.uniform(-14.0, 14.0), rng.uniform(4.0, 22.0), rng.uniform(-14.0, 14.0)


def bullet(count: int) -> dict:
    rng = Random(7)
    world = BulletWorld()
    world.setGravity(Vec3(0, 0, -22.0))
    root = NodePath("bullet")
    ground = BulletRigidBodyNode("ground")
    ground.addShape(BulletPlaneShape(Vec3(0, 0, 1), 0))
    root.attachNewNode(ground)
    world.attachRigidBody(ground)
    shape = BulletBoxShape(Vec3(.15, .15, .15))
    bodies = []
    for _ in range(count):
        node = BulletRigidBodyNode("piece")
        node.setMass(1.0)
        node.addShape(shape)
        path = root.attachNewNode(node)
        path.setPos(Point3(rng.uniform(-1, 1), rng.uniform(-1, 1), 1.0))
        vx, vy, vz = launch(rng)
        node.setLinearVelocity(Vec3(vx, vz, vy))
        world.attachRigidBody(node)
        bodies.append(path)
    worst, total = 0.0, 0.0
    for _ in range(STEPS):
        begin = time.perf_counter()
        world.doPhysics(DT, 1, DT)
        # Reading every position back is part of the price: the game's scene has to follow them.
        for path in bodies:
            path.getPos()
        spent = time.perf_counter() - begin
        total += spent
        worst = max(worst, spent)
    return {"mean_ms": round(total / STEPS * 1000.0, 3), "worst_ms": round(worst * 1000.0, 3),
            "below_ground": sum(path.getZ() < -.2 for path in bodies)}


class Piece:
    __slots__ = ("x", "y", "z", "vx", "vy", "vz")


def custom(count: int) -> dict:
    """The same arithmetic as DebrisPiece.step: gravity, a floor, a bounce with friction. Pure Python, as in the game."""
    rng = Random(7)
    pieces = []
    for _ in range(count):
        piece = Piece()
        piece.x, piece.y, piece.z = rng.uniform(-1, 1), 1.0, rng.uniform(-1, 1)
        piece.vx, piece.vy, piece.vz = launch(rng)
        pieces.append(piece)
    worst, total = 0.0, 0.0
    for _ in range(STEPS):
        begin = time.perf_counter()
        for piece in pieces:
            piece.vy -= 22.0 * DT
            piece.x += piece.vx * DT
            piece.y += piece.vy * DT
            piece.z += piece.vz * DT
            if piece.y < .15:
                piece.y = .15
                if piece.vy < -1.0:
                    piece.vy = -piece.vy * .25
                    piece.vx *= .65
                    piece.vz *= .65
                else:
                    piece.vy = 0.0
        spent = time.perf_counter() - begin
        total += spent
        worst = max(worst, spent)
    return {"mean_ms": round(total / STEPS * 1000.0, 3), "worst_ms": round(worst * 1000.0, 3),
            "below_ground": sum(piece.y < -.2 for piece in pieces)}


def main() -> int:
    results = {}
    for count in (64, 144, 320, 480):
        results[count] = {"custom": custom(count), "bullet": bullet(count)}
        print(count, json.dumps(results[count]), flush=True)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as file:
            json.dump(results, file, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
