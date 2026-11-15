"""Owns the streamed island world and exposes its simulation boundary."""

from world.island_generator import IslandWorld


class WorldManager:
    def __init__(self, game, settings):
        self.world = IslandWorld(game, settings)
        game.world = self.world
        game.planet = self.world.planet
        self.world.initialize()

    def update(self, dt: float) -> None:
        self.world.update(dt)
