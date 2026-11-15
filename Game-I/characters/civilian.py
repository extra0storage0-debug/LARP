"""Varied, pooled pedestrian visuals and a lightweight combat-capable actor."""

from __future__ import annotations

from math import atan2, cos, degrees, sin
from random import Random

from ursina import Entity, Mesh, Vec3, color
from ursina.shaders import lit_with_shadows_shader

from ai.civilian_ai import CivilianBrain, CivilianState
from movement.flight_physics import Vec3 as SimVec3


class _HumanMesh:
    """Small colored low-poly mesh builder for batching a person's body parts."""

    def __init__(self):
        self.vertices=[]; self.triangles=[]; self.colors=[]

    def ellipsoid(self, center, scale, tint, rings=7, segments=10):
        base=len(self.vertices)
        for ring in range(rings+1):
            latitude=-1.57079632679+3.14159265359*ring/rings
            y=sin(latitude)
            radius=cos(latitude)
            for segment in range(segments):
                angle=6.28318530718*segment/segments
                self.vertices.append((center[0]+scale[0]*radius*cos(angle),
                                      center[1]+scale[1]*y,
                                      center[2]+scale[2]*radius*sin(angle)))
                self.colors.append(tint)
        for ring in range(rings):
            for segment in range(segments):
                a=base+ring*segments+segment
                b=base+ring*segments+(segment+1)%segments
                c=b+segments; d=a+segments
                self.triangles.extend((a,b,c,a,c,d))

    def box(self, center, scale, tint):
        x,y,z=center; sx,sy,sz=(v*.5 for v in scale)
        base=len(self.vertices)
        self.vertices.extend(((x-sx,y-sy,z-sz),(x+sx,y-sy,z-sz),
            (x+sx,y+sy,z-sz),(x-sx,y+sy,z-sz),(x-sx,y-sy,z+sz),
            (x+sx,y-sy,z+sz),(x+sx,y+sy,z+sz),(x-sx,y+sy,z+sz)))
        self.colors.extend((tint,)*8)
        for face in ((0,1,2,0,2,3),(5,4,7,5,7,6),(1,5,6,1,6,2),
                     (4,0,3,4,3,7),(3,2,6,3,6,7),(4,5,1,4,1,0)):
            self.triangles.extend(base+i for i in face)

    def mesh(self):
        if not self.vertices:
            return None
        return Mesh(vertices=self.vertices,triangles=self.triangles,
                    colors=self.colors,static=True)

    def entity(self, parent):
        return Entity(parent=parent,model=self.mesh(),
            color=color.white,shader=lit_with_shadows_shader,double_sided=True,collider=None)


