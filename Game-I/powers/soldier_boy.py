"""Soldier Boy: the shield in hand and thrown, the chest blast, and power nullification."""

from __future__ import annotations

from math import cos, radians

from ursina import Entity, Vec3, color

from movement.flight_physics import Vec3 as SimVec3
from powers.aiming import center_of, trace
from powers.base import Ability
from powers.common import Melee
from powers.fx import Bubble
from powers.vitals import EXPLOSION, PHYSICAL, RADIATION

RETRIEVE_DISTANCE = 4.0
AUTO_RETURN_SECONDS = 6.0
MIN_RETURN_SPEED = 170.0
RADIATION_TINT = (120, 255, 150, 230)
CHEST_HEIGHT = 1.75
COUNTER_WINDOW = 1.5
COUNTER_SCALE = 1.8
PARRY_SECONDS = .3
BLOCK_REDUCTION = .8
BLOCK_KNOCKBACK = .2
EXPLOSION_COVER = .55
BASE_BLOCK_ANGLE = 60.0
BLOCK_ANGLE_PER_METRE = 25.0
SHIELD_SIZE = 1.1
NULLIFY_SECONDS = 20.0
DISCHARGE_NULLIFY_SECONDS = 45.0
BOLT_SPEED = 1500.0
MAX_CRATER = 30.0


def chest_point(owner) -> SimVec3:
    return SimVec3(owner.x, owner.y + CHEST_HEIGHT, owner.z)


def fire_at_distant_target(ability, radius: float, damage: float, force: float, nullify) -> None:
    """A blast only reaches so far; an enemy beyond it is hit by a radioactive bolt instead."""
    owner = ability.owner
    target = ability.target()
    if target is None or (center_of(target) - center_of(owner)).length() <= radius:
        return
    origin = chest_point(owner)
    ability.combat.fire_projectile(owner, origin, (center_of(target) - origin).normalized(),
                                   speed=BOLT_SPEED, reach=ability.reach(), damage=damage,
                                   radius=min(radius, 30.0), tint=RADIATION_TINT, size=1.0,
                                   force=force, kind=RADIATION, target=target, nullify=nullify)


class ShieldCombat(Melee):
    ability_id = "shield_combat"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.counter_until = 0.0

    def strength_scale(self) -> float:
        scale = super().strength_scale()
        powers = self.owner.powers
        if not powers.abilities["shield_throw"].in_hand:
            scale *= .6  # his bare hands, while the shield is away
        if self.game.elapsed < self.counter_until:
            scale *= COUNTER_SCALE
        return scale

    def land_blow(self, target, kick: bool = False) -> None:
        super().land_blow(target, kick)
        if self.game.elapsed < self.counter_until:
            self.counter_until = 0.0
            self.say("COUNTERATTACK")


