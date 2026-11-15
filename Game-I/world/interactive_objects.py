"""Ursina scene objects backed by the testable damage and debris models."""

from __future__ import annotations

from math import atan2, cos, degrees, sin
from random import Random

from ursina import Entity, Mesh, Vec3, color
from ursina.shaders import lit_with_shadows_shader

from ai.civilian_ai import CivilianState
from combat.damage_system import Damageable
from movement.flight_physics import Vec3 as SimVec3
from world.destructible_props import DebrisBudget


class DebrisPiece(Entity):
    def __init__(self, game, position, velocity: SimVec3, tint, size: float, lifetime: float):
        position_value = ((float(position.x), float(position.y), float(position.z))
                          if hasattr(position, "x") else position)
        super().__init__(model="cube", collider="box", position=position_value, scale=size,
                         color=tint, shader=lit_with_shadows_shader)
        self.reset(game, position_value, velocity, tint, size, lifetime)

    def reset(self, game, position, velocity: SimVec3, tint, size: float,
              lifetime: float) -> None:
        self.enable()
        self.visible = True
        self.collider = "box"
        self.model = "cube"
        self.position = ((float(position.x), float(position.y), float(position.z))
                         if hasattr(position, "x") else position)
        self.scale = size
        self.color = tint
        self.game = game
        self.velocity = velocity
        self.age = 0.0
        self.lifetime = max(.1, float(lifetime))
        self._simulation_timer = 0.0
        self._collision_timer = 0.0
        self._impact_done = False

    def step(self, dt: float) -> None:
        self.age += dt
        planet = self.game.planet
        position = SimVec3(self.x, self.y, self.z)
        gravity = planet.gravity(position)
        self.velocity = self.velocity + gravity * dt
        self.position += Vec3(self.velocity.x * dt, self.velocity.y * dt, self.velocity.z * dt)
        position = SimVec3(self.x, self.y, self.z)
        altitude = planet.altitude(position)
        floor = self.scale_y * .5
        if planet.is_ocean(position) and altitude < floor:
            position = planet.project(position, floor)
            self.position = Vec3(position.x, position.y, position.z)
            up = planet.normal(position)
            radial = self.velocity.x * up.x + self.velocity.y * up.y + self.velocity.z * up.z
            tangent = self.velocity - up * radial
            self.velocity = tangent * max(0.0, 1.0 - 2.0 * dt) + up * max(0.0, radial * .25)
        elif altitude < floor:
            position = planet.project(position, floor)
            self.position = Vec3(position.x, position.y, position.z)
            up = planet.normal(position)
            radial = self.velocity.x * up.x + self.velocity.y * up.y + self.velocity.z * up.z
            tangent = self.velocity - up * radial
            if radial < -1.0:
                radial = -radial * .25
                tangent = tangent * .65
            if abs(radial) < 1.0:
                radial = 0.0
            self.velocity = tangent + up * radial
        spin = min(1.0, self.velocity.length() / 6.0)
        self.rotation += Vec3(75.0 * spin * dt, 105.0 * spin * dt, 55.0 * spin * dt)
        self._collision_timer -= dt
        if (not self._impact_done and self._collision_timer <= 0.0
                and self.velocity.length() > 14.0):
            self._collision_timer = .12
            self._impact_done = bool(self.game.world.damage_debris_impact(self))
        if self.age >= self.lifetime:
            self.game.world.recycle_debris(self)


