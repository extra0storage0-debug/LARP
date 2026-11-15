"""The six Omni-Man calls on key 1. Not roster characters: nobody plays them, and they are never saved."""

from __future__ import annotations

from characters.roster_character import RosterCharacter
from powers.loadout import PuppetPowers, SquadPowers

VILTRUMITE_SHARE = .45  # of Omni-Man's strength
INVINCIBLE_SHARE = .55
VILTRUMITE_HEALTH = .005  # of Omni-Man's configured maximum health
INVINCIBLE_HEALTH = .05


class Puppet(RosterCharacter):
    """A body an execution moves by hand: Homelander's clones and Sentry's Void copy. It has no AI, no health
    bar and no say in anything, nothing can target it, and all the damage it seems to do is its master's."""

    POWERS = PuppetPowers

    def __init__(self, team, palette, personality, seed: int) -> None:
        super().__init__(team, palette, personality, (0.0, 0.0, 0.0), seed)
        self.collider = None
        self.set_parked(True)


class SquadFighter(RosterCharacter):
    POWERS = SquadPowers
    ai_moves = "SQUAD"

    def __init__(self, team, palette, personality, position, seed: int) -> None:
        invincible = palette.name == "INVINCIBLE"
        self.power_share = INVINCIBLE_SHARE if invincible else VILTRUMITE_SHARE
        self.health_share = INVINCIBLE_HEALTH if invincible else VILTRUMITE_HEALTH
        self.guards_leader = invincible  # his role, and his alone: the others fight as they always have
        super().__init__(team, palette, personality, position, seed)
