"""Who can hit whom, and what damage, blasts, projectiles and throws do to the world."""

from __future__ import annotations

from math import sqrt

from ursina import color, scene

from config.character_roster import ENEMY_TEAM, MY_TEAM
from config.power_schema import PowerSettings
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers.aiming import center_of, objects_in_radius, trace
from powers.fx import BeamVisual, Bolt, GroundCracks, LockReticle, MarkerPool, PuffPool
from powers.targeting import TargetSystem, is_civilian
from powers.vitals import COLD, ENERGY, EXPLOSION, HEAT, IMPACT, PHYSICAL, RADIATION
from world.elements import WorldElements
from world.interactive_objects import DestructibleEntity

BLAST_TINTS = {RADIATION: (110, 255, 140), ENERGY: (255, 205, 70)}
BEAM_POOL = 4
BOLT_POOL = 6
RAM_MIN_SPEED = 60.0
RAM_COOLDOWN = .6
CRASH_MIN_SPEED = 70.0
THROWN_MAX_SECONDS = 4.0
SCORCH_INTERVAL = .35
CUT_INTERVAL = 1.4
OUTSIDE_BLAST_SCALE = .25  # chain explosions from breaking objects, with nobody behind them
MAX_KNOCKBACK = 180.0
FLINCH_FULL_FORCE = 120.0
WAVE_SPEED, WAVE_FORCE, WAVE_MAX_POWER, WAVE_MAX_REACH = 170.0, 25.0, 6.0, 700.0
# Abilities have no cooldowns and start at full power, so this is what keeps a fight with AI
# survivable: however hard it hits, AI takes at most this share of a target's health per second.
AI_DAMAGE_PER_SECOND = .06
TIME_STOP_TINT = (150, 170, 210, 46)
WORLD_STOP_SECONDS = 30.0
WORLD_STOP_TINT = (105, 135, 225, 62)


class Projectile:
    __slots__ = ("owner", "position", "velocity", "reach", "travelled", "damage", "radius", "tint",
                 "size", "force", "kind", "crater_depth", "bolt", "target", "nullify")

    def __init__(self, owner, position, velocity, reach, damage, radius, tint, size, force, kind,
                 crater_depth, bolt, target=None, nullify=None) -> None:
        self.owner, self.position, self.velocity = owner, position, velocity
        self.reach, self.damage, self.radius = reach, damage, radius
        self.tint, self.size, self.force, self.kind = tint, size, force, kind
        self.crater_depth, self.bolt = crater_depth, bolt
        self.target, self.nullify = target, nullify
        self.travelled = 0.0
WEAKENED_DAMAGE = .6  # what a character shadowed by Sentry's Void still hits for


