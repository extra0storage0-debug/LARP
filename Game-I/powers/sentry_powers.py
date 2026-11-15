"""Sentry: golden energy, the shield, molecular manipulation, tendrils and the Void."""

from __future__ import annotations

from movement.flight_physics import Vec3 as SimVec3
from powers.aiming import center_of, objects_in_radius, trees_in_radius
from powers.base import AREA_EFFECT_REACH, Ability
from powers.fx import Bubble, TendrilVisual
from powers.vitals import ENERGY, EXPLOSION, PHYSICAL

GOLD = (255, 205, 70, 220)
SHIELD_TINT = (255, 208, 80, 70)
VOID_TINT = (.20, .15, .30, 1.0)
AURA_TINT = (40, 10, 70, 95)
SHIELD_ABSORPTION = .85
TENDRIL_REFRESH = .5
TENDRIL_OBJECT_INTERVAL = .3
SHOCK_INTERVAL = 3.0
VOID_REGEN_SCALE = 3.0
VOID_TENDRIL_SCALE = 2.0


class EnergyProjection(Ability):
    ability_id = "energy_projection"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.fired = 0

    def press(self) -> None:
        if not self.usable():
            return
        self.fired += 1
        radius = self.area(.03, 40.0)
        origin, direction, target = self.aim(SimVec3(self.owner.x, self.owner.y + 1.8, self.owner.z))
        self.combat.fire_projectile(self.owner, origin, direction, speed=self.p("speed"),
                                    reach=self.reach(),
                                    damage=self.p("damage") * self.owner.powers.energy_scale,
                                    radius=radius, tint=GOLD, size=1.0,
                                    force=self.force(25.0, 110.0), kind=ENERGY,
                                    crater_depth=.5 + radius * .05, target=target)


class GoldenShield(Ability):
    ability_id = "golden_shield"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.bubble = Bubble(owner, SHIELD_TINT)

    def press(self) -> None:
        if self.active:
            self.cancel()
        elif self.usable():
            self.active = True
            self.bubble.show(self.p("range") * 2.0)

    def cancel(self) -> None:
        self.active = False
        self.bubble.hide()

    def update(self, dt: float) -> None:
        if not self.active:
            return
        if self.vitals.downed or self.vitals.nullified:
            self.cancel()
            return
        self.bubble.show(self.p("range") * 2.0)

    def covers(self, character) -> bool:
        return self.active and (center_of(character) - center_of(self.owner)).length() <= self.p("range")

    def absorb(self, amount: float) -> float:
        """Take most of a hit, and return what gets through."""
        if not self.active:
            return amount
        taken = amount * SHIELD_ABSORPTION
        self.owner.powers.gain_from_damage(taken)
        return amount - taken


class MolecularManipulation(Ability):
    ability_id = "molecular_manipulation"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.reconstructed = 0
        self.disintegrated = 0

    def press(self) -> None:
        if not self.usable():
            return
        if self.owner.powers.aiming:
            self._reconstruct()
        else:
            self._disintegrate()

    def reset(self) -> None:
        super().reset()
        self.reconstructed = 0
        self.disintegrated = 0

    def _sparkle(self, point, size: float = 3.0) -> None:
        self.combat.puffs.emit(point, SimVec3(0, 3, 0), (255, 225, 130, 200), size=1.0,
                               grow=size, life=.6)

    def _disintegrate(self) -> None:
        strength = self.p("damage") * self.owner.powers.energy_scale
        target = self.target()
        if target is not None:
            point = center_of(target)
            direction = (point - center_of(self.owner)).normalized()
            self.combat.hit_character(self.owner, target, strength, ENERGY, direction,
                                      self.force(5.0, 40.0))
            self._sparkle(point)
            return
        hit = self.aim_hit(self.reach())
        if hit.kind in ("terrain", "water", "none"):
            self.say("NO TARGET FOR MOLECULAR MANIPULATION")
            return
        direction = (hit.point - center_of(self.owner)).normalized()
        self._sparkle(hit.point, abs(hit.target.scale_y))
        self.combat.damage_hit(self.owner, hit, strength, direction, kind=ENERGY,
                               force=self.force(5.0, 40.0))
        if hit.kind == "object" and hit.target.health.broken:
            self.disintegrated += 1

    def _reconstruct(self) -> None:
        hit = self.aim_hit(self.reach())
        if hit.kind == "object":
            target = hit.target
            health = target.health
            if health.health >= health.maximum_health:
                self.say("NOTHING TO RECONSTRUCT")
                return
            health.health = health.maximum_health
            target.damage_stage = 0
            target._partial_collapse_started = False
            target.color = target.original_tint
            if target.crack_overlay is not None:
                target.crack_overlay.visible = False
            facade = getattr(target, "facade_detail", None)
            if facade is not None:
                facade.color = target.original_tint
            self.game.world.record_damage(target)
        elif hit.kind == "tree":
            tree = hit.target
            if tree.tree_health >= tree.tree_max_health:
                self.say("NOTHING TO RECONSTRUCT")
                return
            self.game.world.restore_tree(tree)
        else:
            self.say("NOTHING TO RECONSTRUCT")
            return
        self.reconstructed += 1
        self.say("RECONSTRUCTED")


