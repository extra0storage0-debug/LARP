"""Configuration package for NO LIMIT TO LARP."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from config.sentry_config import (
    CATEGORIES,
    PRESETS,
    SETTING_SPECS,
    SPECS_BY_KEY,
    SentrySettings,
    SettingSpec,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "settings.json"


@dataclass(slots=True)
class GraphicsSettings:
    quality: str = "low"
    render_distance: int = 10_000
    civilian_count: int = 8
    debris_lifetime: float = 7.0
    day_length_seconds: float = 720.0
    npc_density: str = "medium"
    traffic_density: str = "medium"
    npc_animation_quality: str = "medium"
    vehicle_detail_quality: str = "medium"
    ragdoll_quality: str = "medium"
    resolution: str = ""  # "1600x900", or empty for what the quality preset uses


QUALITY_PRESETS = {
    # Visibility covers the 10 km island even on Low; quality changes detail,
    # not whether distant districts exist.
    "low": GraphicsSettings("low", 10_000, 8, 7.0),
    "medium": GraphicsSettings("medium", 11_000, 14, 10.0),
    "high": GraphicsSettings("high", 12_000, 22, 14.0),
    "ultra": GraphicsSettings("ultra", 13_000, 30, 18.0),
}

QUALITY_RESOLUTIONS = {
    "low": (1600, 900),
    "medium": (1600, 900),
    "high": (1600, 900),
    "ultra": (1920, 1080),
}
RESOLUTIONS = ("1280x720", "1600x900", "1920x1080")


def resolution_of(settings: GraphicsSettings) -> tuple[int, int]:
    """The player's chosen window size, or the one their quality preset comes with."""
    if settings.resolution in RESOLUTIONS:
        width, height = settings.resolution.split("x")
        return int(width), int(height)
    return QUALITY_RESOLUTIONS.get(settings.quality, QUALITY_RESOLUTIONS["low"])


def load_settings() -> GraphicsSettings:
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return GraphicsSettings()
        preset = QUALITY_PRESETS.get(str(raw.get("quality", "low")).lower(), QUALITY_PRESETS["low"])

        def bounded_value(key: str, default, minimum, maximum, converter):
            value = raw.get(key, default)
            if isinstance(value, bool):
                return default
            try:
                value = converter(value)
            except (ValueError, TypeError, OverflowError):
                return default
            if isinstance(value, float) and not math.isfinite(value):
                return default
            return max(minimum, min(maximum, value))

        render_distance = bounded_value("render_distance", preset.render_distance,
                                        0, 13_000, int)
        # Older settings stored 360/620/900 m values that only worked with the
        # previous close-range chunk renderer. Upgrade those values to the
        # chosen visibility distance for the saved quality preset.
        if render_distance < 8_000:
            render_distance = preset.render_distance

        def choice(key: str, options: set[str], default: str) -> str:
            value = str(raw.get(key, default)).lower()
            return value if value in options else default

        density_options = {"low", "medium", "high", "ultra"}
        detail_options = {"low", "medium", "high"}
        return GraphicsSettings(
            quality=preset.quality,
            render_distance=render_distance,
            civilian_count=bounded_value("civilian_count", preset.civilian_count,
                                         4, 30, int),
            debris_lifetime=bounded_value("debris_lifetime", preset.debris_lifetime,
                                          3.0, 30.0, float),
            day_length_seconds=bounded_value("day_length_seconds", 720.0,
                                             120.0, 86400.0, float),
            npc_density=choice("npc_density", density_options, "medium"),
            traffic_density=choice("traffic_density", density_options, "medium"),
            npc_animation_quality=choice("npc_animation_quality", detail_options, "medium"),
            vehicle_detail_quality=choice("vehicle_detail_quality", detail_options, "medium"),
            ragdoll_quality=choice("ragdoll_quality", detail_options, "medium"),
            resolution=choice("resolution", set(RESOLUTIONS), ""),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return GraphicsSettings()


def save_settings(settings: GraphicsSettings) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = CONFIG_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    temporary_path.replace(CONFIG_PATH)

