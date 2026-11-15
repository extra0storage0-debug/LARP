"""Which power an AI character uses next. No engine imports, so it can be tested plainly.

AI reaches a power the way a key does, by pressing the same ability object. Which powers a character
has comes from its cards in the power schema, so this cannot drift away from the player's keys: this
file only says how to use each power, and a card with no entry here fails at import.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from config.power_schema import PLAYER_ONLY_ABILITIES, SCHEMA

CLOSE_METRES = 40.0
VARIETY = .25


@dataclass(frozen=True, slots=True)
class Move:
    ability_id: str
    low: float      # metres
    high: float
    hold: float = 0.0   # seconds before AI lets go, or switches a sustained power back off
    weight: float = 1.0
    cinematic: bool = False  # a long scripted attack, so only one AI runs one at a time
    kick: bool = False
    stays_on: bool = False   # left running when AI's turn ends


@dataclass(frozen=True, slots=True)
class Situation:
    """What a good fighter would look at before choosing."""
    target_flying: bool = False
    target_health: float = 1.0   # as a share
    target_helpless: bool = False
    target_attacking: bool = False
    target_moving_fast: bool = False
    enemies_close: int = 1
    uses: dict | None = None     # how often each power has been used, so that none is left out


def _beam(ability_id: str, low: float, high: float) -> Move:
    return Move(ability_id, low, high, 1.8, 2.0)


def _cinematic(ability_id: str, low: float = 6.0, high: float = 600.0, weight: float = 1.0) -> Move:
    return Move(ability_id, low, high, 0.0, weight, cinematic=True)


TACTICS = {move.ability_id: move for move in (
    _beam("heat_vision", 12, 260), _beam("laser_vision", 12, 300),
    _cinematic("high_speed_attack", 15.0, weight=1.2), _cinematic("time_stop"),
    _cinematic("ground_execution"), _cinematic("neck_laser_execution"), _cinematic("void_nuclear_execution"),
    _cinematic("speed_execution", 20.0, weight=1.2),
    _cinematic("flying_punch", weight=1.2), _cinematic("aerial_grab_blast"), _cinematic("radioactive_execution"),
    Move("squad_summon", 0, 600, 0.0, 4.0),
    Move("void_form", 0, 600, 0.0, 3.0, stays_on=True), Move("radiation_blast", 0, 100, 9.2, 1.5),
    Move("melee", 0, 5.5, 0.0, .4),
)}
# Whichever of his own attacks the blow belongs to, the blasts are worth more among several enemies.
AREA_ATTACKS = {"aerial_grab_blast", "speed_execution", "time_stop", "radiation_blast",
                "void_nuclear_execution"}
FINISHERS = {"high_speed_attack", "flying_punch", "time_stop", "ground_execution", "neck_laser_execution", "radioactive_execution",
             "speed_execution", "aerial_grab_blast", "void_nuclear_execution"}
AIRBORNE_ANSWERS = {"flying_punch", "aerial_grab_blast", "radioactive_execution", "high_speed_attack",
                    "neck_laser_execution", "speed_execution", "void_nuclear_execution"}

# A character with a power this table has not heard of still uses it, at any sensible distance.
MOVES: dict[str, tuple[Move, ...]] = {
    character_id: tuple(TACTICS.get(card.ability_id, Move(card.ability_id, 0, 100, 0.0, 1.0)) for card in cards
                        if card.ability_id not in PLAYER_ONLY_ABILITIES[character_id])
    for character_id, cards in SCHEMA.items()}
# Omni-Man's six: not cards of their own, but his punches, kicks, grapples and charge.
MOVES["SQUAD"] = (Move("melee", 0, 30, 0.0, 2.0), Move("melee", 0, 30, 0.0, 1.2, kick=True),
                  Move("grab", 0, 12, .7, 1.0), Move("flight_charge", 25, 400, 0.0, 1.0))
# Soldier Boy within arm's reach of someone, up in the air, where the ground game does not apply.
MOVES["RED_AIR"] = (Move("shield_combat", 0, 5, 0.0, 2.0), Move("grab", 0, 5, .7, 1.5))
CINEMATIC_IDS = frozenset(move.ability_id for moves in MOVES.values() for move in moves if move.cinematic)


def _weigh(move: Move, situation: Situation | None) -> float:
    weight = move.weight
    if situation is None:
        return weight
    if move.ability_id in AREA_ATTACKS:
        weight *= 1.0 + .5 * max(0, situation.enemies_close - 1)
    if move.ability_id in FINISHERS and (situation.target_health < .5 or situation.target_helpless):
        weight *= 1.8
    if situation.target_flying and move.ability_id in AIRBORNE_ANSWERS:
        weight *= 1.5
    if situation.target_attacking and move.cinematic:
        weight *= 1.3  # the answer to someone mid-attack
    if situation.target_moving_fast and move.cinematic:
        weight *= 1.3  # and to someone a beam would struggle to stay on
    return weight


def choose_move(character_id: str, distance: float, ready, rng: Random,
                situation: Situation | None = None) -> Move | None:
    """A weighted pick among this character's moves that are in range and ready."""
    options = [move for move in MOVES.get(character_id, ())
               if move.low <= distance <= move.high and ready(move.ability_id)]
    if not options:
        return None
    weights = [_weigh(move, situation) for move in options]
    if situation is not None and situation.uses is not None:
        # A character's big attacks take turns, loosely: the one used least is by far the likeliest.
        uses = situation.uses
        big = [uses.get(move.ability_id, 0) for move in options if move.cinematic]
        least = min(big, default=0)
        weights = [weight * VARIETY ** (uses.get(move.ability_id, 0) - least) if move.cinematic else weight
                   for move, weight in zip(options, weights)]
    pick = rng.random() * sum(weights)
    for move, weight in zip(options, weights):
        pick -= weight
        if pick <= 0.0:
            return move
    return options[-1]


class AttackTokens:
    """At most a few AI characters attack at once, so a fight stays readable and survivable."""

    def __init__(self, limit: int = 2) -> None:
        self.limit = limit
        self.holders: set = set()

    def take(self, holder) -> bool:
        if holder in self.holders:
            return True
        if len(self.holders) >= self.limit:
            return False
        self.holders.add(holder)
        return True

    def give_back(self, holder) -> None:
        self.holders.discard(holder)