class DestructibleEntity(Entity):
    def __init__(self, game, position, scale, tint, health: float, name="prop", *, dynamic=False):
        position = (position.x, position.y, position.z) if hasattr(position, "x") else position
        super().__init__(model="cube", collider="box", position=position, scale=scale,
                         color=tint, name=name, shader=lit_with_shadows_shader)
        self.game = game
        self.health = Damageable(health)
        self.velocity = SimVec3()
        self.dynamic = dynamic
        self.held = False
        self.anchored = False
        self.frozen_until = 0.0
        self.heat_until = 0.0
        self.original_tint = tint
        self._random = Random(game.random.randrange(1, 2**31))
        self.persistent_id = None
        self.chunk_key = None
        self.display_name = name.replace("-", " ").title()
        self.damage_stage = 0
        self._partial_collapse_started = False
        self._destruction_handled = False
        self._last_impact_position = None
        self._last_impact_speed = 0.0
        self._last_damage_power = 0.0
        self.crack_overlay = None
        self.rubble_remains = None
        self._base_scale = Vec3(float(self.scale_x), float(self.scale_y), float(self.scale_z))
        game.world.register_object(self)

    def take_damage(self, amount: float, impulse: SimVec3 | None = None, *,
                    impact_position=None, impact_speed: float = 0.0) -> bool:
        if self.health.broken:
            return False
        self._last_damage_power = max(self._last_damage_power, float(amount))
        if impact_position is not None:
            if hasattr(impact_position, "x"):
                self._last_impact_position = SimVec3(impact_position.x,
                    impact_position.y, impact_position.z)
            else:
                self._last_impact_position = SimVec3(*impact_position)
        self._last_impact_speed = max(self._last_impact_speed, float(impact_speed))
        if impulse is not None:
            self.velocity = self.velocity + impulse
        self.health.apply(amount)
        broken_now = self.health.broken
        self._update_damage_appearance()
        self.game.world.record_damage(self, destroyed=broken_now)
        if broken_now:
            self.break_apart()
        return broken_now

    def _ensure_crack_overlay(self) -> None:
        if self.crack_overlay is not None:
            return
        # Thin branching fissures on the forward face create a visible damage
        # state without replacing or rebuilding the object's main mesh.
        paths = (
            ((-.34, .34), (-.11, .08), (-.20, -.08), (.04, -.28)),
            ((-.11, .08), (.18, .24), (.29, .12)),
            ((-.20, -.08), (-.32, -.28)),
            ((.04, -.28), (.24, -.39)),
            ((-.11, .08), (.03, .42)),
        )
        vertices, triangles = [], []
        half_width = .009
        for path in paths:
            for first, second in zip(path, path[1:]):
                dx, dy = second[0] - first[0], second[1] - first[1]
                length = max(1e-6, (dx * dx + dy * dy) ** .5)
                ox, oy = -dy / length * half_width, dx / length * half_width
                base = len(vertices)
                vertices.extend(((first[0] - ox, first[1] - oy, .515),
                                 (first[0] + ox, first[1] + oy, .515),
                                 (second[0] + ox, second[1] + oy, .515),
                                 (second[0] - ox, second[1] - oy, .515)))
                triangles.extend((base, base + 1, base + 2,
                                  base, base + 2, base + 3))
        self.crack_overlay = Entity(parent=self, name="structural-cracks",
            model=Mesh(vertices=vertices, triangles=triangles, static=True),
            color=color.rgb32(48, 39, 34), double_sided=True, collider=None,
            visible=False)

    def _update_damage_appearance(self) -> None:
        fraction = self.health.health_fraction
        stage = (0 if fraction > .75 else 1 if fraction > .5
                 else 2 if fraction > .25 else 3)
        if stage == self.damage_stage and not self.health.broken:
            return
        self.damage_stage = stage
        shade = .55 + .45 * fraction
        base_tint = getattr(self, "debris_tint", self.original_tint)
        damaged_tint = color.rgb32(
            int(max(20, min(255, base_tint.r * 255 * shade))),
            int(max(20, min(255, base_tint.g * 255 * shade))),
            int(max(20, min(255, base_tint.b * 255 * shade))),
        )
        self.color = damaged_tint
        facade = getattr(self, "facade_detail", None)
        if facade is not None:
            facade.color = color.rgb32(round(255 * shade), round(255 * shade),
                                       round(255 * shade))
        if stage >= 2:
            self._ensure_crack_overlay()
            self.crack_overlay.visible = True
        if stage >= 3 and not self._partial_collapse_started:
            self._partial_collapse_started = True
            count = self.game.world.debris_budget.reserve(3)
            for _ in range(count):
                velocity = SimVec3(self._random.uniform(-8, 8),
                                   self._random.uniform(3, 10),
                                   self._random.uniform(-8, 8))
                piece = self.game.world.spawn_debris(
                    Vec3(self.x + self._random.uniform(-.5, .5),
                         self.y + self.scale_y * .35,
                         self.z + self._random.uniform(-.5, .5)),
                    velocity, getattr(self, "debris_tint", self.original_tint),
                    max(.2, min(2.0, min(self.scale_x, self.scale_y, self.scale_z) * .12)),
                    self.game.settings.debris_lifetime)

    def apply_heat(self, amount: float, impulse: SimVec3 | None = None) -> bool:
        self.heat_until = max(self.heat_until, self.game.elapsed + .3)
        return self.take_damage(amount, impulse)

    def apply_impulse(self, impulse: SimVec3) -> None:
        self.dynamic = True
        self.velocity = self.velocity + impulse

    def begin_hold(self) -> bool:
        if self.anchored or not self.enabled:
            return False
        self.held = True
        self.dynamic = True
        self.velocity = SimVec3()
        return True

    def freeze(self, seconds: float) -> None:
        self.frozen_until = max(self.frozen_until, self.game.elapsed + seconds)
        self.color = color.rgb32(130, 210, 235)

    def release(self, impulse: SimVec3 | None = None) -> None:
        self.held = False
        if impulse is not None:
            self.velocity = self.velocity + impulse

    def break_apart(self) -> None:
        if not self.enabled:
            return
        self.game.world.record_damage(self, destroyed=True)
        self.game.world.remove_object(self)
        count = self.game.world.debris_budget.reserve(14)
        origin = Vec3(self.x, self.y, self.z)
        up = self.game.planet.normal(SimVec3(self.x, self.y, self.z))
        east, _, north = self.game.planet.tangent_frame(SimVec3(self.x, self.y, self.z))
        for _ in range(count):
            point = SimVec3(self.x, self.y, self.z)
            impact_point = self._last_impact_position or point
            away = (point - impact_point).normalized()
            if away.length() < 1e-5:
                away = self._random.choice((east, north, east * -1, north * -1))
            velocity = (east * self._random.uniform(-9, 9)
                        + up * self._random.uniform(4, 16)
                        + north * self._random.uniform(-9, 9) + self.velocity * .35
                        + away * min(120.0, max(12.0, self._last_impact_speed * .7)))
            piece = self.game.world.spawn_debris(origin, velocity,
                                getattr(self, "debris_tint", self.color),
                                max(.18, min(3.0, min(self.scale_x, self.scale_y, self.scale_z) * .22)),
                                self.game.settings.debris_lifetime)
        self.game.world.notify_danger(SimVec3(self.x, self.y, self.z))
        terrain = getattr(self.game.world, "height_at", lambda _x, _z: 0.0)(self.x, self.z)
        base_x, base_z = max(1.2, abs(self._base_scale.x) * .42), max(1.2, abs(self._base_scale.z) * .42)
        for child in tuple(self.children):
            child.disable()
        self.model = None
        self.collider = None
        self.scale = (1.0, 1.0, 1.0)
        self.rotation = (0.0, 0.0, 0.0)
        self.position = (self.x, terrain + .14, self.z)
        self.color = color.rgb32(104, 101, 94)
        self.rubble_remains = Entity(parent=self, name="collapsed-rubble-remains",
            model="cube", position=(0, 0, 0), scale=(base_x, .28, base_z),
            color=self.color, collider=None)
        self.anchored = True
        if not self._destruction_handled:
            self._destruction_handled = True
            self.game.world.on_object_destroyed(
                self, impact_position=self._last_impact_position,
                impact_speed=self._last_impact_speed,
                damage_power=self._last_damage_power)

    def step(self, dt: float, held_target: Vec3 | None = None) -> None:
        if not self.enabled:
            return
        if self.frozen_until > self.game.elapsed:
            self.velocity = SimVec3()
            self.color = color.rgb32(130, 210, 235)
            return
        if self.heat_until > self.game.elapsed:
            self.color = color.rgb32(255, 122, 58)
        elif self.damage_stage == 0 and self.color != self.original_tint:
            self.color = self.original_tint
        if not self.dynamic:
            return
        if self.held and held_target is not None:
            delta = SimVec3(held_target.x - self.x, held_target.y - self.y, held_target.z - self.z)
            desired = delta * 14.0
            response = min(1.0, 14.0 * dt)
            self.velocity = self.velocity + (desired - self.velocity) * response
            self.velocity = self.velocity.clamped(38.0)
        else:
            self.velocity.y -= 27.0 * dt
        old_position = SimVec3(self.x, self.y, self.z)
        self.velocity = self.velocity + self.game.planet.gravity(old_position) * dt
        self.position += Vec3(self.velocity.x * dt, self.velocity.y * dt, self.velocity.z * dt)
        floor = self.scale_y * .5
        position = SimVec3(self.x, self.y, self.z)
        altitude = self.game.planet.altitude(position)
        ocean = self.game.planet.is_ocean(position)
        if ocean and altitude < floor:
            position = self.game.planet.project(position, floor)
            self.position = Vec3(position.x, position.y, position.z)
            up = self.game.planet.normal(position)
            radial = self.velocity.x * up.x + self.velocity.y * up.y + self.velocity.z * up.z
            tangent = self.velocity - up * radial
            self.velocity = tangent * max(0.0, 1.0 - 2.2 * dt) + up * max(0.0, radial * .28)
        elif altitude < floor:
            position = self.game.planet.project(position, floor)
            self.position = Vec3(position.x, position.y, position.z)
            up = self.game.planet.normal(position)
            radial = self.velocity.x * up.x + self.velocity.y * up.y + self.velocity.z * up.z
            tangent = self.velocity - up * radial
            if radial < -1.2:
                impact = -radial
                radial = impact * .22
                tangent = tangent * .72
                if impact > 18.0:
                    self.game.world.damage_nearby(SimVec3(self.x, self.y, self.z), impact * .7, ignore=self)
            else:
                radial = 0.0
                tangent = tangent * max(0.0, 1.0 - 3.5 * dt)
            self.velocity = tangent + up * radial
        self.game.world.resolve_object_collision(self, old_position=old_position,
                                                 impact_speed=self.velocity.length())
        if not self.enabled:
            return
        if not self.held:
            up = self.game.planet.normal(SimVec3(self.x, self.y, self.z))
            radial = self.velocity.x * up.x + self.velocity.y * up.y + self.velocity.z * up.z
            speed = (self.velocity - up * radial).length()
            if speed > 1.0:
                east, _, north = self.game.planet.tangent_frame(SimVec3(self.x, self.y, self.z))
                self.game.planet.orient_entity(self, SimVec3(self.x, self.y, self.z),
                    degrees(atan2(self.velocity.x * east.x + self.velocity.y * east.y + self.velocity.z * east.z,
                                  self.velocity.x * north.x + self.velocity.y * north.y + self.velocity.z * north.z)))


