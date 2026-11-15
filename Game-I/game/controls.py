"""Single source of truth for game control names and pressed-key axes."""

from __future__ import annotations


CONTROL_BINDINGS = {
    "move_forward": "w",
    "move_backward": "s",
    "move_left": "a",
    "move_right": "d",
    "rise": "space",
    "descend": "control",
    "flight_action": "f",
    "accelerate": "shift",
    "brake": "alt",
    "camera_left": "left arrow",
    "camera_right": "right arrow",
    "camera_up": "down arrow",
    "camera_down": "up arrow",
    "rise_alt": "home",
    "descend_alt": "end",
    "camera_reset": "c",
    "target_lock": "q",
    "team_manager": "m",
    "team_status": "tab",
    "config_panel": "p",
    "pause": "escape",
    "fullscreen": "k",
    "look": "mouse",
}

_DEFAULT_BINDINGS = dict(CONTROL_BINDINGS)
_HELD_ACTIONS = {"move_forward", "move_backward", "move_left", "move_right",
                 "rise", "descend", "accelerate", "brake", "look"}
# The ability keys are fixed for every character: key name to ability slot.
# E, R and both mouse buttons do nothing in play. Punch and kick answer to the key however the keyboard
# reports it: the main-row + is "=" (Shift is stripped), the numpad's is "+".
ABILITY_SLOTS = {"1": "1", "2": "2", "3": "3", "4": "4", "t": "t",
                 "+": "+", "=": "+", "-": "-", "_": "-"}
SLOT_RELEASES = {f"{key} up": slot for key, slot in ABILITY_SLOTS.items()}
ABILITY_KEYS = {"1", "2", "3", "4", "r", "t", "e", "q", "+", "=", "-", "_"}
AUTO_TARGET_LOCK_KEY = "8"
# Keys the menus and abilities depend on; never reassignable.
RESERVED_KEYS = {"p", "escape", "enter", AUTO_TARGET_LOCK_KEY, *ABILITY_KEYS}

KEY_ACTIONS = {
    value: action for action, value in CONTROL_BINDINGS.items()
    if action not in _HELD_ACTIONS
}


def binding(action: str) -> str:
    return CONTROL_BINDINGS.get(action, "")


def binding_conflict(action: str, key: str, overrides: dict[str, str] | None = None) -> str | None:
    """Name the action already using ``key``, or the reason it cannot be used."""
    key = normalize_key(key)
    if key in RESERVED_KEYS:
        return "reserved"
    table = {**CONTROL_BINDINGS, **(overrides or {})}
    for other, value in table.items():
        if other != action and value == key:
            return other
    return None


def apply_bindings(overrides: dict[str, str]) -> None:
    """Install player keybindings over the defaults; unknown actions are ignored."""
    CONTROL_BINDINGS.update(_DEFAULT_BINDINGS)
    for action, key in overrides.items():
        if action in CONTROL_BINDINGS:
            CONTROL_BINDINGS[action] = normalize_key(key)
    KEY_ACTIONS.clear()
    KEY_ACTIONS.update({value: action for action, value in CONTROL_BINDINGS.items()
                        if action not in _HELD_ACTIONS})


def movement_axes(held) -> tuple[float, float, float, float]:
    """Return forward, backward, left, and right movement axes from the bound keys."""
    return (float(bool(held.get(CONTROL_BINDINGS["move_forward"], 0))),
            float(bool(held.get(CONTROL_BINDINGS["move_backward"], 0))),
            float(bool(held.get(CONTROL_BINDINGS["move_left"], 0))),
            float(bool(held.get(CONTROL_BINDINGS["move_right"], 0))))


def signed_movement_axes(held) -> tuple[float, float]:
    """Return forward/back and right/left intent, cancelling opposing keys."""
    forward, backward, left, right = movement_axes(held)
    return forward - backward, right - left


def vertical_axis(held) -> float:
    """Rise/Home ascend and Descend/End descend; clamp opposing keys to neutral."""
    rise = bool(held.get(CONTROL_BINDINGS["rise"], 0)) or bool(held.get(CONTROL_BINDINGS["rise_alt"], 0))
    descend = (bool(held.get(CONTROL_BINDINGS["descend"], 0))
               or bool(held.get(CONTROL_BINDINGS["descend_alt"], 0)))
    return float(rise) - float(descend)


def normalize_key(key: str) -> str:
    normalized = key.strip().lower()
    if normalized in (".", "period"):
        return "period"
    if normalized in ("esc", "escape"):
        return "escape"
    return normalized


def key_axis(held, positive: str, negative: str) -> float:
    return float(bool(held.get(positive, 0))) - float(bool(held.get(negative, 0)))