class CombatSystem:
    def __init__(self, game) -> None:
        self.game = game
        self.settings = PowerSettings()
        self.targets = TargetSystem(self)
        self.shown_target = None
        self.time_stop_owner = None
        self.time_stop_target = None
        self.world_stop_left = 0.0
        self._frozen_for = 0.0
        self._ai_spent: dict = {}
        quality = str(game.settings.quality).lower()
        self.puffs = PuffPool(quality)
        self.markers = MarkerPool()
        self.lock_reticle = LockReticle()
        self.cracks = GroundCracks()
        self._wave = None
        scene.set_shader_input("u_blast_wave", (0.0, 0.0, 0.0, -1000.0))
        scene.set_shader_input("u_blast_power", (0.0, 1.0, 0.0, 0.0))
        self.elements = WorldElements(game)
        self._beams = [BeamVisual() for _ in range(BEAM_POOL)]
        self._bolts = [Bolt() for _ in range(BOLT_POOL)]
        self.projectiles: list[Projectile] = []
        self._thrown_characters: list[list] = []
        self._thrown_objects: list[list] = []
        self._own_blast = False
        self._scorch_timer = 0.0
        self._cut_timer = 0.0
        self._ram_ready: dict = {}
        self.ai_damage_scale = 1.0
        self.ai_powers_enabled = True

    @property
    def in_world(self) -> list:
        teams = self.game.teams
        return [*(teams.characters[cid] for cid in teams.characters
                  if not teams.characters[cid].parked), *teams.summons]

    # -- time stop -------------------------------------------------------
    # World time is simply not advanced: anything frozen is left exactly as it was, velocity, AI
    # state and pose included, so there is nothing to copy and nothing that can fail to be restored.
    # Two things can hold it, independently: a scripted sequence (key 3, Superman's 4), and T.
    @property
    def sequence_running(self) -> bool:
        return self.time_stop_owner is not None

    @property
    def world_stopped(self) -> bool:
        return self.world_stop_left > 0.0

    @property
    def time_stopped(self) -> bool:
        return self.sequence_running or self.world_stopped

    def begin_time_stop(self, owner, target) -> None:
        """Only the player stops time. AI plays the same attack out with the world still running."""
        if not owner.controlled:
            return
        self.time_stop_owner, self.time_stop_target = owner, target
        self.show_time_stop()

    def end_time_stop(self, owner=None) -> None:
        if owner is not None and owner is not self.time_stop_owner:
            return  # an AI's attack ending has no say over a stop the player is holding
        self.time_stop_owner = self.time_stop_target = None
        self.show_time_stop()

    def begin_world_stop(self) -> bool:
        """T. A press while it is already running neither restarts nor extends it."""
        if self.world_stopped:
            return False
        self.world_stop_left = WORLD_STOP_SECONDS
        self.game.hud.start_time_ripple()
        self.game.camera_impulse = max(self.game.camera_impulse, .6)
        self.game.world.play_power_sound(.4)
        self.show_time_stop()
        return True

    def end_world_stop(self) -> None:
        self.world_stop_left = 0.0
        self.show_time_stop()

    def show_time_stop(self) -> None:
        """Put the tint, label and countdown right for whatever is holding time now."""
        hud = self.game.hud
        if self.world_stopped:
            hud.set_vision(WORLD_STOP_TINT, "")
            hud.set_countdown(self.world_stop_left, WORLD_STOP_TINT)
        else:
            hud.set_countdown(None)
            if self.sequence_running:
                hud.set_vision(TIME_STOP_TINT, "TIME STOPPED")
            else:
                hud.set_vision(None, "")

    def _advance_world_stop(self) -> None:
        """Counted in real seconds, so a slow frame cannot stretch it past 30."""
        if not self.world_stopped:
            return
        self.world_stop_left -= self.game.frame_seconds
        if self.world_stop_left <= 1e-6:
            self.end_world_stop()
            self.game.hud.start_time_ripple()
            self.game.notify("TIME RESUMES")
        else:
            self.game.hud.set_countdown(self.world_stop_left, WORLD_STOP_TINT)

    def _update_time_stopped(self, dt: float) -> None:
        """Only the two people in the sequence carry on; nothing else's state is touched."""
        if self.time_stop_owner.motion is None or self.time_stop_owner.parked:
            self.end_time_stop()  # whatever held it has gone, however it went: time is never left stopped
            return
        for character in (self.time_stop_owner, self.time_stop_target):
            character.vitals.tick(dt)
        self.time_stop_owner.powers.update(dt)
        self.refresh_target_indicator()
        self.puffs.step(dt)

    def _update_world_stopped(self, dt: float) -> None:
        """The player is the one thing still in time, along with what the player has fired."""
        self._scorch_timer = max(0.0, self._scorch_timer - dt)
        self._cut_timer = max(0.0, self._cut_timer - dt)
        player = self.game.sentry
        self._advance_character(player, dt, self.game.elapsed)
        for shot in tuple(self.projectiles):
            if shot.owner is player and not self._step_projectile(shot, dt):
                self._end_projectile(shot)
        self.refresh_target_indicator()
        self.puffs.step(dt)

    def _advance_character(self, character, dt: float, now: float) -> None:
        was_downed = character.vitals.downed
        character.vitals.tick(dt)
        if was_downed and not character.vitals.downed:
            character.on_revived()
        character.powers.update(dt)
        self._ram_and_crash(character, now)

    # -- sides -----------------------------------------------------------
    def hostile(self, a, b) -> bool:
        if a is b or a is None or b is None:
            return False
        state = self.game.teams.state
        teams = {state.team_of(a.character_id), state.team_of(b.character_id)}
        return teams == {MY_TEAM, ENEMY_TEAM}

    def hostiles_of(self, character) -> list:
        return [other for other in self.in_world
                if self.hostile(character, other) and not other.vitals.downed]

    def others_of(self, character) -> list:
        """Everyone a beam can stop on: enemies, but never your own side."""
        return self.hostiles_of(character)

    # -- pools -----------------------------------------------------------
    def acquire_beam(self):
        return self._beams.pop() if self._beams else None

    def release_beam(self, visual) -> None:
        visual.hide()
        self._beams.append(visual)

    # -- damage ----------------------------------------------------------
    def hit_character(self, source, target, amount: float, kind: str = PHYSICAL, direction=None,
                      force: float = 0.0) -> float:
        """Damage and knock back a character, through its evasion and defences."""
        if source is not None and not self.hostile(source, target):
            return 0.0
        if target.is_evading or target.vitals.downed:
            return 0.0
        if source is not None and source.vitals.has("weakened"):
            amount *= WEAKENED_DAMAGE
        if source is not None and not source.controlled:
            amount = self._ai_limited(target, amount * self.ai_damage_scale)
        amount, knock_scale = self._through_defences(target, amount, kind, direction)
        dealt = target.vitals.take(amount, kind)
        target.powers.gain_from_damage(amount)
        if direction is not None and force > 0.0 and knock_scale > 0.0:
            self.push(target, direction * (force * knock_scale))
            self._rock_the_body(target, direction, force * knock_scale)
        if target is self.game.sentry and dealt > 0.0:
            self.game.camera_impulse = max(self.game.camera_impulse, min(1.5, .2 + dealt * .006))
        if target.vitals.downed:
            target.on_downed()
        return dealt

    @staticmethod
    def _rock_the_body(target, direction, force: float) -> None:
        visual = target.visual
        if hasattr(visual, "flinch"):
            visual.flinch(.25 + force / FLINCH_FULL_FORCE, 1.0 if direction.x >= 0.0 else -1.0)

    def _start_blast_wave(self, origin, radius: float, force: float) -> None:
        """Whatever a blast does not break, its wave bends: every tree and blade of grass, on the GPU, for nothing."""
        self._wave = [float(origin.x), float(origin.y), float(origin.z), 0.0, min(WAVE_MAX_POWER, force / WAVE_FORCE),
                      min(WAVE_MAX_REACH, radius * 2.5)]

    def _advance_blast_wave(self, dt: float) -> None:
        wave = self._wave
        if wave is None:
            return
        wave[3] += WAVE_SPEED * dt
        fade = 1.0 - wave[3] / wave[5]
        if fade <= 0.0:
            self._wave = None
            scene.set_shader_input("u_blast_power", (0.0, 1.0, 0.0, 0.0))
            return
        scene.set_shader_input("u_blast_wave", (wave[0], wave[1], wave[2], wave[3]))
        scene.set_shader_input("u_blast_power", (wave[4] * fade, wave[3], 0.0, 0.0))

    def _ai_limited(self, target, amount: float) -> float:
        now = self.game.elapsed
        started, spent = self._ai_spent.get(target, (now, 0.0))
        if now - started >= 1.0:
            started, spent = now, 0.0
        amount = min(amount, max(0.0, target.vitals.max_health * AI_DAMAGE_PER_SECOND - spent))
        self._ai_spent[target] = (started, spent + amount)
        return amount

    def _through_defences(self, target, amount, kind, direction) -> tuple[float, float]:
        abilities = target.powers.abilities
        # A golden barrier covers its bearer and anyone on their side standing inside it.
        for bearer in self.game.teams.characters.values():
            shield = bearer.powers.abilities.get("golden_shield")
            if shield is not None and not bearer.parked and shield.covers(target) and not self.hostile(bearer, target):
                amount = shield.absorb(amount)
        defence = abilities.get("shield_defence")
        if defence is not None:
            return defence.absorb(amount, kind, direction)
        return amount, 1.0

    def push(self, target, impulse: SimVec3) -> None:
        target.apply_knockback((impulse * target.vitals.knockback_scale()).clamped(MAX_KNOCKBACK))

    def damage_hit(self, source, hit, amount: float, direction: SimVec3, *, kind: str = PHYSICAL,
                   force: float = 0.0) -> None:
        """Route damage to whatever a trace found."""
        world = self.game.world
        if hit.kind == "character":
            self.hit_character(source, hit.target, amount, kind, direction, force)
        elif hit.kind == "tree":
            scale = self.elements.damage_scale_for(hit.target, kind)
            world.damage_tree(hit.target, amount * scale, direction * max(1.0, force),
                              impact_position=hit.point, impact_speed=force)
        elif hit.kind == "object":
            self.damage_object(hit.target, amount, direction, force, hit.point)

    def damage_object(self, obj, amount, direction, force, point=None) -> None:
        impulse = None
        if force > 0.0 and direction is not None and not obj.anchored:
            obj.dynamic = True
            impulse = direction * force
        obj.take_damage(amount, impulse, impact_position=point, impact_speed=force)

    def heat_effects(self, hit, owner, intensity: float = 1.0) -> None:
        """What heat does beyond damage: fire, scorching and slow cuts in the ground."""
        if hit.kind == "tree":
            self.elements.ignite_tree(hit.target)
        elif hit.kind == "object":
            hit.target.heat_until = max(hit.target.heat_until, self.game.elapsed + .3)
        elif hit.kind == "terrain":
            if self._scorch_timer <= 0.0:
                self._scorch_timer = SCORCH_INTERVAL
                self.elements.add_scorch(hit.point, 1.2 + .6 * intensity)
                self.elements.start_fire(hit.point, owner)
            if self._cut_timer <= 0.0:
                self._cut_timer = CUT_INTERVAL
                self.game.world.terrain_impact(hit.point, radius=2.2 + intensity, depth=.25,
                                               intensity=.5, surface="heat")

    def chill(self, source, target, amount: float, freeze_seconds: float, damage: float) -> None:
        """Cold builds up on a character: first it slows them, then it freezes them solid."""
        if not self.hostile(source, target) or target.is_evading or target.vitals.downed:
            return
        powers = target.powers
        powers.cold = min(1.0, powers.cold + amount)
        target.vitals.add_status("slowed", 1.0)
        self.hit_character(source, target, damage, COLD)
        if powers.cold >= 1.0 and not target.vitals.downed:
            powers.cold = 0.0
            target.vitals.add_status("frozen", freeze_seconds)

    # -- blasts ----------------------------------------------------------
    def burst(self, point, radius: float, intensity: float, tint=None) -> None:
        world = self.game.world
        world._acquire_explosion(point, radius, intensity)
        if tint is not None and world._active_explosions:
            world._active_explosions[-1].fire_rgb = tint

    def blast(self, source, origin: SimVec3, radius: float, damage: float, force: float, *,
              kind: str = EXPLOSION, crater=None, cracks: bool = False, burst_scale: float = 1.0,
              nullify=None, ignore=(), play_sound: bool = True, tint=None,
              even_damage: bool = False) -> None:
        """A radial hit on characters, objects and trees, with an optional crater and cracks."""
        world = self.game.world
        scaled = damage
        if source is not None and not source.controlled:
            scaled = damage * self.ai_damage_scale
        for target in tuple(self.in_world):
            if target in ignore or target is source:
                continue
            if source is not None and not self.hostile(source, target):
                continue
            offset = center_of(target) - origin
            distance = offset.length()
            if distance >= radius:
                continue
            falloff = 1.0 - distance / radius
            away = SimVec3(offset.x, max(.25, offset.y), offset.z).normalized()
            self.hit_character(source, target, damage if even_damage else damage * falloff, kind,
                               away, force if even_damage else force * falloff)
            if nullify is not None and distance < nullify["radius"]:
                self.nullify(target, nullify)
        self._own_blast = True
        try:
            world.damage_nearby(origin, scaled, radius=radius, impulse=force)
        finally:
            self._own_blast = False
        for obj in objects_in_radius(self.game, origin, radius):
            if not obj.anchored and getattr(obj, "liftable", False):
                offset = SimVec3(obj.x - origin.x, obj.y - origin.y, obj.z - origin.z)
                falloff = max(0.0, 1.0 - offset.length() / radius)
                obj.apply_impulse(SimVec3(offset.x, max(.3, offset.y), offset.z).normalized()
                                  * (force * falloff))
        self.elements.extinguish(origin, 0.0)
        self._start_blast_wave(origin, radius, force)
        self.burst(origin, radius, min(4.0, burst_scale * (.8 + damage / 500.0)),
                   tint or BLAST_TINTS.get(kind))
        if crater is not None:
            world.terrain_impact(origin, radius=crater[0], depth=crater[1],
                                 intensity=min(2.2, .6 + crater[1] * .4), surface=crater[2])
        if cracks:
            self.cracks.place(world, origin, radius * .6, self.game.elapsed)
        if play_sound:
            world.play_power_sound(min(1.0, .3 + damage / 900.0))
        self.game.camera_impulse = max(self.game.camera_impulse, min(3.0, .3 + radius * .04))

    def nullify(self, target, settings: dict) -> bool:
        """Only Compound V biology loses its powers; anyone else just takes the blast."""
        if target.kit.biology != "compound_v" or target.vitals.downed:
            return False
        target.vitals.add_status("nullified", settings["seconds"])
        target.powers.cancel_all()
        target.on_nullified()
        return True

    def on_area_damage(self, origin, amount: float, radius: float, impulse: float) -> None:
        """Chain explosions from things breaking. Blasts with an owner already did this."""
        if self._own_blast:
            return
        for target in tuple(self.in_world):
            offset = center_of(target) - origin
            distance = offset.length()
            if distance < radius:
                falloff = 1.0 - distance / radius
                # What a chest beam blows up must not throw the one firing it. It still hurts them.
                force = 0.0 if target.powers.braced else impulse * falloff * OUTSIDE_BLAST_SCALE
                self.hit_character(None, target, amount * falloff * OUTSIDE_BLAST_SCALE, EXPLOSION,
                                   SimVec3(offset.x, max(.25, offset.y), offset.z).normalized(), force)

    # -- projectiles and throws ------------------------------------------
    def fire_projectile(self, owner, origin, direction, *, speed, reach, damage, radius, tint,
                        size, force, kind=ENERGY, crater_depth=0.0, target=None, nullify=None) -> None:
        bolt = self._bolts.pop() if self._bolts else None
        self.projectiles.append(Projectile(owner, origin, direction * speed, reach, damage, radius,
                                           tint, size, force, kind, crater_depth, bolt, target, nullify))

    def _step_projectile(self, shot: Projectile, dt: float) -> bool:
        speed = shot.velocity.length()
        if shot.target is not None:  # it follows the enemy it was fired at
            if shot.target.vitals.downed or shot.target.parked:
                shot.target = None
            else:
                shot.velocity = (center_of(shot.target) - shot.position).normalized() * speed
        length = speed * dt
        direction = shot.velocity * (1.0 / max(speed, 1e-6))
        hit = trace(self.game, shot.position, direction, max(.1, length), ignore=(shot.owner,),
                    radius=shot.size * .5, characters=self.others_of(shot.owner))
        if hit.kind != "none":
            self._detonate(shot, hit, direction)
            return False
        shot.position = shot.position + shot.velocity * dt
        shot.travelled += length
        if shot.bolt is not None:
            shot.bolt.show(shot.position, shot.size, shot.tint)
        return shot.travelled < shot.reach

    def _detonate(self, shot, hit, direction) -> None:
        if hit.kind == "character":
            self.hit_character(shot.owner, hit.target, shot.damage, shot.kind, direction, shot.force)
            if shot.nullify is not None:
                self.nullify(hit.target, shot.nullify)
        elif hit.kind in ("object", "tree"):
            self.damage_hit(shot.owner, hit, shot.damage, direction, kind=shot.kind, force=shot.force)
        crater = None
        if shot.crater_depth > 0.0 and hit.kind == "terrain":
            crater = (shot.radius * .5, shot.crater_depth, "energy")
        self.blast(shot.owner, hit.point, shot.radius, shot.damage * .7, shot.force, kind=shot.kind,
                   crater=crater, nullify=shot.nullify,
                   ignore=(hit.target,) if hit.kind == "character" else ())

    def _end_projectile(self, shot) -> None:
        if shot.bolt is not None:
            shot.bolt.hide()
            self._bolts.append(shot.bolt)
        self.projectiles.remove(shot)

    def throw_character(self, source, target, direction: SimVec3, speed: float, damage: float) -> None:
        target.apply_knockback(direction * speed)
        self._thrown_characters.append([source, target, damage, 0.0])

    def track_thrown_object(self, source, obj, damage: float) -> None:
        self._thrown_objects.append([source, obj, damage, 0.0])

    def _step_thrown(self, dt: float) -> None:
        for entry in tuple(self._thrown_characters):
            source, target, damage, age = entry
            entry[3] = age + dt
            point = center_of(target)
            velocity = target.moving_velocity
            speed = velocity.length()
            hit = None
            if speed > 1.0:
                hit = trace(self.game, point, velocity * (1.0 / speed), max(1.0, speed * dt) + 1.0,
                            ignore=(target,), characters=[c for c in self.in_world if c is not source])
            if hit is not None and hit.kind != "none":
                self.hit_character(source, target, damage, PHYSICAL)
                self.damage_hit(source, hit, damage, velocity * (1.0 / speed), kind=PHYSICAL, force=speed * .4)
                self.burst(hit.point, 6.0, 1.0)
                if hit.kind == "terrain":
                    self.game.world.terrain_impact(hit.point, radius=3.0, depth=.5, intensity=.7,
                                                   surface="thrown")
                target.stop_knockback()
                self._thrown_characters.remove(entry)
            elif entry[3] > THROWN_MAX_SECONDS or speed < 4.0:
                self._thrown_characters.remove(entry)
        for entry in tuple(self._thrown_objects):
            source, obj, damage, age = entry
            entry[3] = age + dt
            if not obj.enabled or obj.health.broken or entry[3] > THROWN_MAX_SECONDS:
                self._thrown_objects.remove(entry)
                continue
            speed = obj.velocity.length()
            point = SimVec3(obj.x, obj.y, obj.z)
            struck = None
            for target in self.hostiles_of(source):
                if (center_of(target) - point).length() < 3.0 + abs(obj.scale_x) * .5:
                    struck = target
                    break
            ground = self.game.world.height_at(obj.x, obj.z) + abs(obj.scale_y) * .55
            if struck is not None or (obj.y <= ground and entry[3] > .08):
                self.blast(source, point, 6.0 + abs(obj.scale_x), damage, min(60.0, speed * .4),
                           kind=PHYSICAL, crater=(2.5, .4, "thrown"))
                obj.velocity = obj.velocity * .25
                self._thrown_objects.remove(entry)

    # -- markers ---------------------------------------------------------
    def mark(self, viewer, targets, reach: float, tint, extra=()) -> None:
        origin = center_of(viewer)
        points = []
        for target in targets:
            point = center_of(target)
            if (point - origin).length() <= reach:
                points.append(point + SimVec3(0.0, 2.8, 0.0))
        points.extend(extra)
        self.markers.show(points, tint, lambda p: max(.8, (p - origin).length() * .03))

    # -- per frame -------------------------------------------------------
    def apply_settings(self) -> None:
        tuning = self.game.teams.ai_view
        self.ai_damage_scale = tuning.fraction("ai_damage_pct", .35)
        self.ai_powers_enabled = tuning.flag("ai_uses_powers", True)
        for character in self.game.teams.characters.values():
            character.powers.apply_passives()
            character.apply_sentry_config()
        self.game.teams.refresh_tags()

    def refresh_target_indicator(self) -> None:
        """Keep the player's target, its more prominent health bar and the lock reticle up to date."""
        player = self.game.sentry
        manual = self.targets.manual
        if manual is None:
            self.lock_reticle.hide()
        else:
            point = self.targets.point_of(manual)
            self.lock_reticle.show(point, (point - center_of(player)).length())
        if manual is not None and not is_civilian(manual):
            target = manual
        else:
            target = self.targets.lock_of(player) if self.targets.enabled else None
        if target is self.shown_target:
            return
        teams = self.game.teams
        if self.shown_target is not None:
            teams.tag_of(self.shown_target).set_targeted(False)
        if target is not None:
            teams.tag_of(target).set_targeted(True)
        self.shown_target = target

    def _ram_and_crash(self, character, now: float) -> None:
        """Flying into someone at speed hurts them; hitting the ground at speed hurts you."""
        velocity = character.moving_velocity
        speed = velocity.length()
        if speed < RAM_MIN_SPEED or character.motion is not None:
            return
        if character.flight.is_flying and self._ram_ready.get(character, 0.0) <= now:
            damage = character.powers.collision_damage * speed * .01
            if damage > 0.0:
                for target in self.hostiles_of(character):
                    if (center_of(target) - center_of(character)).length() < 3.0:
                        self._ram_ready[character] = now + RAM_COOLDOWN
                        self.hit_character(character, target, damage, PHYSICAL,
                                           velocity * (1.0 / speed), speed * .3)
                        self.burst(center_of(target), 4.0, .7)
                        break
        floor = self.game.world.height_at(character.x, character.z) + .3
        if (character.flight.phase is FlightPhase.CRUISE and character.y <= floor
                and speed >= CRASH_MIN_SPEED and self._ram_ready.get(character, 0.0) <= now):
            self._ram_ready[character] = now + RAM_COOLDOWN
            character.vitals.take((speed - CRASH_MIN_SPEED) * .4, IMPACT)
            if character.vitals.downed:
                character.on_downed()

    def update(self, dt: float) -> None:
        self._advance_blast_wave(dt)
        self._advance_world_stop()
        if self.time_stopped:
            self._frozen_for += dt
            if self.sequence_running:
                self._update_time_stopped(dt)
            else:
                self._update_world_stopped(dt)
            return
        if self._frozen_for > 0.0:  # AI wakes with the same wait left that it had when time stopped
            self.game.teams.shift_ai_clocks(self._frozen_for)
            self._frozen_for = 0.0
        self._scorch_timer = max(0.0, self._scorch_timer - dt)
        self._cut_timer = max(0.0, self._cut_timer - dt)
        now = self.game.elapsed
        for character in self.in_world:
            self._advance_character(character, dt, now)
        for shot in tuple(self.projectiles):
            if not self._step_projectile(shot, dt):
                self._end_projectile(shot)
        self._step_thrown(dt)
        self.refresh_target_indicator()
        self.puffs.step(dt)
        self.elements.step(dt)

    def nearest_threat(self, character) -> tuple | None:
        """The closest enemy within hearing range, as (name, metres)."""
        radius = character.powers.hearing_radius
        if radius <= 0.0:
            return None
        best = None
        origin = center_of(character)
        for target in self.hostiles_of(character):
            distance = (center_of(target) - origin).length()
            if distance <= radius and (best is None or distance < best[1]):
                best = (target.display_name, distance)
        return best

    def reset_world_state(self) -> None:
        """Clear live projectiles, throws, fires and marks without touching the save."""
        for shot in tuple(self.projectiles):
            self._end_projectile(shot)
        self._thrown_characters.clear()
        self._thrown_objects.clear()
        self._ai_spent.clear()
        self.targets.clear()
        self.targets.manual = None
        self.lock_reticle.hide()
        self.world_stop_left = 0.0
        self._frozen_for = 0.0
        self.end_time_stop()
        self.elements.clear()
        self.markers.hide()
        self.cracks.hide_all()


__all__ = ["COLD", "CombatSystem", "DestructibleEntity", "HEAT", "color", "sqrt"]