class _VehicleMesh:
    """Merge simple vehicle details into one low draw-call mesh."""

    def __init__(self):
        self.vertices=[]; self.triangles=[]; self.colors=[]

    def box(self, center, size, tint):
        x,y,z=center; sx,sy,sz=(value*.5 for value in size)
        base=len(self.vertices)
        self.vertices.extend(((x-sx,y-sy,z-sz),(x+sx,y-sy,z-sz),
            (x+sx,y+sy,z-sz),(x-sx,y+sy,z-sz),(x-sx,y-sy,z+sz),
            (x+sx,y-sy,z+sz),(x+sx,y+sy,z+sz),(x-sx,y+sy,z+sz)))
        self.colors.extend((tint,)*8)
        for face in ((0,1,2,0,2,3),(5,4,7,5,7,6),(1,5,6,1,6,2),
                     (4,0,3,4,3,7),(3,2,6,3,6,7),(4,5,1,4,1,0)):
            self.triangles.extend(base+index for index in face)

    def wheel(self, center, radius, width, tint, segments=10):
        x,y,z=center; base=len(self.vertices)
        for side in (-1,1):
            for segment in range(segments):
                angle=6.28318530718*segment/segments
                self.vertices.append((x+side*width*.5,
                    y+radius*cos(angle),z+radius*sin(angle)))
                self.colors.append(tint)
        self.triangles.extend(index for segment in range(1,segments-1)
            for index in (base,base+segment+1,base+segment))
        right=base+segments
        self.triangles.extend(index for segment in range(1,segments-1)
            for index in (right,right+segment,right+segment+1))
        for segment in range(segments):
            following=(segment+1)%segments
            a,b=base+segment,base+following
            c,d=right+following,right+segment
            self.triangles.extend((a,b,c,a,c,d))

    def mesh(self):
        return Mesh(vertices=self.vertices,triangles=self.triangles,
                    colors=self.colors,static=True)