class VoidTendrils(Ability):
    ability_id = "void_tendrils"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.grips: list[list] = []  # target, extended length, tendril visual
        self._visuals: list[TendrilVisual] = []
        self._object_timer = 0.0
        self._refresh_timer = 0.0

    def press(self) -> None:
        if self.active:
            self.cancel()
        elif self.usable():
            self.active = True
            self.grips = []
            self._refresh_timer = 0.0
            self._seize()
            if not self.grips:
                self.say("TENDRILS FIND NOTHING TO HOLD")

    def _seize(self) -> None:
        """Hold every enemy in range, letting go of those no longer there."""
        origin = center_of(self.owner)
        reach = self.reach()
        gripped = {grip[0]: grip[1] for grip in self.grips}
        for grip in self.grips:
            grip[2].hide()
        self.grips = []
        for target in self.combat.hostiles_of(self.owner):
            if (center_of(target) - origin).length() > reach:
                continue
            index = len(self.grips)
            while index >= len(self._visuals):
                self._visuals.append(TendrilVisual())
            self.grips.append([target, gripped.get(target, 0.0), self._visuals[index]])

    def update(self, dt: float) -> None:
        if not self.active:
            return
        if self.vitals.immobile or self.vitals.nullified:
            self.cancel()
            return
        self._refresh_timer -= dt
        if self._refresh_timer <= 0.0:
            self._refresh_timer = TENDRIL_REFRESH
            self._seize()
        origin = SimVec3(self.owner.x, self.owner.y + 1.6, self.owner.z)
        scale = self.owner.powers.tendril_scale
        damage = self.p("damage") * scale * dt
        for grip in self.grips:
            target, length, visual = grip
            point = center_of(target)
            distance = (point - origin).length()
            length = min(distance, length + self.p("speed") * dt)
            grip[1] = length
            if target.vitals.downed:
                visual.hide()
                continue
            tip = origin + (point - origin).normalized() * length
            visual.show(origin, tip, self.game.elapsed)
            if length >= distance - .01:
                target.vitals.add_status("restrained", .25)
                self.combat.hit_character(self.owner, target, damage, PHYSICAL)
        self._object_timer -= dt
        if self._object_timer <= 0.0:
            self._object_timer = TENDRIL_OBJECT_INTERVAL
            reach = min(self.reach() * .5, AREA_EFFECT_REACH * .2)
            amount = self.p("damage") * .1 * scale
            for obj in objects_in_radius(self.game, origin, reach):
                obj.take_damage(amount, impact_position=origin)
            for tree in tuple(trees_in_radius(self.game, origin, reach)):
                self.game.world.damage_tree(tree, amount, SimVec3(tree.x - origin.x, .2,
                                                                  tree.z - origin.z))

    def cancel(self) -> None:
        self.active = False
        for grip in self.grips:
            grip[2].hide()
        self.grips = []


class VoidUnleashed(Ability):
    ability_id = "void_unleashed"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self._shock_timer = 0.0
        self.aura = Bubble(owner, AURA_TINT)

    @property
    def engaged(self) -> bool:
        return self.active

    @property
    def attack_scale(self) -> float:
        return self.boost(1.2, 2.2)

    @property
    def energy_attack_scale(self) -> float:
        return self.boost(1.2, 2.0)

    @property
    def tendril_scale(self) -> float:
        return VOID_TENDRIL_SCALE

    def press(self) -> None:
        if self.active:
            self.cancel()
        elif self.usable():
            self.active = True
            self._shock_timer = 0.0
            self.owner.pose_root.setColorScale(*VOID_TINT)
            self.aura.show(6.0)
            self.vitals.regen_scale = VOID_REGEN_SCALE
            self.say("THE VOID UNLEASHED")
            self.combat.burst(center_of(self.owner), 16.0, 2.0, (105, 40, 170))

    def update(self, dt: float) -> None:
        if not self.active:
            return
        if self.vitals.downed:
            self.cancel()
            return
        self._shock_timer -= dt
        if self._shock_timer <= 0.0:
            self._shock_timer = SHOCK_INTERVAL
            owner = self.owner
            self.combat.blast(owner, SimVec3(owner.x, owner.y + .5, owner.z), self.area(.1, 90.0),
                              self.p("damage"), self.force(20.0, 100.0), kind=EXPLOSION,
                              play_sound=False, tint=(105, 40, 170))

    def cancel(self) -> None:
        if not self.active:
            return
        self.active = False
        self.vitals.regen_scale = 1.0
        self.owner.pose_root.clearColorScale()
        self.aura.hide()
        self.say("THE VOID RECEDES")