class ShieldThrow(Ability):
    ability_id = "shield_throw"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.state = "hand"  # hand, flying, resting, returning
        self.position = SimVec3()
        self.direction = SimVec3()
        self.target_character = None
        self.travelled = 0.0
        self.away_for = 0.0
        self.already_hit: set = set()
        self.model = Entity(model="sphere", color=color.rgb32(186, 192, 198), scale=(1.2, 1.2, .16),
                            collider=None, visible=False, add_to_scene_entities=False)

    @property
    def in_hand(self) -> bool:
        return self.state == "hand"

    def press(self) -> None:
        if self.state == "hand":
            if self.usable():
                self._throw()
        else:
            self._recall()

    def _throw(self) -> None:
        owner = self.owner
        start = SimVec3(owner.x, owner.y + 1.6, owner.z)
        _origin, self.direction, self.target_character = self.aim(start)
        self.position = start + self.direction * 1.2
        self.travelled = 0.0
        self.away_for = 0.0
        self.already_hit = {owner}
        self.state = "flying"
        self.active = True
        owner.powers.abilities["shield_defence"].lower()
        self.model.visible = True
        owner.show_shield(False)
        self.game.world.play_power_sound(.25)

    def _recall(self) -> None:
        if self.state in ("flying", "resting"):
            self.state = "returning"
            self.say("SHIELD RETURNING")

    def _catch(self) -> None:
        self.state = "hand"
        self.active = False
        self.model.visible = False
        self.owner.show_shield(True)

    def update(self, dt: float) -> None:
        if self.state == "hand":
            return
        self.away_for += dt
        owner = self.owner
        if self.state == "flying":
            self._fly(dt)
        elif self.state == "resting":
            near = (center_of(owner) - self.position).length() <= RETRIEVE_DISTANCE
            if near:
                self._catch()
                self.say("SHIELD RETRIEVED")
                return
        if self.state != "returning" and self.away_for >= AUTO_RETURN_SECONDS:
            self.state = "returning"
        if self.state == "returning":
            home = SimVec3(owner.x, owner.y + 1.6, owner.z)
            offset = home - self.position
            distance = offset.length()
            speed = max(MIN_RETURN_SPEED, self.p("speed"))
            if distance <= speed * dt + 1.0:
                self._catch()
                return
            self.position = self.position + offset.normalized() * (speed * dt)
        self.model.position = Vec3(self.position.x, self.position.y, self.position.z)
        self.model.rotation_y += 720.0 * dt

    def _fly(self, dt: float) -> None:
        length = self.p("speed") * dt
        combat = self.combat
        target = self.target_character
        if target is not None:
            if target.vitals.downed or target.parked:
                self.target_character = None
            else:
                self.direction = (center_of(target) - self.position).normalized()
        hit = trace(self.game, self.position, self.direction, length, ignore=tuple(self.already_hit),
                    radius=SHIELD_SIZE * .5, characters=combat.hostiles_of(self.owner))
        strength = self.owner.powers.strength * self.owner.powers.attack_scale
        damage = self.p("damage") * strength
        force = self.force(30.0, 130.0)
        if hit.kind == "character":
            self.already_hit.add(hit.target)
            combat.hit_character(self.owner, hit.target, damage, PHYSICAL, self.direction, force)
            combat.burst(hit.point, 3.0, .6)
            self.position = hit.point
            self.state = "returning"
            return
        if hit.kind in ("object", "tree"):
            self.already_hit.add(hit.target)
            combat.damage_hit(self.owner, hit, damage, self.direction, kind=PHYSICAL, force=force)
            combat.burst(hit.point, 3.0, .6)
            self.position = hit.point
            self.state = "returning"
            return
        if hit.kind in ("terrain", "water"):
            combat.burst(hit.point, 2.0, .4)
            self.position = hit.point
            self.state = "resting"
            return
        self.position = self.position + self.direction * length
        self.travelled += length
        if self.travelled >= self.reach():
            self.state = "resting"

    def cancel(self) -> None:
        """A swap keeps the shield where it is; it comes back on its own."""
        return None

    def reset(self) -> None:
        self._catch()


class ShieldDefence(Ability):
    ability_id = "shield_defence"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.raised_for = None
        self.parries = 0

    @property
    def raised(self) -> bool:
        return self.raised_for is not None

    def press(self) -> None:
        if self.raised:
            self.lower()
        elif self.usable() and self.owner.powers.abilities["shield_throw"].in_hand:
            self.raised_for = 0.0
            self.active = True

    def lower(self) -> None:
        self.raised_for = None
        self.active = False

    def cancel(self) -> None:
        self.lower()

    def update(self, dt: float) -> None:
        if self.raised_for is None:
            return
        if self.vitals.downed:
            self.lower()
            return
        self.raised_for += dt
        self.owner.left_arm.rotation_x = -80.0
        self.owner.left_arm.rotation_z = -28.0

    def block_angle(self) -> float:
        """How much of the circle the shield covers, which is what Range means here."""
        return min(360.0, BASE_BLOCK_ANGLE + self.p("range") * BLOCK_ANGLE_PER_METRE)

    def faces(self, direction) -> bool:
        """Whether an attack travelling along ``direction`` comes into the shield's arc."""
        if direction is None:
            return True
        forward = self.facing()
        into = -(forward.x * direction.x + forward.y * direction.y + forward.z * direction.z)
        return into >= cos(radians(self.block_angle() * .5))

    def absorb(self, amount: float, kind: str, direction) -> tuple[float, float]:
        """Return (damage through, knockback scale)."""
        if not self.raised or not self.faces(direction):
            return amount, 1.0
        if kind == EXPLOSION:
            return amount * (1.0 - EXPLOSION_COVER), BLOCK_KNOCKBACK
        if self.raised_for <= PARRY_SECONDS:
            self.parries += 1
            combat_ability = self.owner.powers.abilities["shield_combat"]
            combat_ability.counter_until = self.game.elapsed + COUNTER_WINDOW
            self.say("PARRY")
            return 0.0, 0.0
        return amount * (1.0 - BLOCK_REDUCTION), BLOCK_KNOCKBACK


