"""Coordinates input, movement, the roster, world simulation and the HUD."""

from __future__ import annotations

import atexit
from dataclasses import replace
from ursina import application, held_keys, mouse, scene, time, window

from characters.roster_character import YellowSentry
from math import ceil

from config import load_settings, resolution_of, save_settings, QUALITY_PRESETS
from combat.sentry_combat import BoostGate
from config.sentry_profiles import PLAYER, ProfileStore, SETTINGS
from game.combat_system import CombatSystem
from game.controls import (AUTO_TARGET_LOCK_KEY, ABILITY_SLOTS, CONTROL_BINDINGS, KEY_ACTIONS, SLOT_RELEASES,
                           apply_bindings, normalize_key)
from ui.debug_overlay import DebugOverlay
from ui.visual_effects import PlayerVisualEffects
from game.camera_manager import CameraManager, ZOOM_STEP
from game.sandbox_lighting import SandboxLighting
from game.input_manager import InputManager
from game.team_manager import TeamManager
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from ui.hud import SentryHUD
from ui.loading_screen import report as report_loading
from ui.main_menu import MainMenu
from ui.character_power_panel import CharacterPowerPanel
from powers.ground_impact import MIN_HEIGHT
from ui.enemy_team_ui import _DefaultShader
from ui.profile_settings_page import ProfileSettingsPage
from ui.team_manager_panel import TeamManagerPanel
from config.sentry_config import SentrySettings
from game.world_manager import WorldManager
from world.destruction_math import DestructionScales
from world.landmarks import Landmarks


QUIET_SWEEP_SECONDS = 2.0
PHYSICS_STEP, MAX_PHYSICS_STEPS = 1.0 / 48.0, 3


def quiet_static_entities() -> None:
    """Ursina walks every entity's ancestors each frame, even one with nothing to update.

    Most of the world has no update, input or script, so it can safely skip that walk.
    """
    for entity in scene.entities:
        if (not entity.ignore and not hasattr(entity, "update") and not hasattr(entity, "input")
                and not getattr(entity, "scripts", None)
                and not hasattr(entity.shader, "continuous_input")):
            entity.ignore = True