class TrafficVehicle(DestructibleEntity):
    _BODY_COLOURS=((190,190,190),(30,30,30),(210,210,210),(150,25,25),
        (25,55,120),(35,75,45),(200,145,30),(90,90,90),(55,90,150),(160,40,40))
    _PROFILES={
        "sedan":(4.7,1.28,1.85), "suv":(4.9,1.63,2.02),
        "hatchback":(3.9,1.26,1.78), "sports_car":(4.45,1.06,1.92),
        "delivery_van":(5.25,1.95,2.05), "motorcycle":(2.15,.95,.84),
    }

    def __init__(self, game, position, lane_direction: float, *,
                 route_center=(0.0,0.0), persistent_id: str | None=None,
                 style_seed: int | None=None):
        rng=Random(style_seed if style_seed is not None else game.random.randrange(1,2**31))
        self.vehicle_type=rng.choice(tuple(self._PROFILES))
        body_colour=color.rgb32(*rng.choice(self._BODY_COLOURS))
        glass=color.rgba32(105,155,190,205)
        super().__init__(game,position,self._PROFILES[self.vehicle_type],body_colour,
                         210.0,"traffic-vehicle")
        self.persistent_id=persistent_id
        self.is_traffic=True
        self.anchored=True
        self.lane_direction=1.0 if lane_direction>=0 else -1.0
        self.traffic_speed=0.0
        self.base_traffic_speed=rng.uniform(8.0,12.0)
        self._simulation_timer=0.0
        self._route_center=tuple(route_center)
        self._route_index=0 if self.lane_direction>0 else 2
        self._route_points=self._make_route(self._route_center)
        self._vehicle_detail_quality=getattr(game.settings,"vehicle_detail_quality","medium")
        self._vehicle_visuals=Entity(parent=self,model=None,name="vehicle-detail",
            color=color.white,shader=lit_with_shadows_shader,collider=None,double_sided=True)
        self._wheel_offsets=[]
        self._build_vehicle_visuals(body_colour,glass,rng)
        self._vehicle_tint=body_colour
        self._death_visual_started=False
        if persistent_id:
            state=game.world.object_states.get(persistent_id)
            if state and not state.get("destroyed",False):
                self.health.health=min(self.health.maximum_health,float(state.get("health",self.health.maximum_health)))
                self._update_damage_appearance()

    @staticmethod
    def _make_route(center):
        x,z=center
        return ((x-237.0,z-237.0),(x+237.0,z-237.0),
                (x+237.0,z+237.0),(x-237.0,z+237.0))

    def _build_vehicle_visuals(self,body_colour,glass,rng):
        trim=color.rgb32(55,58,63)
        wheel_dark=color.rgb32(20,21,23)
        rim=color.rgb32(165,169,176)
        mesh=_VehicleMesh()
        if self.vehicle_type=="motorcycle":
            for x in (-.37,.37):
                mesh.wheel((x,-.22,0),.19,.12,wheel_dark)
                self._wheel_offsets.append((x,-.22,0))
            mesh.box((0,.08,0),(.36,.24,.35),body_colour)
            mesh.box((-.02,.22,0),(.30,.12,.34),trim)
            mesh.box((.39,.27,0),(.05,.24,.52),trim)
            mesh.box((.43,.17,0),(.12,.12,.18),color.rgb32(255,242,190))
            self._vehicle_visuals.model=mesh.mesh()
            return
        # Low center of mass chassis with a distinct cabin profile per vehicle type.
        cabin=(.70,.40,.78)
        if self.vehicle_type=="suv": cabin=(.68,.54,.82)
        elif self.vehicle_type=="hatchback": cabin=(.72,.46,.80)
        elif self.vehicle_type=="sports_car": cabin=(.67,.30,.72)
        elif self.vehicle_type=="delivery_van": cabin=(.70,.70,.82)
        mesh.box((0,.18,-.03),cabin,body_colour)
        for wx in (-.35,.35):
            for wz in (-.40,.40):
                mesh.wheel((wx,-.25,wz),.21,.105,wheel_dark)
                mesh.wheel((wx*1.01,-.25,wz*1.02),.12,.11,rim,8)
                self._wheel_offsets.append((wx,-.25,wz))
        for x in (-.34,.34):
            mesh.box((x,.31,-.03),(.035,.28,.54),glass)
        for z in (-.31,.31):
            mesh.box((.02,.32,z),(.45,.24,.025),glass)
            mesh.box((.04,.02,z*1.38),(.16,.045,.055),trim)
        for z in (-.36,.36):
            mesh.box((.51,.02,z),(.055,.09,.13),color.rgb32(255,248,205))
            mesh.box((-.51,.02,z),(.04,.09,.13),color.rgb32(194,32,30))
        for x in (-.52,.52):
            mesh.box((x,-.20,0),(.06,.13,.9),trim)
        self._vehicle_visuals.model=mesh.mesh()

    def reset(self,game,position,lane_direction,route_center,persistent_id):
        """Reactivate an intact, pooled traffic vehicle."""
        self.game=game; self.persistent_id=persistent_id
        self.health=Damageable(210.0)
        self.velocity=SimVec3(); self.dynamic=False; self.held=False; self.anchored=True
        self.frozen_until=0.0; self.heat_until=0.0
        self.damage_stage=0; self._partial_collapse_started=False
        self._destruction_handled=False; self._last_impact_position=None
        self._last_impact_speed=0.0; self._last_damage_power=0.0
        self.crack_overlay=None; self.rubble_remains=None
        self._base_scale=Vec3(*self._PROFILES[self.vehicle_type])
        self.scale=self._base_scale; self.model="cube"; self.color=self._vehicle_tint
        self._vehicle_visuals.enable()
        self.position=(position.x,position.y,position.z)
        self._route_center=tuple(route_center); self._route_points=self._make_route(route_center)
        self._route_index=0 if lane_direction>=0 else 2
        self.lane_direction=1.0 if lane_direction>=0 else -1.0
        self.chart_x=float(position.x); self.chart_z=float(position.z)
        self.traffic_speed=0.0; self._simulation_timer=0.0
        self._death_visual_started=False
        self.enable()
        state=game.world.object_states.get(persistent_id)
        if state and not state.get("destroyed",False):
            self.health.health=min(self.health.maximum_health,float(state.get("health",self.health.maximum_health)))

    def set_visual_lod(self,detailed: bool):
        self._vehicle_visuals.enabled=bool(detailed)

    def break_apart(self):
        if self.health.broken and not self._death_visual_started:
            self._death_visual_started=True
            if self.vehicle_type!="motorcycle":
                for wx,wy,wz in self._wheel_offsets:
                    point=SimVec3(self.x+wx*self.scale_x,self.y+wy*self.scale_y,
                                  self.z+wz*self.scale_z)
                    velocity=self.velocity+SimVec3(self._random.uniform(-9,9),self._random.uniform(5,14),
                                                   self._random.uniform(-9,9))
                    self.game.world.spawn_debris(point,velocity,color.rgb32(25,25,27),.42,
                                                 self.game.settings.debris_lifetime)
        super().break_apart()

    def step(self,dt:float,held_target:Vec3|None=None)->None:
        if self.frozen_until>self.game.elapsed:
            self.velocity=SimVec3(); return
        if self.dynamic:
            super().step(dt,held_target); return
        dt=max(0.0,min(float(dt),.1))
        old_position=Vec3(self.x,self.y,self.z)
        target_speed=self.base_traffic_speed
        route=self._route_points
        target=route[(self._route_index+1)%4]
        dx,dz=target[0]-self.chart_x,target[1]-self.chart_z
        length=max(1e-4,(dx*dx+dz*dz)**.5)
        direction=SimVec3(dx/length,0,dz/length)
        for other in self.game.world.nearby_traffic(self.chart_x,self.chart_z,18.0):
            if other is self or other._route_center!=self._route_center: continue
            ox,oz=other.chart_x-self.chart_x,other.chart_z-self.chart_z
            ahead=ox*direction.x+oz*direction.z
            lateral=abs(-ox*direction.z+oz*direction.x)
            if .1<ahead<14.0 and lateral<3.0:
                target_speed=min(target_speed,max(0.0,(ahead-5.0)*.8))
        for civilian in self.game.world.nearby_civilians(self.chart_x,self.chart_z,1):
            dxp,dzp=civilian.chart_x-self.chart_x,civilian.chart_z-self.chart_z
            ahead=dxp*direction.x+dzp*direction.z
            lateral=abs(-dxp*direction.z+dzp*direction.x)
            if -.5<ahead<8.0 and lateral<2.6:
                target_speed=min(target_speed,max(0.0,(ahead-2.0)*1.2))
                if ahead<3.0: civilian.brain.state=CivilianState.IDLE
        response=min(1.0,dt*1.4)
        self.traffic_speed+=(target_speed-self.traffic_speed)*response
        distance=self.traffic_speed*dt
        if distance>=length:
            self._route_index=(self._route_index+1)%4
            next_point=route[(self._route_index+1)%4]
            direction=SimVec3(next_point[0]-target[0],0,next_point[1]-target[1]).normalized()
            self.chart_x,self.chart_z=target
        else:
            self.chart_x+=direction.x*distance
            self.chart_z+=direction.z*distance
        point=self.game.planet.point_from_local(self.chart_x,self.chart_z,
            self.game.world.height_at(self.chart_x,self.chart_z)+.66)
        self.position=Vec3(point.x,point.y,point.z)
        heading=degrees(atan2(direction.x,direction.z))
        self.game.planet.orient_entity(self,SimVec3(point.x,point.y,point.z),heading)
        self.game.world.resolve_object_collision(self,old_position=old_position,
                                                 impact_speed=self.traffic_speed)
        self._vehicle_detail_quality=getattr(self.game.settings,"vehicle_detail_quality","medium")
        player=getattr(self.game,"sentry",None)
        if player is not None:
            distance_sq=(self.x-player.x)**2+(self.z-player.z)**2
            detail_range={"low":75.0,"medium":120.0,"high":190.0}.get(self._vehicle_detail_quality,120.0)
            self.set_visual_lod(distance_sq<detail_range**2)