class ChestBlast(Ability):
    ability_id = "chest_blast"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.armed = False
        self.glow = Bubble(owner, (120, 255, 150, 0), center=CHEST_HEIGHT)
        self.discharges = 0

    def press(self) -> None:
        if not self.armed and self.usable():
            self.armed = True
            self.active = True

    def update(self, dt: float) -> None:
        if not self.armed:
            return
        if self.vitals.immobile:
            self.cancel()
            return
        self.glow.show(3.0, (120, 255, 150, 240))
        self.combat.puffs.emit(chest_point(self.owner), SimVec3(0, 1.5, 0), (120, 255, 150, 120),
                               size=.4, grow=2.0, life=.4)

    def release(self) -> None:
        if not self.armed:
            return
        self.armed = False
        self.active = False
        self.glow.hide()
        self.discharges += 1
        owner = self.owner
        radius = self.area(.1, 120.0)
        damage, force = self.p("damage"), self.force(40.0, 160.0)
        nullify = owner.powers.abilities["nullification"].settings(NULLIFY_SECONDS)
        fire_at_distant_target(self, radius, damage, force, nullify)
        self.combat.blast(owner, chest_point(owner), radius, damage, force, kind=RADIATION,
                          crater=(min(MAX_CRATER, radius * .4), 3.0, "radiation"),
                          cracks=True, burst_scale=1.5, nullify=nullify)

    def cancel(self) -> None:
        self.armed = False
        self.active = False
        self.glow.hide()

    def on_input_lost(self) -> None:
        self.cancel()

    def reset(self) -> None:
        super().reset()
        self.discharges = 0


class Nullification(Ability):
    """Carried by his discharge rather than pressed; holds the target rules."""

    ability_id = "nullification"

    def settings(self, seconds: float) -> dict:
        return {"radius": self.reach(), "seconds": seconds}


class RadioactiveDischarge(Ability):
    ability_id = "radioactive_discharge"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.flash = Bubble(owner, (120, 255, 150, 0), center=CHEST_HEIGHT)
        self.flash_left = 0.0
        self.discharges = 0

    def press(self) -> None:
        if not self.usable():
            return
        self.discharges += 1
        owner = self.owner
        radius = self.area(.15, 150.0)
        self.flash_left = .6
        damage, force = self.p("damage"), self.force(60.0, 200.0)
        nullify = owner.powers.abilities["nullification"].settings(DISCHARGE_NULLIFY_SECONDS)
        fire_at_distant_target(self, radius, damage, force, nullify)
        self.combat.blast(owner, chest_point(owner), radius, damage, force, kind=RADIATION,
                          crater=(min(MAX_CRATER, radius * .5), 6.0, "radiation-max"),
                          cracks=True, burst_scale=2.0, nullify=nullify)
        self.say("MAXIMUM RADIOACTIVE DISCHARGE")

    def update(self, dt: float) -> None:
        if self.flash_left > 0.0:
            self.flash_left -= dt
            self.flash.show(8.0 * (1.0 - self.flash_left / .6) + 1.0,
                            (120, 255, 150, int(220 * max(0.0, self.flash_left / .6))))
            if self.flash_left <= 0.0:
                self.flash.hide()

    def reset(self) -> None:
        super().reset()
        self.discharges = 0


__all__ = ["ChestBlast", "Nullification", "RadioactiveDischarge", "ShieldCombat", "ShieldDefence",
           "ShieldThrow", "PHYSICAL"]
