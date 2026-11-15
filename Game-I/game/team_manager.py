"""Runs the roster: team membership, player control and AI movement."""

from __future__ import annotations

from math import cos, isfinite, pi, sin, sqrt

from ursina import camera, scene

from ai.combat_ai import AttackTokens
from ai.enemy_team_ai import (PERSONALITIES, AITuning, Intent, TargetView, TeamDirector, separation)
from characters.registry import BASE_BODY, definition
from characters.roster import KITS
from characters.roster_character import RosterCharacter
from characters.skinned_visual import preload
from characters.sentry_clone import CLONE_PALETTES, SENTRY_COPY_PALETTE, SQUAD_PALETTES, CloneAssets
from characters.squad import Puppet, SquadFighter
from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM, RosterError, RosterState
from config.sentry_profiles import ENEMY
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers.aiming import center_of
from powers.omni_man import TripleImpactExecution
from powers.void import refresh_ground_shadow
from ui.enemy_team_ui import CharacterTag
from world.destruction_math import sweep_point_aabb

DIRECTOR_INTERVAL = .25
DECISION_INTERVAL = .12  # at 100% Decision Frequency
DECISIONS_PER_FRAME = 2
SPAWN_RADIUS = 58.0
MIN_SPACING = 2.6
OVERLAP_INTERVAL = .1
ALLY_FOLLOW_DISTANCE = 9.0
ARRIVAL_RADIUS = 24.0
AI_CINEMATIC_GAP = 12.0  # AI waits this long between stopping the world, so the player still gets to play
SQUAD_RING = 9.0
SQUAD_FIRST_ATTACK = .5
# Mark, guarding Omni-Man. All of this is what he decides to do; none of it changes what he can do.
GUARD_INTERVAL = .1       # seconds between looks at how Omni-Man is doing
GUARD_NOTICE = 60.0       # metres: an enemy this near Omni-Man counts as a threat, attacking or not
GUARD_ATTACK_NOTICE = 400.0  # and one actually going for him counts from here
GUARD_CLOSE = 6.0         # where he stays when all is quiet
GUARD_BETWEEN = 8.0       # how far out from Omni-Man he stands in the way
GUARD_ROAM = 40.0         # how far from Omni-Man he will go after someone when nothing threatens him
GUARD_REACH = 6.0         # near enough a grabber to make it let go
CRITICAL_HEALTH = .25
SURROUNDED_BY, SURROUNDED_WITHIN = 3, 30.0


class PowerConfig:
    """What AI characters read: the AI profile's movement values."""

    def __init__(self, source, tuning) -> None:
        self.source = source
        self.tuning = tuning
        self.values: dict = {}
        self.refresh()

    def refresh(self) -> None:
        tuning = self.tuning
        self.values = {**tuning.derived(),
                       "flight_speed": tuning.number("flight_speed"),
                       "flight_boost_speed": tuning.number("flight_boost_speed"),
                       "ground_speed": tuning.number("ground_speed")}

    def __contains__(self, key: str) -> bool:
        return key in self.values or key in self.source

    def get(self, key: str, default=None):
        if key in self.values:
            return self.values[key]
        return self.source.get(key, default)


