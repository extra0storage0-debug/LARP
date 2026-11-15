"""The two general settings profiles: the player's controls, and shared AI movement.

Every setting is an exact integer (or a toggle or key name) in one table, so the
panel, persistence and tests all share a single definition. Fractional engine
values are stored in whole units such as percent, centimetres or centiseconds,
which is what lets the original camera defaults (9.5 m, for example) stay exact.

``derives`` feeds the keys existing game code already reads through cfg.get(), so
a setting reaches its system without a second lookup path. Per-character choices
live in config/character_roster.py.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from game.controls import ABILITY_KEYS

logger = logging.getLogger(__name__)

PROFILE_FILE = Path(__file__).resolve().parent / "sentry_profiles.json"
MAX_INPUT_DIGITS = 18  # exact in JSON; beyond this the physics' floats lose meaning

PLAYER = "my_sentry"
ENEMY = "common_enemies"
PROFILE_LABELS = {PLAYER: "PLAYER", ENEMY: "AI CHARACTERS"}

LIVE, RESPAWN = "live", "respawn"


@dataclass(frozen=True, slots=True)
class Setting:
    key: str
    label: str
    category: str
    default: int | str
    kind: str = "int"               # int, toggle or key
    minimum: int = 0
    applies: str = LIVE             # respawn: takes effect on the next battle (Enter)
    derives: tuple[tuple[str, float], ...] = ()  # (legacy cfg key, multiplier)
    # A value the shared 8-setting file owns for the player; see ProfileStore.
    simple: bool = False
    # Only for hard engine limits, such as a projection that breaks at 180 degrees.
    maximum: int | None = None


def _int(key, label, category, default, *derives, minimum=0, maximum=None, applies=LIVE,
         simple=False):
    return Setting(key, label, category, default, "int", minimum, applies, tuple(derives),
                   simple, maximum)


def _toggle(key, label, category, default=1):
    return Setting(key, label, category, int(default), "toggle")


def _key(key, label, default):
    return Setting(key, label, "input", default, "key")


CATEGORIES = (("camera", "Camera & Sensitivity"), ("movement", "Movement & Controls"),
              ("flight", "Flight Advanced"), ("ai", "AI Behaviour"),
              ("visual", "Visual & Audio"), ("debug", "Gameplay & Debug"),
              ("input", "Input & Controls"))


def _movement() -> list[Setting]:
    c = "movement"
    return [
        _int("walking_pace", "Walking Speed, W alone (m/s)", c, 3, minimum=1, simple=True),
        _int("ground_speed", "Base Ground Speed (m/s)", c, 50, minimum=1, simple=True),
        _int("running_speed_pct", "Running Speed, with Shift (% of base)", c, 150),
        _int("ground_acceleration_pct", "Ground Acceleration (%)", c, 100),
        _int("ground_deceleration", "Ground Deceleration", c, 9, ("deceleration", 1.0)),
        _int("turning_speed", "Turning Speed (deg/s)", c, 300, ("turning_speed", 1.0)),
        _int("movement_responsiveness_pct", "Movement Responsiveness (%)", c, 100),
        _int("flight_responsiveness_pct", "Flight Responsiveness (%)", c, 100),
        _int("air_turning_speed", "Air Turning Speed (deg/s)", c, 125,
             ("flight_turn_speed", 1.0)),
        _int("vertical_movement_speed", "Vertical Movement Speed", c, 25,
             ("vertical_ascent_speed", 1.0)),
        _int("boost_duration_cs", "Boost Duration (cs, 0=unlimited)", c, 0),
        _int("boost_cooldown_cs", "Boost Cooldown (cs)", c, 0),
    ]


def _flight() -> list[Setting]:
    c = "flight"
    return [
        _int("flight_speed", "Maximum Flight Speed (m/s)", c, 100, minimum=1, simple=True),
        _int("flight_boost_speed", "Boost Flight Speed (m/s)", c, 500, minimum=1, simple=True),
        _int("flight_acceleration_pct", "Flight Acceleration (%)", c, 100),
        _int("flight_deceleration_pct", "Flight Coasting Hold (%)", c, 70,
             ("flight_inertia", .01)),
        _int("horizontal_speed_pct", "Horizontal Speed (% of max)", c, 100),
        _int("vertical_speed_pct", "Vertical Speed (%)", c, 100),
        _int("flight_turning_pct", "Flight Turning Sensitivity (%)", c, 100),
        _int("flight_stability_pct", "Flight Stability (%)", c, 100),
        _int("air_braking", "Air Braking", c, 100, ("air_braking_strength", 1.0)),
        _int("boost_multiplier_pct", "Boost Multiplier (%)", c, 100, minimum=1),
        _int("takeoff_speed_dm", "Takeoff Speed (dm/s)", c, 75),
        _int("landing_speed", "Landing Speed (m/s)", c, 24, ("descent_speed", 1.0)),
    ]


_CAMERA = "camera"
PLAYER_ONLY: list[Setting] = [
    # Original values from CameraManager and movement.camera_controls.
    _int("mouse_sensitivity_pct", "Mouse Sensitivity (%)", _CAMERA, 100),
    _int("camera_horizontal_pct", "Horizontal Sensitivity (%)", _CAMERA, 100),
    _int("camera_vertical_pct", "Vertical Sensitivity (%)", _CAMERA, 100),
    _int("camera_rotation_speed", "Camera Rotation Speed (deg/s)", _CAMERA, 90),
    _int("camera_smoothing", "Camera Follow Rate (higher=tighter)", _CAMERA, 12, minimum=1),
    _int("camera_follow_distance_cm", "Follow Distance (cm)", _CAMERA, 950),
    _int("camera_follow_height_cm", "Follow Height (cm)", _CAMERA, 355),
    _int("camera_frame_position_pct", "Player Height on Screen (% down)", _CAMERA, 77),
    _int("camera_fov", "Field of View (deg)", _CAMERA, 82, minimum=1, maximum=179),
    _int("camera_zoom_speed_cs", "Zoom Speed (0.01/s)", _CAMERA, 400),
    _int("flight_camera_pct", "Flight Camera Sensitivity (%)", _CAMERA, 100),
    _int("ground_camera_pct", "Ground Camera Sensitivity (%)", _CAMERA, 100),
    # The original camera has no pitch clamp, so "no limit" is the true default.
    _int("camera_pitch_min", "Pitch Limit Low (deg)", _CAMERA, -999999, minimum=-999999),
    _int("camera_pitch_max", "Pitch Limit High (deg)", _CAMERA, 999999, minimum=-999999),
    _int("camera_reset_speed_pct", "Camera Reset Speed (%)", _CAMERA, 100, minimum=1),

    _int("jump_strength", "Jump Strength (0=no jump)", "movement", 7),
    _int("super_jump_power_pct", "Soldier Boy Super Jump Power (%)", "movement", 100, minimum=1),

    _int("motion_blur_pct", "Motion Blur Intensity (%)", "visual", 0),
    _int("flight_trail_pct", "Flight Trail Intensity (%)", "visual", 0),
    _int("cape_quality_pct", "Cape Physics Quality (%)", "visual", 100),
    _int("animation_speed_pct", "Character Animation Speed (%)", "visual", 100),
    _int("explosion_sound_pct", "Explosion Volume (%)", "visual", 100),
    _int("destruction_camera_shake_pct", "Camera Shake (%)", "visual", 100),

    _toggle("show_enemy_names", "Show Character Names", "debug"),
    _toggle("show_fps", "Show FPS", "debug", 0),
    _toggle("show_flight_speed", "Show Flight Speed", "debug"),
    _toggle("show_altitude", "Show Current Altitude", "debug"),
    _toggle("show_collision_info", "Show Collision Information", "debug", 0),
    _toggle("show_debug_info", "Show Debug Information", "debug", 0),

    _toggle("invert_mouse_y", "Invert Vertical Mouse", "input", 0),
    _int("mouse_smoothing_pct", "Mouse Smoothing (%)", "input", 0),
    _key("key_move_forward", "Move Forward", "w"),
    _key("key_move_backward", "Move Backward", "s"),
    _key("key_move_left", "Move Left", "a"),
    _key("key_move_right", "Move Right", "d"),
    _key("key_rise", "Flight: Rise", "space"),
    _key("key_descend", "Flight: Descend", "control"),
    _key("key_flight_action", "Flight: Take Off / Land", "f"),
    _key("key_accelerate", "Flight: Boost", "shift"),
    _key("key_brake", "Flight: Brake", "alt"),
    _key("key_team_manager", "Team & Character Manager", "m"),
    _key("key_team_status", "Team Status", "tab"),
    _key("key_camera_reset", "Camera Reset", "c"),
]

ENEMY_ONLY: list[Setting] = [
    _int("detection_sensitivity_pct", "Detection Sensitivity (%)", "ai", 100),
    _int("detection_range", "Target Detection Range (m)", "ai", 20000),
    _int("reaction_speed_pct", "Reaction Speed (%)", "ai", 100, minimum=1),
    _int("decision_frequency_pct", "Decision Frequency (%)", "ai", 100, minimum=1),
    _int("pursuit_aggression_pct", "Pursuit Aggression (%)", "ai", 100, minimum=1),
    _int("flight_pursuit_pct", "Flight Pursuit Sensitivity (%)", "ai", 100),
    _int("team_coordination_pct", "Team Coordination (%)", "ai", 100),
    _int("flanking_frequency_pct", "Flanking Frequency (%)", "ai", 100),
    _int("target_prediction_pct", "Target Prediction Accuracy (%)", "ai", 100),
    _int("target_switching_pct", "Role Switching Speed (%)", "ai", 100, minimum=1),
    _int("reaction_time_pct", "Reaction Time (%)", "ai", 100),
    _toggle("ai_uses_powers", "AI Characters Use Powers", "ai"),
    _int("ai_damage_pct", "AI Damage (%)", "ai", 35),

    _int("cape_quality_pct", "Cape Animation Quality (%)", "visual", 100),
    _int("animation_speed_pct", "Character Animation Speed (%)", "visual", 100),
]


def _dedupe(settings: Iterable[Setting]) -> dict[str, Setting]:
    table: dict[str, Setting] = {}
    for setting in settings:
        if setting.key in table:
            raise ValueError(f"Duplicate setting key {setting.key}")
        table[setting.key] = setting
    return table


PLAYER_SETTINGS = _dedupe((*_movement(), *_flight(), *PLAYER_ONLY))
ENEMY_SETTINGS = _dedupe(replace(setting, simple=False) for setting in
                         (*_movement(), *_flight(), *ENEMY_ONLY))
SETTINGS = {PLAYER: PLAYER_SETTINGS, ENEMY: ENEMY_SETTINGS}


def coerce(setting: Setting, raw: Any):
    """Return the exact value to store, or raise ValueError; nothing is clamped or rounded."""
    if setting.kind == "key":
        text = str(raw).strip().lower()
        if not text:
            raise ValueError("A key name is required")
        return text
    if isinstance(raw, str):
        # int() keeps every digit; float() would silently round large entries.
        text = raw.strip()
        if not text.lstrip("+-").isdigit():
            raise ValueError(f"'{text}' is not a whole number")
        value = int(text)
    elif isinstance(raw, int):
        value = int(raw)
    elif isinstance(raw, float) and raw.is_integer():
        value = int(raw)
    else:
        raise ValueError(f"'{raw}' is not a whole number")
    if setting.kind == "toggle":
        return 1 if value else 0
    if abs(value) >= 10 ** MAX_INPUT_DIGITS:
        raise ValueError(f"{MAX_INPUT_DIGITS} digits maximum")
    if value < setting.minimum:
        raise ValueError(f"Minimum is {setting.minimum}")
    if setting.maximum is not None and value > setting.maximum:
        raise ValueError(f"Maximum is {setting.maximum}")
    return value


class ProfileView:
    """Read one profile as engine units, plus the keys existing code asks for."""

    def __init__(self, store: "ProfileStore", profile: str) -> None:
        self._store = store
        self.profile = profile

    def value(self, key: str):
        return self._store.get(self.profile, key)

    def has(self, key: str) -> bool:
        return key in SETTINGS[self.profile]

    def number(self, key: str, default: float = 0.0) -> float:
        return float(self.value(key)) if self.has(key) else float(default)

    def fraction(self, key: str, default: float = 1.0) -> float:
        """A percent setting as a multiplier; absent settings keep their default."""
        return float(self.value(key)) / 100.0 if self.has(key) else float(default)

    def seconds(self, key: str, default: float = 0.0) -> float:
        return float(self.value(key)) / 100.0 if self.has(key) else float(default)

    def metres(self, key: str) -> float:
        """A centimetre setting in metres; division keeps 950 cm at exactly 9.5."""
        return float(self.value(key)) / 100.0

    def flag(self, key: str, default: bool = True) -> bool:
        return bool(self.value(key)) if self.has(key) else bool(default)

    def derived(self) -> dict[str, float]:
        """Legacy cfg.get() keys computed from this profile's settings."""
        values: dict[str, float] = {}
        for setting in SETTINGS[self.profile].values():
            for legacy_key, multiplier in setting.derives:
                # Rounding drops binary noise, so 70% is exactly the original .70.
                values[legacy_key] = round(float(self.value(setting.key)) * multiplier, 9)
        return values