class Civilian:
    CLEANUP_AFTER = 20.0

    def __init__(self, game, position, seed: int, persistent_id: str | None = None):
        self.game = game
        self.seed = int(seed)
        self.random = Random(self.seed)
        self.persistent_id = persistent_id or f"civilian:{self.seed}"
        self.chart_x = float(position[0])
        self.chart_z = float(position[2] if len(position) > 2 else position[1])
        mapped = game.planet.point_from_local(self.chart_x, self.chart_z)
        self.entity = Entity(position=(mapped.x, mapped.y, mapped.z), model=None,
                             collider="box", scale=(.58, 1.85, .58),
                             shader=lit_with_shadows_shader, name="civilian")
        self.detail_root = Entity(parent=self.entity, model=None)
        self.left_arm = self.right_arm = self.left_leg = self.right_leg = None
        self._build_appearance()
        game.planet.orient_entity(self.entity, SimVec3(mapped.x, mapped.y, mapped.z))
        self.entity.civilian_owner = self
        self.entity.take_damage = self.take_damage
        self.entity.apply_heat = self.apply_heat
        self.entity.freeze = self.freeze
        self.entity.display_name = self.display_name
        self.brain = CivilianBrain(SimVec3(self.chart_x, 0.0, self.chart_z))
        self._walk_time = 0.0
        self._wander_time = 0.0
        self._animation_timer = 0.0
        self._simulation_timer = 0.0
        self._detailed_visual = True
        self.knockback = SimVec3()
        self.freeze_until = 0.0
        self.death_age = 0.0
        self._death_recorded = False
        self._corpse_damping = 4.5
        self._spatial_chunk = None

    def _build_appearance(self) -> None:
        rng = self.random
        self.gender = rng.choice(("woman", "man"))
        self.age_group = rng.choices(("young_adult", "adult", "older_adult"),
                                     weights=(3, 5, 2), k=1)[0]
        self.build = rng.choice(("slim", "average", "broad"))
        width = {"slim": .87, "average": 1.0, "broad": 1.14}[self.build]
        if self.gender == "woman":
            width *= .91
        self.height = rng.uniform(.84, .94) if self.age_group == "older_adult" else rng.uniform(.93, 1.10)
        self.detail_root.scale = (width, self.height, rng.uniform(.9, 1.08))
        shirt = rng.choice((color.rgb32(113,124,143), color.rgb32(158,105,75),
            color.rgb32(74,122,96), color.rgb32(135,126,97), color.rgb32(182,60,60),
            color.rgb32(55,88,140), color.rgb32(200,200,200), color.rgb32(40,40,40)))
        trousers = rng.choice((color.rgb32(35,40,55), color.rgb32(51,57,68),
            color.rgb32(80,60,45), color.rgb32(25,25,25), color.rgb32(70,80,70)))
        skin = rng.choice((color.rgb32(255,219,185), color.rgb32(241,194,125),
            color.rgb32(198,148,97), color.rgb32(141,85,36), color.rgb32(80,48,22)))
        hair = (color.rgb32(170,168,162) if self.age_group == "older_adult" and rng.random() < .65
                else rng.choice((color.rgb32(25,17,10), color.rgb32(76,47,25),
                    color.rgb32(155,100,50), color.rgb32(215,170,80),
                    color.rgb32(200,200,200), color.rgb32(245,235,220))))
        self._proxy_tint = shirt
        outfit = rng.choice(("casual", "office", "coat", "sport", "dress"))
        body = _HumanMesh()
        arm = _HumanMesh()
        leg = _HumanMesh()
        body.ellipsoid((0,1.27,0),(.44*width,.72,.32),shirt)
        if outfit == "coat":
            body.ellipsoid((0,1.28,.015),(.45*width,.66,.34),trousers)
        elif outfit == "office":
            body.box((0,1.25,.174),(.055,.38,.035),color.rgb32(165,38,42))
        elif outfit == "sport":
            for side in (-1,1):
                body.box((side*.19,1.27,.164),(.055,.56,.025),trousers)
        elif outfit == "dress":
            body.ellipsoid((0,.85,0),(.34,.43,.28),shirt)
        body.ellipsoid((0,1.71,.01),(.09,.12,.09),skin,6,8)
        head_size = rng.uniform(.92,1.08)
        body.ellipsoid((0,1.90,.02),(.30*head_size,.36*head_size,.28*head_size),skin,9,12)
        style = rng.choice(("short", "parted", "long", "bun", "curly"))
        body.ellipsoid((0,1.98,-.02),(.30,.22,.27),hair,6,10)
        if style in ("long", "curly"):
            body.ellipsoid((0,1.75,-.105),(.30,.36 if style == "long" else .27,.17),hair,7,9)
        elif style == "bun":
            body.ellipsoid((0,2.08,-.20),(.12,.12,.12),hair,5,7)
        for ex in (-.065,.065):
            body.ellipsoid((ex,1.91,.135),(.025,.022,.015),color.rgb32(25,24,23),5,7)
            body.ellipsoid((ex*1.9,1.91,0),(.055,.075,.06),skin,5,7)
        body.ellipsoid((0,1.865,.17),(.035,.07,.045),skin,5,7)
        body.box((0,1.795,.155),(.11,.018,.018),color.rgb32(110,56,50))

        # One mesh for the torso/head and one for each animated limb, limiting
        # draw entities while retaining articulated walking and death poses.
        self.detail_root.model=body.mesh()
        self.left_arm=Entity(parent=self.detail_root,position=(-.26,1.38,0))
        self.right_arm=Entity(parent=self.detail_root,position=(.26,1.38,0))
        for part in (arm,):
            part.ellipsoid((0,-.16,0),(.13,.32,.13),shirt,6,8)
            part.ellipsoid((0,-.38,.01),(.11,.28,.11),skin,6,8)
            part.ellipsoid((0,-.53,.01),(.10,.10,.09),skin,5,7)
        self.left_arm.model=arm.mesh()
        self.right_arm.model=arm.mesh()
        leg.ellipsoid((0,-.18,0),(.18,.38,.18),trousers,6,8)
        leg.box((0,-.43,0),(.14,.32,.16),trousers)
        leg.box((0,-.60,.04),(.14,.09,.22),color.rgb32(28,22,16))
        self.left_leg=Entity(parent=self.detail_root,position=(-.13,.95,0))
        self.right_leg=Entity(parent=self.detail_root,position=(.13,.95,0))
        self.left_leg.model=leg.mesh()
        self.right_leg.model=leg.mesh()
        self.display_name = f"{self.age_group.replace('_',' ').title()} {self.gender.title()}"

    @property
    def alive(self) -> bool:
        return self.brain.alive

    @property
    def state(self) -> CivilianState:
        return self.brain.state

    def reset(self, position, persistent_id: str) -> None:
        """Reactivate a pooled actor at a deterministic chunk spawn point."""
        self.chart_x = float(position[0])
        self.chart_z = float(position[2] if len(position) > 2 else position[1])
        self.persistent_id = persistent_id
        self.brain = CivilianBrain(SimVec3(self.chart_x,0,self.chart_z))
        self.entity.civilian_owner = self
        self.entity.display_name = self.display_name
        self.entity.take_damage = self.take_damage
        self.entity.apply_heat = self.apply_heat
        self.entity.freeze = self.freeze
        self.entity.model = None
        self.entity.collider = "box"
        self.entity.scale = (.58,1.85,.58)
        self.entity.color = color.white
        mapped = self.game.planet.point_from_local(self.chart_x,self.chart_z,.95)
        self.entity.position = (mapped.x, mapped.y, mapped.z)
        self.entity.rotation = (0,0,0)
        self.entity.enable()
        self.detail_root.enable()
        self.detail_root.position=(0,0,0)
        self.detail_root.rotation=(0,0,0)
        self.left_arm.rotation=(0,0,0); self.right_arm.rotation=(0,0,0)
        self.left_leg.rotation=(0,0,0); self.right_leg.rotation=(0,0,0)
        self._walk_time=self._wander_time=self._animation_timer=self._simulation_timer=0.0
        self._detailed_visual=True
        self.knockback=SimVec3(); self.freeze_until=0.0; self.death_age=0.0
        self._death_recorded=False; self._spatial_chunk=None
        self._corpse_damping=4.5

    def set_visual_lod(self, detailed: bool) -> None:
        detailed=bool(detailed)
        if detailed == self._detailed_visual:
            return
        self._detailed_visual=detailed
        self.detail_root.enabled=detailed
        self.entity.model=None if detailed else "cube"
        self.entity.collider="box" if detailed and self.alive else None
        if not detailed:
            self.entity.color=self._proxy_tint

    def react_to_danger(self, origin: SimVec3) -> None:
        self.brain.react_to_danger(origin,self.random)

    def take_damage(self, amount: float, impulse: SimVec3 | None=None, *,
                    impact_speed: float=0.0, impact_position=None) -> bool:
        if not self.alive:
            return False
        actual=self.brain.apply_damage(max(0.0,float(amount)))
        if actual<=0.0:
            return False
        if impulse is not None:
            self.knockback=self.knockback+impulse.clamped(95.0)
        if not self.alive:
            self._die(impact_speed)
            return True
        self.react_to_danger(SimVec3(self.chart_x,0,self.chart_z))
        if self.brain.state is CivilianState.INJURED and self._detailed_visual:
            self.left_arm.rotation_z=-22; self.right_arm.rotation_z=22
        return False

    def apply_heat(self, amount: float, impulse: SimVec3 | None=None) -> bool:
        return self.take_damage(amount,impulse)

    def freeze(self, seconds: float) -> None:
        if self.alive:
            self.freeze_until=max(self.freeze_until,self.game.elapsed+max(0.0,seconds))

    def _die(self, impact_speed: float=0.0) -> None:
        if self._death_recorded:
            return
        self._death_recorded=True
        self.brain.state=CivilianState.DEAD
        self.brain.target=None
        self.death_age=0.0
        self.entity.collider=None
        ragdoll_quality=getattr(self.game.settings,"ragdoll_quality","medium")
        pose={"low":(.30,42,42),"medium":(.48,62,68),"high":(.56,78,86)}
        drop, root_tilt, limb_swing=pose.get(ragdoll_quality,pose["medium"])
        self._corpse_damping={"low":3.2,"medium":4.5,"high":6.0}.get(ragdoll_quality,4.5)
        self.detail_root.position=(0,-drop,0)
        self.detail_root.rotation_z=root_tilt if self.knockback.x>=0 else -root_tilt
        if self._detailed_visual:
            self.left_arm.rotation_x=limb_swing; self.right_arm.rotation_x=-limb_swing
            self.left_leg.rotation_x=limb_swing*.60; self.right_leg.rotation_x=-limb_swing*.48
        self.game.world.record_civilian_death(self)

    def step(self, dt: float, *, player_chart=None) -> None:
        dt=max(0.0,min(float(dt),.1))
        if not self.alive:
            self.death_age+=dt
            if self.knockback.length()>.1:
                self.knockback=self.knockback*max(0.0,1.0-self._corpse_damping*dt)
                self.entity.position+=Vec3(self.knockback.x*dt,self.knockback.y*dt,self.knockback.z*dt)
            return
        if self.game.elapsed<self.freeze_until:
            return
        self._walk_time+=dt; self._wander_time-=dt
        sentry=getattr(self.game,"sentry",None)
        sentry_x=sentry_z=None
        if player_chart is not None:
            sentry_x,sentry_z=player_chart
        elif sentry is not None:
            sentry_x,sentry_z=self.game.planet.local_coordinates(SimVec3(sentry.x,sentry.y,sentry.z))
        danger=None
        if sentry_x is not None:
            dx,dz=self.chart_x-sentry_x,self.chart_z-sentry_z
            distance_sq=dx*dx+dz*dz
            if distance_sq<17.0**2:
                danger=SimVec3(sentry_x,0,sentry_z)
            elif distance_sq<40.0**2 and self.brain.state in (CivilianState.IDLE,CivilianState.TALKING):
                self.game.planet.orient_entity(self.entity,
                    SimVec3(self.entity.x,self.entity.y,self.entity.z),degrees(atan2(sentry_x-self.chart_x,sentry_z-self.chart_z)))

        if self.brain.target is None and self._wander_time<=0.0 and self.brain.state not in (CivilianState.IDLE,CivilianState.TALKING):
            self.brain.target=self.brain.position+SimVec3(self.random.uniform(-8,8),0,self.random.uniform(-8,8))
            self._wander_time=self.random.uniform(2.0,5.0)
        old=self.brain.position
        new=self.brain.step(dt,danger=danger,rng=self.random)
        if not self.alive:
            self._die(); return

        # Keep pedestrians out of building footprints; nearby traffic can stop them at a crossing.
        for obstacle in self.game.world.nearby_buildings(new.x,new.z):
            dx,dz=new.x-obstacle.chart_x,new.z-obstacle.chart_z
            clear_x=abs(obstacle.scale_x)*.5+.55; clear_z=abs(obstacle.scale_z)*.5+.55
            if abs(dx)<clear_x and abs(dz)<clear_z:
                if clear_x-abs(dx)<clear_z-abs(dz):
                    new.x=obstacle.chart_x+(clear_x if dx>=0 else -clear_x)
                else:
                    new.z=obstacle.chart_z+(clear_z if dz>=0 else -clear_z)
        for vehicle in self.game.world.nearby_traffic(self.chart_x,self.chart_z,8.0):
            dx,dz=self.chart_x-vehicle.chart_x,self.chart_z-vehicle.chart_z
            if dx*dx+dz*dz<5.0**2:
                self.brain.state=CivilianState.IDLE; self.brain.target=None
                self.brain.reaction_time=.55; new=old; break
        self.brain.position=new
        self.chart_x,self.chart_z=new.x,new.z
        self.game.world.reindex_civilian(self)
        mapped=self.game.planet.point_from_local(self.chart_x,self.chart_z,.95)
        self.entity.position=Vec3(mapped.x,mapped.y,mapped.z)
        direction=new-old
        if direction.length()>.001 and self.brain.state not in (CivilianState.IDLE,CivilianState.TALKING):
            self.game.planet.orient_entity(self.entity,SimVec3(mapped.x,mapped.y,mapped.z),degrees(atan2(direction.x,direction.z)))
        if not self._detailed_visual:
            return
        self._animation_timer+=dt
        quality=getattr(self.game.settings,"npc_animation_quality","medium")
        interval={"low":.16,"medium":.08,"high":.033}.get(quality,.08)
        if self._animation_timer<interval:
            return
        self._animation_timer=0.0
        phase=self._walk_time*(17.0 if self.brain.state in (CivilianState.FLEE,CivilianState.RUNNING) else 10.0)
        swing=sin(phase)*28.0
        self.left_leg.rotation_x=swing; self.right_leg.rotation_x=-swing
        self.left_arm.rotation_x=-swing*.65; self.right_arm.rotation_x=swing*.65
