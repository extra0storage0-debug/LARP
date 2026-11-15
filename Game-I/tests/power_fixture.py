"""Helpers for driving one character's abilities against a target at a known place."""

from __future__ import annotations

from unittest import mock

from config.character_roster import ENEMY_TEAM, MY_TEAM
from game_fixture import FRAME, reset_game
from movement.flight_physics import FlightPhase, Vec3 as SimVec3


class PowerCase:
    """Mixin: a game where AI is still, the camera looks along +Z, and one enemy waits ahead.

    Automatic targeting is on, as in the game; ``manual()`` turns it off for a test that aims
    an ability at the world while an enemy is still on the island.
    """

    PLAYER = "YELLOW"
    ENEMY = "BLACK"
    DISTANCE = 20.0
    # Test name for a key -> ability with no real key now. AI still uses those, so they stay tested.
    DIRECT = {}

    def setUp(self):
        self.game = reset_game()
        self.teams = self.game.teams
        self.combat = self.game.combat
        patcher = mock.patch.object(self.teams, "update")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.play(self.PLAYER)
        self.place_enemy(self.ENEMY)

    def tearDown(self):
        self.game.sentry.powers.cancel_all()
        self.game.sentry.release_motion()
        self.enemy.powers.apply_passives()

    def manual(self) -> None:
        self.combat.targets.enabled = False

    def play(self, character_id: str):
        self.teams.state.assignment[character_id] = MY_TEAM
        self.teams.swap(character_id, save=False)
        self.player = self.game.sentry
        self.player.powers.hard_reset()
        self.stand(self.player, 0.0, 0.0)
        self.player.local_yaw = 0.0
        self.game.camera.yaw = 0.0
        for other in self.teams.characters.values():
            if other is not self.player:
                self.teams.state.assignment[other.character_id] = "available"
        self.teams._apply_roster()
        aim = mock.patch.object(type(self.player), "aim_ray", lambda owner: self.aim(owner))
        aim.start()
        self.addCleanup(aim.stop)
        direct = mock.patch.object(type(self.player), "aim_direction_from",
                                   lambda owner, _origin, _limit: self.aim(owner)[1])
        direct.start()
        self.addCleanup(direct.stop)
        return self.player

    def aim(self, owner):
        origin = SimVec3(owner.x, owner.y + 2.5, owner.z)
        target = getattr(self, "aim_at", None)
        if target is not None:
            return origin, (target - origin).normalized()
        return origin, SimVec3(0.0, 0.0, 1.0)

    def stand(self, character, x: float, z: float) -> None:
        character.position = (x, self.game.world.height_at(x, z) + .25, z)
        character.flight.phase = FlightPhase.GROUNDED
        character.flight.velocity = SimVec3()
        character.ground.velocity = SimVec3()
        character.knock = SimVec3()

    def place_enemy(self, character_id: str, distance: float | None = None, x: float = 0.0):
        self.enemy = self.teams.characters[character_id]
        self.teams.state.assignment[character_id] = ENEMY_TEAM
        self.teams._apply_roster()
        z = self.DISTANCE if distance is None else distance
        for other in self.teams.characters.values():  # one enemy at a time unless a test adds more
            if other is not self.player and other is not self.enemy \
                    and self.teams.state.team_of(other.character_id) == ENEMY_TEAM:
                self.teams.state.assignment[other.character_id] = "available"
        self.teams._apply_roster()
        self.stand(self.enemy, x, z)
        self.enemy.vitals.health = self.enemy.vitals.max_health
        self.enemy.vitals.statuses.clear()
        self.enemy.vitals.downed_for = 0.0
        self.enemy.vitals.damage_taken = 0.0
        self.enemy.vitals.regen = 0.0
        self.aim_at = SimVec3(x, self.enemy.y + 1.4, z)
        return self.enemy

    def remove_enemy(self) -> None:
        """Nobody to target: abilities fall back to where the camera aims."""
        self.teams.state.assignment[self.enemy.character_id] = "available"
        self.teams._apply_roster()

    def ability(self, ability_id: str):
        return self.player.powers.abilities[ability_id]

    def set(self, ability_id: str, key: str, value: float, character_id: str | None = None) -> None:
        self.combat.settings.set(character_id or self.player.character_id, ability_id, key, value)

    def frames(self, count: int) -> None:
        for _ in range(count):
            self.game.update(FRAME)

    def seconds(self, length: float) -> None:
        self.frames(max(1, int(length / FRAME)))

    def press(self, key: str) -> None:
        if key in self.DIRECT:
            self.ability(self.DIRECT[key]).press()
        else:
            self.game.input(key)

    def release(self, key: str) -> None:
        if key in self.DIRECT:
            self.ability(self.DIRECT[key]).release()
        else:
            self.game.input(f"{key} up")

    def tap(self, key: str, frames: int = 1) -> None:
        self.press(key)
        self.frames(frames)
        self.release(key)

    def click(self, frames: int = 1) -> None:
        self.press("=")
        self.frames(frames)
        self.release("=")

    def damage_of(self, action) -> float:
        """Health the enemy lost to an action, with health to spare and no recovery."""
        vitals = self.enemy.vitals
        vitals.max_health = 10000000.0
        vitals.health = vitals.max_health
        vitals.downed_for = 0.0
        vitals.regen = 0.0
        vitals.damage_taken = 0.0
        action()
        return vitals.damage_taken


def fresh_tree(game, near=(0.0, 0.0), minimum: float = 0.0):
    """The nearest healthy tree at least ``minimum`` metres away."""
    best, best_distance = None, 1e12
    for chunk in game.world.chunks.values():
        for tree in chunk.tree_colliders:
            if tree.tree_health < game.world.TREE_MAX_HEALTH:
                continue
            distance = ((tree.x - near[0]) ** 2 + (tree.z - near[1]) ** 2) ** .5
            if minimum <= distance < best_distance:
                best, best_distance = tree, distance
    return best


def object_of(game, kind: str):
    """A standing landmark of a given display name."""
    return next(item for item in game.landmarks.items
                if getattr(item, "display_name", "") == kind and not item.health.broken)