class ProfileStore:
    """Exact-valued storage for both profiles, saved across game restarts.

    The player's eight original settings stay in config/sentry_settings.json so
    existing saves and tools keep working; everything else lives beside them in
    config/sentry_profiles.json. Saving only ever happens on request.
    """

    def __init__(self, simple, path: Path | str | None = None) -> None:
        self.simple = simple
        override = os.environ.get("SENTRY_PROFILE_FILE")
        self.path = Path(path) if path else (Path(override) if override else PROFILE_FILE)
        self._values = {profile: {} for profile in SETTINGS}
        self._listeners: list = []
        self.load()
        self.views = {profile: ProfileView(self, profile) for profile in SETTINGS}

    def view(self, profile: str) -> ProfileView:
        return self.views[profile]

    def add_listener(self, callback) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def _notify(self) -> None:
        for callback in tuple(self._listeners):
            try:
                callback()
            except Exception:
                logger.exception("Profile listener %r failed", callback)

    def get(self, profile: str, key: str):
        setting = SETTINGS[profile][key]
        if setting.simple:
            return self.simple.get(key, setting.default)
        return self._values[profile].get(key, setting.default)

    def set(self, profile: str, key: str, raw, *, notify: bool = True) -> None:
        setting = SETTINGS[profile][key]
        value = coerce(setting, raw)
        if setting.simple:
            self.simple.set(key, value)
        else:
            self._values[profile][key] = value
        if notify:
            self._notify()

    def reset(self, profile: str, category: str | None = None) -> None:
        for key, setting in SETTINGS[profile].items():
            if category is not None and setting.category != category:
                continue
            if setting.simple:
                self.simple.set(key, setting.default)
            else:
                self._values[profile].pop(key, None)
        self._notify()

    def load(self) -> bool:
        if not self.path.exists():
            return False
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            profiles = raw["profiles"]
            if not isinstance(profiles, dict):
                raise ValueError("'profiles' is not an object")
        except (OSError, ValueError, KeyError, TypeError) as error:
            logger.warning("Ignoring unreadable profile file %s (%s)", self.path, error)
            return False
        for profile, table in SETTINGS.items():
            stored = profiles.get(profile, {})
            if not isinstance(stored, dict):
                continue
            for key, value in stored.items():
                setting = table.get(key)
                if setting is None or setting.simple:
                    continue
                if setting.kind == "key" and str(value).strip().lower() in ABILITY_KEYS:
                    logger.warning("Dropping old key binding %s=%s: that key is now an ability",
                                   key, value)
                    continue
                try:
                    self._values[profile][key] = coerce(setting, value)
                except (ValueError, TypeError, OverflowError):
                    logger.warning("Ignoring invalid value for %s.%s", profile, key)
        return True

    def save(self) -> bool:
        """Write both profiles independently; unchanged settings keep following defaults."""
        data = {"version": 1, "profiles": {profile: dict(self._values[profile])
                                           for profile in SETTINGS}}
        ok = bool(self.simple.save())
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
            try:
                temporary.replace(self.path)
            except PermissionError:
                # Same cloud-sync fallback as SentrySettings.save.
                self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            logger.exception("Failed to save profiles to %s", self.path)
            ok = False
        finally:
            temporary.unlink(missing_ok=True)
        return ok
