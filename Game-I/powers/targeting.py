"""The one target system: every character's nearest valid enemy, and the player's manual lock.

The manual lock is chosen with Q and the mouse wheel. It ends when the player releases it or its
target stops being valid. Only enemies can be locked: allies and civilians are never candidates.
"""

from __future__ import annotations

from movement.flight_physics import Vec3 as SimVec3
from powers.aiming import center_of, in_cone

ACQUIRE_INTERVAL = .2
FORWARD_PREFERENCE = .85  # an enemy ahead counts as this much closer than it really is
STICKINESS = .8           # a new enemy must score this much better to replace the current one
FORWARD_HALF_ANGLE = 45.0
CANDIDATE_SECONDS = 1.0   # civilians come and go with the chunks; the roster clears this itself
CIVILIAN_CENTER = 1.0
AUTO_LOCK_SECONDS = 4.0


def is_civilian(target) -> bool:
    return not hasattr(target, "vitals")


class TargetSystem:
    def __init__(self, combat) -> None:
        self.combat = combat
        self.enabled = True  # always on in play; AI always uses it
        self.manual = None   # what the player has locked with Q
        self._locks: dict = {}
        self._next: dict = {}
        self._candidates = None
        self._candidates_until = 0.0
        self._auto_wait = 0.0     # the one timer there is: nothing can start a second
        self._target_lost = False

    def clear(self) -> None:
        """Forget every automatic lock, after a character switch or a team change.

        A manual lock survives this, for as long as its target is still valid.
        """
        self._locks.clear()
        self._next.clear()
        self._candidates = None

    # -- the player's manual lock ----------------------------------------
    def _lockable(self, target) -> bool:
        game = self.combat.game
        if target is None or target is game.sentry:
            return False
        if is_civilian(target):
            return False
        return not target.parked and not target.vitals.downed and self.combat.hostile(game.sentry, target)

    def _build_candidates(self) -> list:
        """Every enemy of the player, in an order that stays put while cycling."""
        game = self.combat.game
        player = game.sentry
        return [character for character in (*game.teams.characters.values(), *game.teams.summons)
                if character is not player and self.combat.hostile(player, character)]

    def candidates(self) -> list:
        """Everything the player could lock now. Cached, so nothing searches the scene every frame."""
        now = self.combat.game.elapsed
        if self._candidates is None or now >= self._candidates_until:
            self._candidates = self._build_candidates()
            self._candidates_until = now + CANDIDATE_SECONDS
        return [target for target in self._candidates if self._lockable(target)]

    def _set_manual(self, target, message: str) -> None:
        self.manual = target
        self.combat.game.notify(message)
        self.combat.refresh_target_indicator()

    def toggle_manual(self) -> None:
        """Q. Starts on the enemy automatic targeting already has, or whoever is nearest otherwise."""
        if self.manual is not None:
            self._set_manual(None, "TARGET LOCK OFF")
            return
        player = self.combat.game.sentry
        target = self.lock_of(player)
        if target is None:
            options = self.candidates()
            origin = center_of(player)
            target = min(options, key=lambda option: (self.point_of(option) - origin).length(), default=None)
        if target is None:
            self.combat.game.notify("NO TARGET TO LOCK")
            return
        self._set_manual(target, f"LOCKED: {target.display_name}")

    def cycle_manual(self, step: int) -> None:
        """The mouse wheel, while locked: the next or previous target, with no need to release it first."""
        options = self.candidates()
        if not options:
            return
        index = options.index(self.manual) + step if self.manual in options else 0
        target = options[index % len(options)]
        self._set_manual(target, f"LOCKED: {target.display_name}")

    def update_manual(self) -> None:
        """Once a frame: a target that has died, gone or become the player releases the lock."""
        if self.manual is not None and not self._lockable(self.manual):
            self._set_manual(None, "TARGET LOST")
            self._target_lost = True

    def update_auto(self, enabled: bool, seconds: float) -> None:
        """Auto Target Lock: Q's own function every four seconds, and at once when a target is lost."""
        lost, self._target_lost = self._target_lost, False
        if not enabled:
            self._auto_wait = 0.0  # so that switching it on locks straight away
            return
        self._auto_wait -= seconds
        if self._auto_wait <= 0.0 or lost:
            self._auto_wait = AUTO_LOCK_SECONDS
            self.auto_lock()

    def auto_lock(self) -> None:
        """Lock the nearest enemy through toggle_manual. Q toggles, so it is only called when that means locking:
        with something locked already it would let go, so the lock is cleared first, and only for a change."""
        player = self.combat.game.sentry
        enemies = self.combat.hostiles_of(player)
        if not enemies:
            return
        origin = center_of(player)
        nearest = min(enemies, key=lambda enemy: (center_of(enemy) - origin).length())
        if self.manual is nearest:
            return
        self.manual = None
        self._locks[player] = nearest  # where Q starts from
        self._next[player] = self.combat.game.elapsed + ACQUIRE_INTERVAL
        self.toggle_manual()

    @staticmethod
    def point_of(target) -> SimVec3:
        if is_civilian(target):
            entity = target.entity
            return SimVec3(float(entity.x), float(entity.y) + CIVILIAN_CENTER, float(entity.z))
        return center_of(target)

    def locked_point(self) -> SimVec3 | None:
        """Where the camera should look, or None for the normal free camera."""
        return None if self.manual is None else self.point_of(self.manual)

    def _manual_enemy_of(self, character):
        manual = self.manual
        if (manual is not None and character.controlled and not is_civilian(manual)
                and not manual.vitals.downed and not manual.parked and self.combat.hostile(character, manual)):
            return manual
        return None

    def _valid(self, character, target) -> bool:
        return (not target.parked and not target.vitals.downed
                and self.combat.hostile(character, target))

    def _score(self, character, target, origin, forward) -> float:
        point = center_of(target)
        distance = (point - origin).length()
        if in_cone(origin, forward, point, distance + 1.0, FORWARD_HALF_ANGLE):
            return distance * FORWARD_PREFERENCE
        return distance

    def _acquire(self, character, current, reach=None, exclude=None):
        origin = center_of(character)
        forward = self.combat.game.planet.heading(origin, character.local_yaw)
        best, best_score = None, None
        for candidate in self.combat.hostiles_of(character):
            if candidate is exclude:
                continue
            if reach is not None and (center_of(candidate) - origin).length() > reach:
                continue
            score = self._score(character, candidate, origin, forward)
            if best is None or score < best_score:
                best, best_score = candidate, score
        if (current is not None and best is not None and current is not exclude
                and self._score(character, current, origin, forward) * STICKINESS <= best_score):
            return current
        return best

    def lock_of(self, character):
        """The manual lock if it is an enemy, or the cached nearest enemy, searched a few times a second."""
        manual = self._manual_enemy_of(character)
        if manual is not None:
            return manual
        now = self.combat.game.elapsed
        current = self._locks.get(character)
        if current is not None and not self._valid(character, current):
            current = None
            self._next[character] = now
        if now >= self._next.get(character, 0.0):
            current = self._acquire(character, current)
            self._next[character] = now + ACQUIRE_INTERVAL
        self._locks[character] = current
        return current

    def for_ability(self, owner, reach: float, exclude=None):
        """The enemy an ability should go for, or None to fall back to where the camera aims."""
        if owner.controlled and (not self.enabled or owner.powers.aiming):
            return None
        manual = self._manual_enemy_of(owner)
        if manual is not None and manual is not exclude \
                and (center_of(manual) - center_of(owner)).length() > reach:
            return None  # out of Range: it fires where the camera looks, not at somebody else
        lock = self.lock_of(owner)
        if lock is not None and lock is not exclude \
                and (center_of(lock) - center_of(owner)).length() <= reach:
            return lock
        return self._acquire(owner, None, reach, exclude)

    def nearest_to(self, owner, point, reach: float):
        """The enemy of ``owner`` closest to a point, for something already in flight."""
        best, best_distance = None, reach
        for candidate in self.combat.hostiles_of(owner):
            distance = (center_of(candidate) - point).length()
            if distance <= best_distance:
                best, best_distance = candidate, distance
        return best