class GameManager:
    def __init__(self):
        self.settings = load_settings()
        self.elapsed = 0.0
        self.frame_seconds = 0.0  # this frame's real length, before the simulation's cap
        self._next_quiet_sweep = 0.0
        self.paused = False
        self.at_title = False
        self.camera_impulse = 0.0
        self._notification = ""
        self._notification_until = 0.0
        self._windowed_resolution = resolution_of(self.settings)
        # main.build_game explicitly starts windowed; Ursina's getter defaults True
        # until the fullscreen setter has been called once.
        self._is_fullscreen = False
        self._had_focus = True

        self.sentry_config = SentrySettings()
        self.profiles = ProfileStore(self.sentry_config)
        self.tuning = self.profiles.view(PLAYER)
        self._push_player_profile()
        self._boost_gate = BoostGate()
        self.sentry_config.add_listener(self.apply_sentry_config)

        report_loading(.08, "BUILDING THE ISLAND")
        self.world_manager = WorldManager(self, self.settings)
        self.world = self.world_manager.world
        start = self.planet.point_from_local(0.0, 0.0, .25)
        start_position = (start.x, start.y, start.z)
        report_loading(.4, "LOADING CHARACTERS")
        self.sentry = YellowSentry(self, position=start_position)
        self.sentry.position = start_position
        self.camera = CameraManager(self)
        self.environment = SandboxLighting(self)
        self.input_manager = InputManager(self)
        self.hud = SentryHUD(self)
        self.combat = None
        report_loading(.5, "ASSEMBLING THE ROSTER")
        self.teams = TeamManager(self)
        report_loading(.85, "ARMING POWERS AND ABILITIES")
        self.combat = CombatSystem(self)
        self.landmarks = Landmarks(self)
        self.power_panel = CharacterPowerPanel(self)
        self.team_panel = TeamManagerPanel(self)
        with _DefaultShader():
            self.settings_page = ProfileSettingsPage(self, self)
            self.main_menu = MainMenu(self)
        self.debug_overlay = DebugOverlay(self)
        self.visual_effects = PlayerVisualEffects(self)
        self.apply_sentry_config()
        self.combat.apply_settings()
        self.teams.restore_session()
        self.on_player_changed()
        atexit.register(self.teams.save_session)

    # -- menus -----------------------------------------------------------
    def release_inputs(self) -> None:
        """No key stays held across a menu, a swap or lost focus, and nothing keeps firing."""
        for key in tuple(held_keys):
            held_keys[key] = 0
        self.sentry.powers.on_input_lost()

    def _set_menu_mouse(self, in_menu: bool) -> None:
        if getattr(application.base, "win", None) is not None:
            mouse.locked = not in_menu
            mouse.visible = in_menu

    @property
    def menu_open(self) -> bool:
        return self.power_panel.visible or self.team_panel.visible or self.settings_page.enabled

    def toggle_power_panel(self) -> None:
        """P: Character Power Configuration. Returns to the pause menu if opened from there."""
        if self.power_panel.visible:
            self.power_panel.close()
            self._close_menu()
        else:
            self._open_menu(self.team_panel)
            self.power_panel.open()

    def toggle_team_panel(self) -> None:
        """M: the character switcher and team manager, available at any time."""
        if self.team_panel.visible:
            self.team_panel.close()
            self._close_menu()
        else:
            self._open_menu(self.power_panel)
            self.team_panel.open()

    def open_settings_page(self) -> None:
        self._open_menu(None)
        self.settings_page.open()

    def page_closed(self) -> None:
        """The camera, audio and keys page has closed."""
        self._close_menu()

    # -- the title screen ------------------------------------------------
    def show_title(self) -> None:
        self.at_title = True
        self.release_inputs()
        self.hud.set_atlas_visible(True)
        self.hud.set_status_visible(False)
        self.main_menu.set_visible(True)
        self._set_menu_mouse(True)

    def leave_title(self) -> None:
        self.at_title = False
        self.main_menu.started = True
        self.main_menu.set_visible(False)
        self.release_inputs()
        self.hud.set_atlas_visible(False)
        self._set_menu_mouse(False)

    def return_to_title(self) -> None:
        """The pause menu's MAIN MENU. Nothing is lost: the game waits where it was, and CONTINUE goes back to it."""
        self.paused = False
        self.hud.set_paused(False)
        self.show_title()

    # -- saving ----------------------------------------------------------
    def save_game(self) -> bool:
        """Who is where, in what state, on which team. Power and game settings save themselves when they are changed."""
        return self.teams.save_session()

    def load_game(self) -> bool:
        """Back to the last save, in the running game."""
        return self.teams.load_session()

    def _open_menu(self, other) -> None:
        if other is not None and other.visible:
            other.close()
        if self.at_title:
            self.main_menu.set_visible(False)
        self.release_inputs()
        self.hud.set_atlas_visible(True)
        self.hud.set_status_visible(False)
        if self.paused:
            self.hud.set_paused(False)
        self._set_menu_mouse(True)

    def _close_menu(self) -> None:
        if self.at_title:
            self.release_inputs()
            self.main_menu.set_visible(True)
            self._set_menu_mouse(True)
            return
        self.release_inputs()
        self.hud.set_atlas_visible(self.paused)
        if self.paused:
            self.hud.set_paused(True)
        self._set_menu_mouse(self.paused)

    def _push_player_profile(self) -> None:
        """Publish the player profile's values to the keys and bindings game systems read."""
        self.sentry_config._values.update(self.tuning.derived())
        apply_bindings({setting.key.removeprefix("key_"): self.tuning.value(setting.key)
                        for setting in SETTINGS[PLAYER].values() if setting.kind == "key"})

    def apply_sentry_config(self) -> None:
        self._push_player_profile()
        if hasattr(self, "world"):
            self.world.scales = DestructionScales.from_tuning(self.tuning)
        if hasattr(self, "camera"):
            self.camera.apply_tuning()
        if getattr(self, "visual_effects", None) is not None:
            self.visual_effects.apply()
        if hasattr(self, "teams"):
            self.teams.apply_config()
            if self.combat is not None:
                self.combat.apply_settings()
        elif hasattr(self, "sentry"):
            self.sentry.apply_sentry_config()

    @property
    def camera_transparent(self):
        """Other characters must not pull the chase camera in when they cross behind."""
        teams = getattr(self, "teams", None)
        return teams.others if teams is not None else ()

    def on_area_damage(self, origin, amount: float, radius: float, impulse: float) -> None:
        """The world reports chain explosions here, so they can reach characters too."""
        if self.combat is not None:
            self.combat.on_area_damage(origin, amount, radius, impulse)

    def on_player_changed(self) -> None:
        """The player now controls a different character; everything else follows it."""
        self.camera.vision_zoom = 1.0
        self.hud.on_player_changed()
        if self.combat is not None:
            self.combat.markers.hide()
            self.combat.targets.clear()
            self.combat.targets.update_manual()
            self.combat.show_time_stop()
        self.notify(self.sentry.display_name)

    def _release_keys_on_focus_loss(self) -> None:
        win = getattr(application.base, "win", None)
        if win is None:
            return
        focused = win.getProperties().getForeground()
        if self._had_focus and not focused:
            self.release_inputs()
        self._had_focus = focused

    def update(self, dt: float | None = None) -> None:
        self._release_keys_on_focus_loss()
        if self.power_panel.visible:
            self.power_panel.update()
            return
        if self.team_panel.visible or self.settings_page.enabled or self.paused or self.at_title:
            return
        dt = float(time.dt if dt is None else dt)
        self.frame_seconds = max(0.0, dt)
        dt = max(0.0, min(dt, .05))
        self.elapsed += dt

        self.combat.targets.update_manual()
        self.combat.targets.update_auto(self.teams.state.auto_target_lock, self.frame_seconds)
        sentry = self.sentry
        sentry.enforce_flight()
        flying = sentry.flight.is_flying
        # A/D are lateral flight thrust; mouse and arrow keys still control the
        # camera heading while airborne.
        steering_axis = 0.0 if flying else self.input_manager.turn_axis()
        self.camera.update_control(dt, steering_axis, flying=flying)
        direction, vertical = self.input_manager.movement(flying=flying)
        if sentry.has_super_jump and held_keys[CONTROL_BINDINGS["flight_action"]]:
            vertical = max(vertical, 1.0)  # holding F through a super jump drives it on, as Space does
        steering_direction = direction if flying and direction.length() > 1e-5 else None
        # Flying forward means both: the key held, and the body really going that way (choose_pose reads the velocity).
        sentry.thrusting = bool(held_keys[CONTROL_BINDINGS["move_forward"]])
        sentry_position = SimVec3(sentry.x, sentry.y, sentry.z)
        altitude = self.planet.altitude(sentry_position)
        if (sentry.flight.phase in (FlightPhase.TAKEOFF, FlightPhase.CRUISE)
                and vertical < 0 and altitude <= 1.4):
            sentry.flight.phase = FlightPhase.LANDING
            sentry.flight.phase_time = 0.0
        boost_key = bool(held_keys[CONTROL_BINDINGS["accelerate"]])
        boost = self._boost_gate.allow(boost_key, dt, self.tuning.seconds("boost_duration_cs"),
                                       self.tuning.seconds("boost_cooldown_cs"))
        brake = bool(held_keys[CONTROL_BINDINGS["brake"]])
        # On the ground the boost key is the run key.
        sprint = not flying and boost_key
        ground_distance = max(0.0, altitude - .25)
        # A slow frame is taken in several short steps, so that physics behaves the same at any frame rate.
        # (A motion keeps its own clock in real seconds, and takes each frame as one step.)
        steps = 1 if sentry.motion is not None else max(1, min(MAX_PHYSICS_STEPS, ceil(dt / PHYSICS_STEP)))
        for _ in range(steps):
            sentry.simulate(dt / steps, direction, vertical, boost=boost, brake=brake, sprint=sprint,
                            ground_distance=ground_distance, steering_direction=steering_direction,
                            aimed=True)

        # World time stands still in a time stop. Chunks still stream around the player, the camera
        # keeps following them, and craters they make still appear.
        world_dt = 0.0 if self.combat.time_stopped else dt
        if self.combat.time_stopped:
            self.world._terrain_rebuild_wait -= dt
        self.world_manager.update(world_dt)
        self.camera.update(dt)
        self.environment.update(world_dt)
        self.teams.update(dt)
        self.combat.update(dt)
        self.visual_effects.update(dt)
        self.hud.update()
        self.debug_overlay.update(dt)
        if self.elapsed >= self._next_quiet_sweep:
            self._next_quiet_sweep = self.elapsed + QUIET_SWEEP_SECONDS
            quiet_static_entities()

    def input(self, key: str) -> None:
        normalized = normalize_key(key)
        if normalized.endswith(" hold"):
            return  # key repeat never re-triggers a press-only ability
        action = KEY_ACTIONS.get(normalized)

        if self.settings_page.enabled:
            if normalized == "escape" and self.settings_page.capturing is None:
                self.settings_page.close()
            else:
                self.settings_page.input(normalized)
            return
        if self.power_panel.visible:
            if normalized == "escape" or (action == "config_panel"
                                          and self.power_panel.editing is None):
                self.toggle_power_panel()
            else:
                self.power_panel.input(normalized)
            return
        if self.team_panel.visible:
            if normalized == "escape" or action == "team_manager":
                self.toggle_team_panel()
            else:
                self.team_panel.input(normalized)
            return

        if self.at_title:
            if normalized in ("enter", "return"):
                self.leave_title()
            return

        if action == "config_panel":
            self.toggle_power_panel()
        elif action == "team_manager":
            self.toggle_team_panel()
        elif action == "pause":
            self.toggle_pause()
        elif action == "fullscreen":
            self.toggle_fullscreen()
        elif normalized == f"{CONTROL_BINDINGS['team_status']} up":
            self.hud.set_status_visible(False)
        elif action == "team_status":
            self.hud.set_status_visible(True)
        elif self.paused:
            return
        elif normalized in ABILITY_SLOTS:
            if not self.combat.sequence_running:  # nothing interrupts a time-stop sequence
                self.sentry.powers.press(ABILITY_SLOTS[normalized])
        elif normalized in SLOT_RELEASES:
            self.sentry.powers.release(SLOT_RELEASES[normalized])
        elif normalized in ("scroll up", "scroll down"):
            # While a target is locked the wheel picks the target; the rest of the time it zooms.
            if self.combat.targets.manual is not None:
                self.combat.targets.cycle_manual(1 if normalized == "scroll up" else -1)
            else:
                self.camera.zoom_by(-ZOOM_STEP if normalized == "scroll up" else ZOOM_STEP)
        elif action == "target_lock":
            self.combat.targets.toggle_manual()
        elif normalized == AUTO_TARGET_LOCK_KEY:
            self.toggle_auto_target_lock()
        elif action == "flight_action":
            if not self.sentry.vitals.immobile:
                self.toggle_flight()
        elif normalized == f"{CONTROL_BINDINGS['rise']} up":
            self.sentry.cut_jump()
        elif normalized == CONTROL_BINDINGS["rise"]:
            if not self.sentry.vitals.immobile:
                self.sentry.start_jump(self.tuning.number("jump_strength"),
                                       self.tuning.fraction("super_jump_power_pct"))
        elif action == "camera_reset":
            self.camera.reset()

    def toggle_auto_target_lock(self) -> None:
        """Key 8 or the pause menu. Off stops the timer and leaves whatever is locked just as it is."""
        state = self.teams.state
        state.auto_target_lock = not state.auto_target_lock
        state.save()
        if state.auto_target_lock:
            self.combat.targets.update_auto(True, 0.0)  # first, so its own message does not replace this one
        self.notify(f"AUTO TARGET LOCK: {'ON' if state.auto_target_lock else 'OFF'}")

    def toggle_flight(self) -> None:
        """F. On the ground: take off, or for Soldier Boy a super jump. In the air: a dive and a ground slam."""
        sentry = self.sentry
        if sentry.recover_into_flight():
            return
        dive = sentry.powers.abilities["impact_dive"]
        if sentry.motion is not None or sentry.jump_height >= MIN_HEIGHT:
            dive.press()  # falling, it can only be this. Any other motion owns the body, and this does nothing
            return
        if sentry.has_super_jump and not sentry.keeps_own_height:
            sentry.super_launch(self.tuning.fraction("super_jump_power_pct"))
            return
        position = SimVec3(sentry.x, sentry.y, sentry.z)
        altitude = self.planet.altitude(position)
        if not sentry.flight_allowed and not sentry.flight.is_flying and not sentry.keeps_own_height:
            return
        if self.planet.is_ocean(position) and altitude < 0.0 and sentry.flight_allowed:
            up = self.planet.normal(position)
            velocity = sentry.flight.velocity
            radial = velocity.x * up.x + velocity.y * up.y + velocity.z * up.z
            sentry.flight.velocity = velocity + up * max(0.0, 16.0 - radial)
            sentry.flight.phase = FlightPhase.TAKEOFF
            sentry.flight.phase_time = 0.0
            self.notify("SURFACING")
        elif sentry.flight.phase is FlightPhase.GROUNDED and not sentry.keeps_own_height:
            # Flight already reads the shared camera yaw; do not reset the
            # user's view to the body heading while taking off.
            sentry.flight.toggle_flight(self.planet.normal(position))
        else:
            dive.press()

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.release_inputs()
        self._set_menu_mouse(self.paused)
        self.hud.set_atlas_visible(self.paused)
        self.hud.set_paused(self.paused)

    def set_quality(self, quality: str) -> None:
        preset = QUALITY_PRESETS.get(quality.lower())
        if preset is None:
            return
        self.settings = type(preset)(preset.quality, preset.render_distance,
                                     preset.civilian_count, preset.debris_lifetime,
                                     self.settings.day_length_seconds,
                                     self.settings.npc_density, self.settings.traffic_density,
                                     self.settings.npc_animation_quality,
                                     self.settings.vehicle_detail_quality,
                                     self.settings.ragdoll_quality, self.settings.resolution)
        self.world.set_quality(self.settings)
        self.environment.set_quality(self.settings.quality)
        self._apply_resolution()
        self.camera.apply_settings()
        save_settings(self.settings)

    def set_resolution(self, resolution: str) -> None:
        """A window size chosen on its own, which then stays whatever the quality preset."""
        self.settings = replace(self.settings, resolution=resolution)
        self._apply_resolution()
        save_settings(self.settings)

    def _apply_resolution(self) -> None:
        self._windowed_resolution = resolution_of(self.settings)
        if not self._is_fullscreen:
            window.size = self._windowed_resolution

    def update_population_settings(self, **values) -> None:
        """Apply the population tab without resetting unrelated graphics choices."""
        allowed = {"npc_density", "traffic_density", "npc_animation_quality",
                   "vehicle_detail_quality", "ragdoll_quality"}
        changes = {key: str(value).lower() for key, value in values.items()
                   if key in allowed}
        for key, value in tuple(changes.items()):
            valid = {"low", "medium", "high", "ultra"} if key.endswith("density") else {
                "low", "medium", "high"}
            if value not in valid:
                changes.pop(key)
        if not changes:
            return
        self.settings = replace(self.settings, **changes)
        self.world.settings = self.settings
        self.world.refresh_population()
        save_settings(self.settings)

    def toggle_fullscreen(self) -> None:
        if self._is_fullscreen:
            window.fullscreen = False
            window.size = self._windowed_resolution
            self._is_fullscreen = False
        else:
            self._windowed_resolution = resolution_of(self.settings)
            window.fullscreen = True
            self._is_fullscreen = True

    def notify(self, message: str, duration: float = 1.4) -> None:
        self._notification = message
        self._notification_until = self.elapsed + duration