class TreeIndex:
    """Per-chunk tree bounds as plain tuples, for cheap AI collision."""

    def __init__(self, world) -> None:
        self.world = world
        self._cache: dict[tuple[int, int], tuple] = {}

    def chunk_trees(self, key: tuple[int, int]) -> tuple:
        chunk = self.world.chunks.get(key)
        if chunk is None:
            return ()
        cached = self._cache.get(key)
        colliders = chunk.tree_colliders
        if cached is not None and cached[0] is chunk and cached[1] == len(colliders):
            return cached[2]
        bounds = []
        for tree in tuple(colliders):
            radius = tree.tree_radius + .48
            half_height = tree.scale_y * .5 + 1.05
            bounds.append((tree.x - radius, tree.y - half_height, tree.z - radius,
                           tree.x + radius, tree.y + half_height, tree.z + radius, tree))
        result = tuple(bounds)
        self._cache[key] = (chunk, len(colliders), result)
        return result

    def along(self, start: SimVec3, end: SimVec3):
        size = self.world.CHUNK_SIZE
        first = (int(start.x // size), int(start.z // size))
        last = (int(end.x // size), int(end.z // size))
        yield from self.chunk_trees(first)
        if last != first:
            yield from self.chunk_trees(last)

    def sweep(self, sentry, start: SimVec3, end: SimVec3) -> None:
        """Stop a moving character at the first tree on its path."""
        contact = None
        low = min(start.y, end.y)
        segment_start, segment_end = (start.x, start.y, start.z), (end.x, end.y, end.z)
        for bounds in self.along(start, end):
            if low > bounds[4]:
                continue
            hit = sweep_point_aabb(segment_start, segment_end, bounds[:3], bounds[3:6])
            if hit is not None and (contact is None or hit[0] < contact[0]):
                contact = hit
        if contact is None:
            return
        t, normal_tuple = contact
        normal = SimVec3(*normal_tuple)
        center = start + (end - start) * t
        sentry.position = (center.x + normal.x * .025, center.y + normal.y * .025,
                           center.z + normal.z * .025)
        velocity = sentry.velocity
        into = velocity.x * normal.x + velocity.y * normal.y + velocity.z * normal.z
        if into < 0.0:
            velocity = velocity - normal * into
            if sentry.flight.is_flying:
                sentry.flight.velocity = velocity
            else:
                sentry.ground.velocity = velocity


class TeamManager:
    def __init__(self, game) -> None:
        self.game = game
        self.state = RosterState()
        self.scene_root = scene
        self.ai_view = game.profiles.view(ENEMY)
        self.ai_tuning = AITuning.from_profile(self.ai_view)
        self.power_config = PowerConfig(game.sentry_config, self.ai_view)
        self.trees = TreeIndex(game.world)
        yellow = game.sentry
        self.clone_assets = None if yellow.uses_skinned_body else CloneAssets(yellow)
        if yellow.uses_skinned_body:  # nobody's first appearance should stall a frame later on
            preload((*(palette.name for palette in CLONE_PALETTES), *(palette.name for palette in SQUAD_PALETTES)))
        self.director = TeamDirector()
        self.director.tuning = self.ai_tuning
        self._next_director = 0.0
        self._next_overlap = 0.0
        self._decision_cursor = 0
        self._ai: list[RosterCharacter] = []
        self._enemy_views: list = []
        self.attack_tokens = AttackTokens()
        self.squad_tokens = AttackTokens(limit=4)
        self.summons: list[RosterCharacter] = []  # those of the squad in the world now
        self._squad: list[SquadFighter] = []      # all six, built once
        self.squad_tags: dict = {}
        self._cinematic_runner = None
        self._next_guard = 0.0
        self.guard_tokens = AttackTokens(limit=1)  # whoever else is attacking, he never has to wait his turn
        self.leader_threat = None
        self.leader_in_danger = False
        self._puppets: dict[str, list[Puppet]] = {}  # built the first time each is needed, then kept
        self.ground_shadows: set = set()             # whoever Sentry's Void has turned into a shadow now
        self._next_cinematic = 0.0

        yellow.attach_team(self, PERSONALITIES[BASE_BODY], definition(BASE_BODY).seed)
        self.characters: dict[str, RosterCharacter] = {BASE_BODY: yellow}
        for palette, position in zip(CLONE_PALETTES, self.spawn_positions()):
            self.characters[palette.name] = RosterCharacter(
                self, palette, PERSONALITIES[palette.name], position, seed=definition(palette.name).seed)
        self.tags = {character_id: CharacterTag(character)
                     for character_id, character in self.characters.items()}
        self._apply_roster()
        if self.state.player != BASE_BODY:
            self.swap(self.state.player, save=False)
        if yellow.uses_skinned_body:  # built now, while loading, instead of in the middle of somebody's fight
            self._build_squad()
            self.return_puppets(self.borrow_puppets("BLACK", 4))
            self.return_puppets(self.borrow_puppets(BASE_BODY, 1))

    # -- views of the roster ---------------------------------------------
    @property
    def player(self) -> RosterCharacter:
        return self.game.sentry

    @property
    def player_position(self) -> SimVec3:
        player = self.player
        return SimVec3(player.x, player.y, player.z)

    def members(self, team: str) -> list[RosterCharacter]:
        return [self.characters[character_id] for character_id in self.state.members(team)]

    @property
    def enemies(self) -> list[RosterCharacter]:
        return self.members(ENEMY_TEAM)

    @property
    def allies(self) -> list[RosterCharacter]:
        return [member for member in self.members(MY_TEAM) if member is not self.player]

    @property
    def others(self) -> list[RosterCharacter]:
        """Everyone in the world except the player; these never block the chase camera."""
        return self._ai

    def spawn_positions(self) -> list[tuple[float, float, float]]:
        """Ring the player on clear land, away from trees and from each other."""
        world = self.game.world
        planet = self.game.planet
        origin_x, origin_z = self.game.sentry.x, self.game.sentry.z
        placed: list[tuple[float, float, float]] = []
        count = len(CLONE_PALETTES)
        for index in range(count):
            base = 2.0 * pi * index / count
            for attempt in range(24):
                angle = base + attempt * .13 * (-1) ** attempt
                radius = SPAWN_RADIUS + attempt * 3.0
                x, z = planet.clamp_to_land(origin_x + sin(angle) * radius,
                                            origin_z + cos(angle) * radius, 40.0)
                if self._spawn_is_clear(x, z, placed):
                    break
            placed.append((x, world.height_at(x, z) + .25, z))
        return placed

    def _spawn_is_clear(self, x: float, z: float, placed) -> bool:
        world = self.game.world
        if not world.contains_position(x, z):
            return False
        if any((x - px) ** 2 + (z - pz) ** 2 < 100.0 for px, _py, pz in placed):
            return False
        for tree in world._nearby_tree_colliders(x, z, 1):
            if (tree.x - x) ** 2 + (tree.z - z) ** 2 < 36.0:
                return False
        return True

    # -- team changes ----------------------------------------------------
    def assign(self, character_id: str, team: str) -> None:
        """Move one character between teams; raises RosterError if a rule forbids it."""
        character = self.characters[character_id]
        was_parked = character.parked
        self.state.move(character_id, team)
        self._apply_roster()
        if was_parked and not character.parked:
            self._place_near_player(character)
        self.state.save()

    def swap(self, character_id: str, *, save: bool = True) -> None:
        """Take over any character's actual body, with no respawn.

        A character on another team, or waiting in Available, joins My Team first. The
        previous character stays where it is, on My Team, and carries on as an AI ally.
        """
        was_parked = self.characters[character_id].parked
        if self.state.team_of(character_id) != MY_TEAM:
            self.state.assignment[character_id] = MY_TEAM
        self.state.select_player(character_id)
        previous = self.game.sentry
        chosen = self.characters[character_id]
        if chosen is not previous:
            self.game.release_inputs()
            previous.set_controlled(False)
            previous.thrusting = True  # the keys were saying otherwise; as an AI ally it flies wherever it is flying
            chosen.set_controlled(True)
            self.game.sentry = chosen
            self.game.on_player_changed()
        self._apply_roster()
        if was_parked:
            self._place_near_player(chosen)
        if save:
            self.save_session()

    # -- saved session ---------------------------------------------------
    def save_session(self) -> bool:
        """Each character's health, energy, cooldowns and position, beside the roster."""
        session = {}
        for character_id, character in self.characters.items():
            session[character_id] = {**character.powers.snapshot(),
                                     "position": [round(float(character.x), 3),
                                                  round(float(character.y), 3),
                                                  round(float(character.z), 3)],
                                     "flying": bool(character.flight.is_flying)}
        self.state.session = session
        return self.state.save()

    def load_session(self) -> bool:
        """The save file again, over the running game: teams, who the player is, and everyone's state and place."""
        if not self.state.load():
            return False
        self._apply_roster()
        self.swap(self.state.player, save=False)
        self.restore_session()
        return True

    def restore_session(self) -> None:
        for character_id, saved in self.state.session.items():
            character = self.characters[character_id]
            character.powers.restore(saved)
            position = saved.get("position")
            if not (isinstance(position, list) and len(position) == 3
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v)
                            for v in position)):
                continue
            x, y, z = (float(v) for v in position)
            if not self.game.world.contains_position(x, z):
                continue
            floor = self.game.world.height_at(x, z) + .25
            # Soldier Boy is never restored to the air, whatever a save says.
            flying = saved.get("flying") is True and character.flight_allowed
            character.position = (x, min(490.0, max(floor, y)) if flying else floor, z)
            if flying:
                character.flight.phase = FlightPhase.CRUISE

    def _apply_roster(self) -> None:
        self._ai = []
        for character_id, character in self.characters.items():
            parked = self.state.team_of(character_id) == AVAILABLE
            if parked != character.parked:
                character.set_parked(parked)
            if not parked and character is not self.game.sentry:
                self._ai.append(character)
            self.tags[character_id].set_team(self.state.team_of(character_id),
                                             character is self.game.sentry)
        if self.summons and self.state.team_of("GREEN") == AVAILABLE:
            self.characters["GREEN"].powers.abilities["squad_summon"].dismiss()  # he has left the world
            if self.summons:  # any that key 4 has out for the moment
                self.withdraw_squad(list(self.summons))
        for member in self.summons:
            self._ai.append(member)
            self.squad_tags[member].set_team(self.state.team_of("GREEN"), False)
        combat = getattr(self.game, "combat", None)
        if combat is not None:
            combat.targets.clear()
        self._enemy_views = [enemy.view for enemy in self.enemies]
        self.director = TeamDirector()
        self.director.tuning = self.ai_tuning
        self._next_director = 0.0

    def _place_near_player(self, character: RosterCharacter) -> None:
        player = self.player
        angle = self.game.elapsed
        x, z = self.game.planet.clamp_to_land(player.x + sin(angle) * 30.0,
                                              player.z + cos(angle) * 30.0, 40.0)
        character.position = (x, self.game.world.height_at(x, z) + .25, z)
        character.flight.phase = FlightPhase.GROUNDED
        character.flight.velocity = SimVec3()
        character.ground.velocity = SimVec3()
        character.intent = None

    # -- Omni-Man's squad ------------------------------------------------
    def _build_squad(self) -> None:
        for index, palette in enumerate(SQUAD_PALETTES):
            member = SquadFighter(self, palette, PERSONALITIES["GREEN"], (0.0, 0.0, 0.0), seed=4100 + index * 37)
            self.squad_tags[member] = CharacterTag(member)
            member.set_parked(True)
            self._squad.append(member)

    def deploy_squad(self, leader: RosterCharacter, viltrumites: int = 5, mark: bool = True) -> list[RosterCharacter]:
        """Whichever of the same six bodies are wanted and not out already, around him, ready to fight."""
        if not self._squad:
            self._build_squad()
        world, planet = self.game.world, self.game.planet
        now = self.game.elapsed
        chosen = [*self._squad[:viltrumites], *self._squad[5:] * mark]  # the five Viltrumites, then Mark
        deployed = [member for member in chosen if member not in self.summons]
        for index, member in enumerate(deployed):
            member.powers.apply_passives()  # whatever his maximum health is set to now
            member.powers.hard_reset()
            member.release_motion()
            angle = 2.0 * pi * index / len(deployed)
            x, z = planet.clamp_to_land(float(leader.x) + sin(angle) * SQUAD_RING,
                                        float(leader.z) + cos(angle) * SQUAD_RING, 40.0)
            floor = world.height_at(x, z) + .25
            flying = leader.flight.is_flying
            member.position = (x, max(floor, float(leader.y)) if flying else floor, z)
            member.flight.phase = FlightPhase.CRUISE if flying else FlightPhase.GROUNDED
            member.flight.velocity = SimVec3()
            member.ground.velocity = SimVec3()
            member.knock = SimVec3()
            member.jump_height = member.jump_velocity = 0.0
            member.intent = None
            member.next_decision = 0.0
            member._ai_next_attack = now + SQUAD_FIRST_ATTACK + index * .2
            member.set_parked(False)
        self.summons = [*self.summons, *deployed]
        self._apply_roster()
        return deployed

    def withdraw_squad(self, members) -> None:
        for member in members:
            member.powers.cancel_all()
            member.release_motion()
            member._end_ai_move()
            member.vitals.statuses.clear()
            member.vitals.downed_for = 0.0
            member.pose_root.setP(0.0)
            member.set_parked(True)
        self.summons = [member for member in self.summons if member not in members]
        self._apply_roster()

    def borrow_puppets(self, character_id: str, count: int) -> list[Puppet]:
        """Bodies for an execution to move. Only as many are ever built as have been needed at once."""
        pool = self._puppets.setdefault(character_id, [])
        free = [puppet for puppet in pool if puppet.parked]
        palette = next((palette for palette in (*CLONE_PALETTES, SENTRY_COPY_PALETTE) if palette.name == character_id))
        while len(free) < count:
            puppet = Puppet(self, palette, PERSONALITIES[character_id], seed=5200 + len(pool))
            pool.append(puppet)
            free.append(puppet)
        chosen = free[:count]
        for puppet in chosen:
            puppet.set_parked(False)
        return chosen

    def return_puppets(self, puppets) -> None:
        for puppet in puppets:
            puppet.pose_root.setP(0.0)
            puppet.set_parked(True)

    def tag_of(self, character) -> CharacterTag:
        return self.squad_tags.get(character) or self.tags[character.character_id]

    def _squad_intent(self, member, view, target: TargetView) -> Intent:
        """Go for the nearest enemy, as long as it is within their Range; otherwise back to Omni-Man."""
        leader = self.characters["GREEN"]
        reach = leader.powers.abilities["squad_summon"].reach()
        enemy = self.game.combat.targets.lock_of(member)
        if enemy is not None:
            point = SimVec3(float(enemy.x), float(enemy.y), float(enemy.z))
            distance = (view.position - point).length()
            if distance <= reach:
                return Intent(point, enemy.velocity, True, distance)
        here = SimVec3(float(leader.x), float(leader.y) + 1.5, float(leader.z))
        index = self.summons.index(member)
        angle = index * 2.0 * pi / max(1, len(self.summons))
        home = here + SimVec3(sin(angle) * SQUAD_RING, 0.0, cos(angle) * SQUAD_RING)
        distance = (view.position - here).length()
        return Intent(home, leader.velocity if distance < ARRIVAL_RADIUS else SimVec3(),
                      leader.flight.is_flying or distance > 60.0, distance)

    # -- Mark, Omni-Man's bodyguard ---------------------------------------
    def _bodyguard(self):
        """Found by his role, every time: never by how he looks, or where in the squad he came."""
        return next((member for member in self.summons if member.guards_leader and not member.vitals.downed), None)

    def _grabber_of(self, leader):
        """Whoever has Omni-Man in their hands, by a grab or partway through an attack."""
        for enemy in self.game.combat.hostiles_of(leader):
            grab = enemy.powers.abilities.get("grab")
            if grab is not None and grab.held is leader:
                return enemy
            if leader.vitals.has("held") and getattr(enemy.motion, "target", None) is leader:
                return enemy
        return None

    def _read_threats(self, leader) -> tuple:
        """Who is the worst danger to Omni-Man now, and whether he needs rescuing from it."""
        combat = self.game.combat
        here = center_of(leader)
        enemies = combat.hostiles_of(leader)
        distance = {enemy: (center_of(enemy) - here).length() for enemy in enemies}
        grabber = self._grabber_of(leader)
        surrounded = sum(away <= SURROUNDED_WITHIN for away in distance.values()) >= SURROUNDED_BY
        danger = grabber is not None or surrounded or leader.vitals.fraction < CRITICAL_HEALTH

        def going_for_him(enemy) -> bool:
            if getattr(enemy.motion, "target", None) is leader:
                return True
            if enemy.controlled:
                return combat.targets.manual is leader
            aiming = enemy._ai_move is not None or enemy.motion is not None
            return aiming and combat.targets._locks.get(enemy) is leader

        attackers = [enemy for enemy in enemies if distance[enemy] <= GUARD_ATTACK_NOTICE and going_for_him(enemy)]
        nearby = [enemy for enemy in enemies if distance[enemy] <= GUARD_NOTICE]
        threat = grabber or min(attackers or nearby, key=distance.get, default=None)
        return threat, danger and threat is not None

    def _guard_leader(self, now: float) -> None:
        if 0.0 < self._next_guard - now <= GUARD_INTERVAL:  # the clock can start again, on a restart
            return
        self._next_guard = now + GUARD_INTERVAL
        mark, leader = self._bodyguard(), self.characters["GREEN"]
        if mark is None or leader.parked:
            self.leader_threat, self.leader_in_danger = None, False
            return
        if isinstance(leader.motion, TripleImpactExecution):
            return  # that sequence places the squad itself
        self.leader_threat, self.leader_in_danger = self._read_threats(leader)
        threat = self.leader_threat
        targets = self.game.combat.targets
        if threat is not None:  # this is who his punches and his charge go for
            targets._locks[mark] = threat
            targets._next[mark] = now + GUARD_INTERVAL * 3.0
        if self.leader_in_danger:
            self._drop_everything_for(mark, threat, now)
            self._break_the_grip(mark, leader, now)
        mark.next_decision = now + 1.0  # this is his thinking, at his own rate
        mark.refresh_view()
        mark.adopt_intent(self._guard_intent(mark, leader, threat))

    def _drop_everything_for(self, mark, threat, now: float) -> None:
        """Whatever he was doing that is not this ends now, and he may strike straight away."""
        motion = mark.motion
        if motion is not None and not motion.ballistic and getattr(motion, "target", None) is not threat:
            mark.release_motion()
        if mark.powers.abilities["grab"].held not in (None, threat):
            mark._end_ai_move()
        mark._ai_next_attack = min(mark._ai_next_attack, now)

    def _break_the_grip(self, mark, leader, now: float) -> None:
        """At arm's length of whoever is holding him: the blow lands, and the hold is broken."""
        grabber = self._grabber_of(leader)
        if grabber is None or mark.vitals.immobile:
            return
        if (center_of(grabber) - center_of(mark)).length() > GUARD_REACH:
            return
        mark.powers.abilities["melee"].land_blow(grabber)
        grabber.powers.abilities["grab"].cancel()
        if getattr(grabber.motion, "target", None) is leader:
            grabber.release_motion()
        leader.vitals.clear_status("held")

    def _guard_intent(self, mark, leader, threat) -> Intent:
        here = SimVec3(float(mark.x), float(mark.y), float(mark.z))
        home = SimVec3(float(leader.x), float(leader.y), float(leader.z))
        flying = True
        if threat is not None:
            there = SimVec3(float(threat.x), float(threat.y), float(threat.z))
            if self.leader_in_danger:
                return Intent(there, threat.velocity, flying, (there - here).length())
            away = there - home
            spot = home + away.normalized() * min(GUARD_BETWEEN, away.length() * .5)  # squarely in the way
            return Intent(spot, leader.velocity, flying, (spot - here).length())
        enemy = self.game.combat.targets.lock_of(mark)  # nothing near him: normal combat, without leaving him
        if enemy is not None and (center_of(enemy) - center_of(leader)).length() <= GUARD_ROAM:
            there = SimVec3(float(enemy.x), float(enemy.y), float(enemy.z))
            return Intent(there, enemy.velocity, flying, (there - here).length())
        spot = home + SimVec3(GUARD_CLOSE, 1.5, 0.0)
        distance = (spot - here).length()
        return Intent(spot, leader.velocity if distance < ARRIVAL_RADIUS else SimVec3(),
                      leader.flight.is_flying or distance > 60.0, distance)

    # -- AI and the stopped world ----------------------------------------
    def cinematic_ready(self, now: float) -> bool:
        runner = self._cinematic_runner
        return (now >= self._next_cinematic and not self.game.combat.time_stopped
                and (runner is None or runner.motion is None or runner.parked))  # one at a time, however long it runs

    def cinematic_started(self, now: float, character) -> None:
        self._next_cinematic = now + AI_CINEMATIC_GAP
        self._cinematic_runner = character

    def apply_config(self) -> None:
        self.ai_tuning = AITuning.from_profile(self.ai_view)
        self.director.tuning = self.ai_tuning
        self.power_config.refresh()
        for character in self._squad:
            character.brain.tuning = self.ai_tuning
            if getattr(self.game, "combat", None) is not None:
                character.powers.apply_passives()
            character.apply_sentry_config()
        for character in self.characters.values():
            character.brain.tuning = self.ai_tuning
            if getattr(self.game, "combat", None) is not None:
                character.powers.apply_passives()
            character.apply_sentry_config()
        names = self.game.tuning.flag("show_enemy_names")
        for tag in self.tags.values():
            tag.set_visible(names)

    def separation_push(self, character: RosterCharacter) -> SimVec3:
        character.refresh_view()
        return separation(character.view, [other.view for other in self._ai])

    # -- per-frame update ------------------------------------------------
    def _target_view(self) -> TargetView:
        player = self.player
        position = SimVec3(player.x, player.y, player.z)
        return TargetView(position, player.velocity, player.flight.is_flying,
                          self.game.planet.altitude(position))

    def update(self, dt: float) -> None:
        combat = self.game.combat
        if combat.time_stopped:
            # Whoever the player has sent flying stays in time with them. Every other AI stands frozen.
            thrown = combat.time_stop_target
            if (thrown is not None and combat.time_stop_owner is not None
                    and thrown.motion is not None and thrown.motion.ballistic):
                thrown._step_motion_only(dt)
            self._update_tags()  # bars still show what the player does
            return
        now = self.game.elapsed
        target = self._target_view()
        enemies = self.enemies
        if now >= self._next_director:
            self._next_director = now + DIRECTOR_INTERVAL
            for enemy in enemies:
                enemy.refresh_view()
            self.director.update(now, self._enemy_views, target)
        self._guard_leader(now)
        self._run_decisions(now, target)
        self._run_ai_combat(dt, now)
        px, py, pz = target.position.x, target.position.y, target.position.z
        for character in self._ai:
            dx, dy, dz = character.x - px, character.y - py, character.z - pz
            distance_sq = dx * dx + dy * dy + dz * dz
            character.step(dt, distance_sq)
        self._update_tags()
        if now >= self._next_overlap:
            self._next_overlap = now + OVERLAP_INTERVAL
            self._resolve_overlaps()

    def shift_ai_clocks(self, seconds: float) -> None:
        """Time stopped for this long, so every wait measured against the game clock moves on too."""
        self._next_director += seconds
        self._next_cinematic += seconds
        self._next_overlap += seconds
        for character in (*self.characters.values(), *self.summons):
            character.next_decision += seconds
            character._ai_next_attack += seconds
            character._next_leap += seconds
            character._next_mode_change += seconds
            character._unstuck_until += seconds

    def refresh_tags(self) -> None:
        """Bars and HUD show a settings change at once, even while a menu has the game paused."""
        self._update_tags()

    def _update_tags(self) -> None:
        """Health and size of every bar, for the player's own included."""
        for body in self.ground_shadows:
            refresh_ground_shadow(body)
        eye = camera.world_position
        for character_id, character in self.characters.items():
            if not character.parked:
                dx, dy, dz = character.x - eye.x, character.y - eye.y, character.z - eye.z
                self.tags[character_id].update(sqrt(dx * dx + dy * dy + dz * dz), character.vitals)
        for character in self.summons:
            dx, dy, dz = character.x - eye.x, character.y - eye.y, character.z - eye.z
            self.squad_tags[character].update(sqrt(dx * dx + dy * dy + dz * dz), character.vitals)

    def _run_ai_combat(self, dt: float, now: float) -> None:
        combat = self.game.combat
        for character in self._ai:
            if combat.time_stopped:
                return  # someone earlier in this very loop has just stopped the world
            squad = character.ai_moves is not None
            if squad or combat.ai_powers_enabled:  # called in by a key, so that setting does not bench them
                tokens = self.attack_tokens if not squad else (
                    self.guard_tokens if character.guards_leader else self.squad_tokens)
                character.run_ai_combat(dt, now, tokens, combat.hostiles_of(character))

    def _run_decisions(self, now: float, target: TargetView) -> None:
        count = len(self._ai)
        if not count:
            return
        decided = 0
        frequency = max(.01, self.ai_view.fraction("decision_frequency_pct"))
        for offset in range(count):
            character = self._ai[(self._decision_cursor + offset) % count]
            if now < character.next_decision:
                continue
            character.next_decision = now + DECISION_INTERVAL / frequency
            self._decide(character, now, target)
            decided += 1
            if decided >= DECISIONS_PER_FRAME:
                self._decision_cursor = (self._decision_cursor + offset + 1) % count
                break

    def _decide(self, character: RosterCharacter, now: float, target: TargetView) -> None:
        view = character.refresh_view()
        if character.ai_moves is not None:
            intent = self._squad_intent(character, view, target)
        elif self.state.team_of(character.character_id) == MY_TEAM:
            intent = self._follow_intent(character, view, target)
        else:
            fc = character.flight.config
            intent = character.brain.decide(now, view, target, self.director, self._enemy_views,
                                            flight_speed=max(fc.boost_speed, fc.cruise_speed))
        character.adopt_intent(intent)

    def _follow_intent(self, character: RosterCharacter, view, target: TargetView) -> Intent:
        """Allies stay close to the player and fly only when the player does."""
        index = self.allies.index(character) if character in self.allies else 0
        angle = 2.4 + index * 1.25
        destination = target.position + SimVec3(sin(angle) * ALLY_FOLLOW_DISTANCE, 1.5,
                                                cos(angle) * ALLY_FOLLOW_DISTANCE)
        distance = (view.position - target.position).length()
        wants_flight = character.flight_allowed and (target.flying or distance > 120.0)
        return Intent(destination, target.velocity if distance < ARRIVAL_RADIUS else SimVec3(),
                      wants_flight, distance)

    def _resolve_overlaps(self) -> None:
        """Hard floor under the steering push so character models never intersect."""
        characters = self._ai
        px, py, pz = self.player.x, self.player.y, self.player.z
        for index, character in enumerate(characters):
            ex, ey, ez = character.x, character.y, character.z
            for other in characters[index + 1:]:
                dx, dy, dz = ex - other.x, ey - other.y, ez - other.z
                distance_sq = dx * dx + dy * dy + dz * dz
                if 1e-6 < distance_sq < MIN_SPACING * MIN_SPACING:
                    distance = sqrt(distance_sq)
                    push = (MIN_SPACING - distance) * .5 / distance
                    character.x += dx * push
                    character.z += dz * push
                    other.x -= dx * push
                    other.z -= dz * push
            dx, dy, dz = ex - px, ey - py, ez - pz
            distance_sq = dx * dx + dy * dy + dz * dz
            if 1e-6 < distance_sq < MIN_SPACING * MIN_SPACING:
                push = (MIN_SPACING - sqrt(distance_sq)) / sqrt(distance_sq)
                character.x += dx * push
                character.z += dz * push


__all__ = ["KITS", "RosterError", "TeamManager"]
