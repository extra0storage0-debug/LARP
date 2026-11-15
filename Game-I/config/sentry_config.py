"""Simple and centralized configuration system for gameplay settings.

Stores integer gameplay settings with direct file persistence to
config/sentry_settings.json, validation, and real-time application.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from uuid import uuid4
from typing import Any, Callable, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
SETTINGS_FILE = CONFIG_DIR / "sentry_settings.json"
logger = logging.getLogger(__name__)


# The simple integer movement settings
SIMPLE_SETTINGS: List[Tuple[str, str, int]] = [
    ("flight_speed", "Flight Speed", 100),
    ("flight_boost_speed", "Flight Boost Speed", 500),
    ("ground_speed", "Ground Speed", 50),
]

DEFAULT_SETTINGS: Dict[str, int] = {key: default for key, _, default in SIMPLE_SETTINGS}

# Bidirectional alias mapping for existing systems and tests
ALIASES: Dict[str, str] = {
    "normal_flight_speed": "flight_speed",
    "max_flight_speed": "flight_speed",
    "flight_acceleration": "flight_speed",
    "max_boost_speed": "flight_boost_speed",
    "flight_boost_multiplier": "flight_boost_speed",
    "ground_running_speed": "ground_speed",
    "max_running_speed": "ground_speed",
}


def _whole_number(value: Any) -> int:
    """Parse to an integer, keeping every digit of a whole-number string."""
    if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        return int(value.strip())
    return int(round(float(value)))


@dataclass(slots=True)
class SettingSpec:
    key: str
    name: str
    category: str
    value_type: type
    default_value: float | int
    min_value: float | int
    max_value: float | int
    unit: str
    step: float | int
    description: str = ""

    def clamp(self, value: Any) -> float | int:
        try:
            val = int(round(float(value)))
        except (ValueError, TypeError):
            val = int(self.default_value)
        return max(int(self.min_value), val)


SETTING_SPECS: List[SettingSpec] = [
    SettingSpec(k, name, "general", int, default, 1, 999999, "", 10)
    for k, name, default in SIMPLE_SETTINGS
]
SPECS_BY_KEY: Dict[str, SettingSpec] = {s.key: s for s in SETTING_SPECS}
CATEGORIES = [("general", "General")]
PRESETS: Dict[str, Dict[str, Any]] = {"default": dict(DEFAULT_SETTINGS)}


class SentrySettings:
    """Manages gameplay settings with JSON persistence and live listeners."""

    def __init__(self, config_path: Optional[Path | str] = None) -> None:
        self.config_path = Path(config_path) if config_path else SETTINGS_FILE
        self._values: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._listeners: List[Callable[[], None]] = []
        self.load()

    def __contains__(self, key: str) -> bool:
        return key in self._values or key in ALIASES

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._values:
            return self._values[key]
        if key in ALIASES:
            target = ALIASES[key]
            if target in self._values:
                return self._values[target]
        if default is not None:
            return default
        return DEFAULT_SETTINGS.get(key, 0)

    def set(self, key: str, value: Any) -> None:
        try:
            if key in DEFAULT_SETTINGS or (key in ALIASES and ALIASES[key] in DEFAULT_SETTINGS and not isinstance(value, float)):
                # Whole numbers skip float() so large entries keep every digit.
                stored_val = max(1, value if isinstance(value, int) else _whole_number(value))
            elif isinstance(value, float):
                stored_val = max(0.0, float(value))
            elif isinstance(value, int):
                stored_val = max(0, int(value))
            elif isinstance(value, str):
                if "." in value:
                    stored_val = max(1, _whole_number(value)) if key in DEFAULT_SETTINGS else max(0.0, float(value))
                else:
                    stored_val = max(0, int(value))
            else:
                stored_val = value
        except (ValueError, TypeError):
            stored_val = DEFAULT_SETTINGS.get(key, 100)

        self._values[key] = stored_val
        if key in ALIASES:
            target = ALIASES[key]
            try:
                self._values[target] = int(round(float(stored_val)))
            except (ValueError, TypeError):
                self._values[target] = stored_val
        elif key in DEFAULT_SETTINGS:
            for alias_k, target_k in ALIASES.items():
                if target_k == key:
                    self._values[alias_k] = stored_val

        self._notify_listeners()

    def reset(self) -> None:
        self._values = dict(DEFAULT_SETTINGS)
        for alias_k, target_k in ALIASES.items():
            if target_k in DEFAULT_SETTINGS:
                self._values[alias_k] = DEFAULT_SETTINGS[target_k]
        self._notify_listeners()

    def reset_category(self, category: str) -> None:
        self.reset()

    def reset_all(self) -> None:
        self.reset()

    def get_category_settings(self, category: str) -> List[SettingSpec]:
        return SETTING_SPECS

    def apply_preset(self, name: str) -> None:
        self.reset()

    def current_preset(self) -> str:
        return "custom"

    def add_listener(self, callback: Callable[[], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                logger.exception("Game settings listener %r failed", cb)

    def save(self) -> bool:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            # Save only the clean settings as integers; old power values drop out
            clean_data = {
                key: int(self.get(key, default))
                for key, _, default in SIMPLE_SETTINGS
            }
            tmp_path = self.config_path.with_name(
                f".{self.config_path.name}.{uuid4().hex}.tmp"
            )
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(clean_data, f, indent=2)
            try:
                try:
                    tmp_path.replace(self.config_path)
                except PermissionError:
                    # Cloud-sync providers can temporarily deny replacing a file
                    # even when normal writes are allowed. Fall back to a direct
                    # write so Apply/Reset still persists settings on those paths.
                    logger.warning("Atomic settings replacement was denied for %s; "
                                   "falling back to a direct write", self.config_path)
                    with self.config_path.open("w", encoding="utf-8") as f:
                        json.dump(clean_data, f, indent=2)
            finally:
                tmp_path.unlink(missing_ok=True)
            return True
        except Exception:
            logger.exception("Failed to save game settings to %s", self.config_path)
            return False

    def load(self) -> bool:
        if not self.config_path.exists():
            self.save()
            return False

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)

            if not isinstance(raw, dict):
                raise ValueError("Root JSON is not an object")

            # Handle format if nested inside "settings" or top-level dict
            data = raw.get("settings", raw) if "settings" in raw and isinstance(raw["settings"], dict) else raw

            for key, _, default in SIMPLE_SETTINGS:
                val = data.get(key)
                if val is None and key in ALIASES:
                    val = data.get(ALIASES[key])
                if val is not None:
                    try:
                        self._values[key] = max(1, val if isinstance(val, int) else _whole_number(val))
                    except (ValueError, TypeError, OverflowError):
                        self._values[key] = default
                else:
                    self._values[key] = default

            # Populate aliases
            for alias_k, target_k in ALIASES.items():
                if target_k in self._values:
                    self._values[alias_k] = self._values[target_k]

            return True
        except Exception as err:
            logger.warning("Failed to load game settings from %s (%s); using defaults",
                           self.config_path, err)
            self.reset()
            return False
