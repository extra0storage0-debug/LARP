"""The HUD: health, the current target, the character's six abilities, and Tab info."""

from math import ceil, sin
from time import perf_counter

from ursina import Button, Circle, Entity, Text, camera, color

from ui import theme

from movement.flight_physics import Vec3 as SimVec3

from characters.roster import KITS
from config.character_roster import TEAM_LABELS
from config.power_schema import ABILITIES, PASSIVES, SCHEMA, UNIVERSAL
from ui.enemy_team_ui import _DefaultShader
from ui.menus import PauseMenu

# In the bottom-left corner, clear of the player's body.
HELP = ("WASD move | Mouse look | {attacks}Space jump/rise | Ctrl descend\n"
        "Shift run/boost{flight} | Q lock target\n"
        "Wheel next target (zoom when unlocked) | 1-4 abilities | {time_stop}Tab info\n"
        "8 auto target lock | M switch character | P powers | C camera | Esc menu")
# Three either side of the player's body, which fills the middle of the bottom of the screen.
SLOT_POSITIONS = (-.37, -.27, -.17, .17, .27, .37)
TEXT_INTERVAL = .15
HELP_SECONDS = 15.0
_TARGET_TEXT = theme.ACCENT_SOFT
_LOCKED_TEXT = theme.ACCENT_BRIGHT
RIPPLE_SECONDS = .7
RIPPLE_SCALE = 3.4
PULSE_ALPHA = 9.0
PULSE_RATE = 2.2
_OK_TINT = theme.STEEL_SLOT
_ON_TINT = theme.ACCENT
_WAIT_TINT = theme.WAITING
_EMPTY_TINT = theme.STEEL_EMPTY
STATUS_NAMES = {"frozen": "FROZEN", "restrained": "RESTRAINED", "slowed": "SLOWED", "held": "HELD",
                "nullified": "NULLIFIED"}


class _Bar:
    def __init__(self, y: float, tint, width: float = .34) -> None:
        self.width = width
        self.back = Entity(parent=camera.ui, model="quad", origin=(-.5, 0), position=(-.72, y),
                           scale=(width, .014), z=.01, color=theme.BAR_BACK)
        self.fill = Entity(parent=camera.ui, model="quad", origin=(-.5, 0), position=(-.72, y),
                           scale=(width, .014), color=tint)
        self._shown = 1.0

    def set(self, fraction: float) -> None:
        fraction = max(0.0, min(1.0, fraction))
        if abs(fraction - self._shown) > .002:
            self._shown = fraction
            self.fill.scale_x = max(.0001, self.width * fraction)

    @property
    def entities(self):
        return (self.back, self.fill)


class _Slot:
    SIZE = (.092, .056)

    def __init__(self, x: float, y: float) -> None:
        self.box = Entity(parent=camera.ui, model="quad", position=(x, y), scale=self.SIZE, z=.01,
                          color=_OK_TINT)
        self.key = Text(parent=camera.ui, text="", position=(x - .04, y + .021), scale=.72,
                        origin=(-.5, .5), color=theme.TEXT)
        self.state = Text(parent=camera.ui, text="", position=(x + .04, y + .021), scale=.62,
                          origin=(.5, .5), color=color.white)
        self.name = Text(parent=camera.ui, text="", position=(x, y - .009), scale=.5,
                         origin=(0, 0), color=theme.TEXT_MUTED)
        self._last = (None, None)
        self.wanted = True

    def set_shown(self, shown: bool) -> None:
        self.wanted = shown
        for entity in self.entities:
            entity.enabled = shown

    def show(self, key: str, name: str) -> None:
        self.key.text = key
        self.name.text = name
        self.state.text = ""
        self._last = (None, None)

    def set_state(self, state: str, available: bool) -> None:
        if (state, available) == self._last:
            return
        self._last = (state, available)
        self.state.text = state
        if not available:
            self.box.color = _EMPTY_TINT
        elif state == "ON":
            self.box.color = _ON_TINT
        elif state:
            self.box.color = _WAIT_TINT
        else:
            self.box.color = _OK_TINT

    @property
    def entities(self):
        return (self.box, self.key, self.state, self.name)


# Slot boxes have room for about fifteen characters.
SHORT_NAMES = {"Time-Stop Brutal Heat Vision Execution": "Heat Execution",
               "Aerial Laser Execution + Clone Assault": "Clone Assault", "Void Transformation": "Void Form",
               "Void Nuclear Execution": "Void Nuke", "Nuclear Radiation Blast": "Radiation",
               "Time-Stop Radioactive Nuclear Execution": "Execution", "Grab and Throw": "Grab / Throw", "Energy Projection": "Energy Shots",
               "Golden Energy Shield": "Gold Shield", "Molecular Manipulation": "Molecular",
               "High-Speed Aerial Charge": "Aerial Charge", "High-Speed Flight Charge": "Flight Charge",
               "Kryptonian Vision": "Vision Modes", "Viltrumite Shockwave Punch": "Shockwave Punch",
               "Viltrumite Dive Bomb": "Dive Bomb", "Radioactive Chest Blast": "Chest Blast",
               "Maximum Radioactive Discharge": "Max Discharge",
               "Maximum Laser Overdrive": "Laser Overdrive", "Solar Overcharge": "Solar Charge",
               "Power Nullification": "Nullification", "Enhanced Senses / X-ray": "Senses / X-ray",
               "Superhuman Physical Combat": "Physical Combat",
               "Viltrumite Physical Combat": "Physical Combat",
               "Maximum Radioactive Discharge": "Max Discharge",
               "High-Speed Punch Attack": "Speed Punch", "Aerial Neck Grab + Laser Execution": "Laser Execution", "Time-Stop Nuclear Execution": "Nuke Execution",
               "Time-Stop Ground Execution": "Execution", "Golden Chest Beam": "Chest Beam", "Radioactive Chest Beam": "Chest Beam", "Massive Spherical Bomb Blast": "Massive Blast",
               "Time-Stop High-Speed Flying Punch": "Flying Punch", "Time-Stop Aerial Grab and Blast": "Grab + Blast",
               "Time-Stop Radioactive Execution": "Execution", "Summon Viltrumites and Invincible": "Squad",
               "Time-Stop Shockwave Punch": "Shock Punch", "Time-Stop Triple Impact Execution": "Triple Impact"}


def _short(name: str) -> str:
    return SHORT_NAMES.get(name, name)


class SentryHUD:
    def __init__(self, game):
        self.game = game
        # A soft panel keeps the readouts legible over bright cloud.
        self.readout_panel = Entity(parent=camera.ui, model="quad", position=(-.74, .475),
                                    origin=(-.5, .5), scale=(.62, .135), z=.02,
                                    color=theme.READOUT)
        self.status = Text(parent=camera.ui, text="", position=(-.72, .46), scale=1.0,
                           origin=(-.5, .5), color=color.white)
        self.health_bar = _Bar(.415, theme.ACCENT)
        self.numbers = Text(parent=camera.ui, text="", position=(-.37, .424), scale=.58,
                            origin=(-.5, .5), color=theme.TEXT_MUTED)
        self.details = Text(parent=camera.ui, text="", position=(-.72, .392), scale=.6,
                            origin=(-.5, .5), color=theme.TEXT_MUTED)
        self.target_panel = Entity(parent=camera.ui, model="quad", position=(0, .355), z=.02,
                                   scale=(.56, .032), color=theme.READOUT_DARK,
                                   enabled=False)
        self.target_text = Text(parent=camera.ui, text="", position=(0, .355), scale=.8,
                                origin=(0, 0), color=theme.ACCENT_SOFT)
        self.help = Text(parent=camera.ui, text="", position=(-.87, -.49), scale=.58,
                         origin=(-.5, -.5), color=theme.HELP_TEXT)
        self.info_panel = Entity(parent=camera.ui, model="quad", position=(0, .03), scale=(1.1, .8),
                                 color=theme.PANEL_SOFT, enabled=False, z=.03)
        self.team_status = Text(parent=camera.ui, text="", position=(-.52, .40), scale=.74,
                                origin=(-.5, .5), color=color.white, enabled=False)

        self.config_button = Button(
            parent=camera.ui,
            text="POWERS",
            scale=(0.11, 0.038),
            position=(0.78, 0.45),
            color=theme.STEEL_DARK_SOFT,
            highlight_color=theme.ACCENT,
            text_color=theme.TEXT,
        )
        self.config_button.on_click = self._on_config_button_clicked
        reticle_tint = color.rgb32(245, 248, 239)
        self.crosshair = [
            Entity(parent=camera.ui, model="quad", position=(-.010, 0), scale=(.012, .002), color=reticle_tint, unlit=True),
            Entity(parent=camera.ui, model="quad", position=(.010, 0), scale=(.012, .002), color=reticle_tint, unlit=True),
            Entity(parent=camera.ui, model="quad", position=(0, -.010), scale=(.002, .012), color=reticle_tint, unlit=True),
            Entity(parent=camera.ui, model="quad", position=(0, .010), scale=(.002, .012), color=reticle_tint, unlit=True),
            Entity(parent=camera.ui, model="quad", scale=.0035, color=reticle_tint, unlit=True),
        ]
        self.notification = Text(parent=camera.ui, text="", position=(0, -.27), scale=.82,
                                 origin=(0, 0), color=theme.TEXT)
        self.slot_row = [_Slot(x, -.36) for x in SLOT_POSITIONS]
        self.slots: dict[str, _Slot] = {}
        self._bound_slots: list = []
        self.vision_overlay = Entity(parent=camera.ui, model="quad", scale=(3, 2), z=.9,
                                     color=color.rgba32(0, 0, 0, 0), enabled=False)
        self.vision_label = Text(parent=camera.ui, text="", position=(0, .42), scale=.9,
                                 origin=(0, 0), color=color.white, enabled=False)
        self.countdown_panel = Entity(parent=camera.ui, model="quad", position=(0, .425), z=.02,
                                      scale=(.25, .05), color=theme.PANEL_SOFT,
                                      enabled=False)
        self.countdown = Text(parent=camera.ui, text="", position=(0, .425), scale=1.35,
                              origin=(0, 0), color=theme.TEXT)
        self.ripple = Entity(parent=camera.ui, model=Circle(64, mode="line", thickness=3), z=.8,
                             color=color.rgba32(190, 215, 255, 0), enabled=False)
        self._ripple_age = None
        self._pulse_tint = None
        self._shown_seconds = None
        with _DefaultShader():
            self.pause_menu = PauseMenu(game)
        self._text_timer = 0.0
        self._last_status = None
        self._help_until = 0.0

    def on_player_changed(self) -> None:
        character = self.game.sentry
        kit = character.kit
        self.help.text = HELP.format(attacks="+ punch | - kick | " if kit.can_fly else "",
                                     flight=" | F take off, or slam in the air" if kit.can_fly else " | F super jump, or slam in the air",
                                     time_stop="T stop time | " if "world_stop" in character.powers.abilities else "")
        self.slots = {}
        self._bound_slots = []
        cards = list(SCHEMA[kit.character_id])
        if "world_stop" in character.powers.abilities:
            cards.append(UNIVERSAL["world_stop"])
        for index, slot in enumerate(self.slot_row):
            slot.set_shown(index < len(cards))
        for slot, card in zip(self.slot_row, cards):
            key = card.binding.split(",")[0].replace(" and ", " ")
            slot.show(key, _short(card.name))
            self.slots[key.lower()] = slot
            self._bound_slots.append((character.powers.abilities[card.ability_id], slot))
        self.set_vision(None, "")
        self._text_timer = 0.0
        self._help_until = perf_counter() + HELP_SECONDS

    def set_vision(self, tint, label: str) -> None:
        if tint is None:
            self.vision_overlay.enabled = False
            self.vision_label.enabled = False
            return
        self.vision_overlay.color = color.rgba32(*tint)
        self.vision_overlay.enabled = True
        self.vision_label.text = label
        self.vision_label.enabled = True

    def set_countdown(self, seconds: float | None, tint=None) -> None:
        """The 30-second readout, and a slow breath in the tint so frozen time feels alive."""
        self.countdown_panel.enabled = seconds is not None
        if seconds is None:
            self.countdown.text = ""
            self._shown_seconds = None
            return
        whole = ceil(seconds)
        if whole != self._shown_seconds:  # rebuilding text is costly; it changes once a second
            self._shown_seconds = whole
            self.countdown.text = f"TIME STOP  {whole}"
        red, green, blue, alpha = tint
        self.vision_overlay.color = color.rgba32(red, green, blue,
                                                 int(alpha + PULSE_ALPHA * sin(seconds * PULSE_RATE)))

    def start_time_ripple(self) -> None:
        self._ripple_age = 0.0
        self.ripple.scale = .01
        self.ripple.enabled = True

    def _step_ripple(self) -> None:
        if self._ripple_age is None:
            return
        self._ripple_age += self.game.frame_seconds
        progress = self._ripple_age / RIPPLE_SECONDS
        if progress >= 1.0:
            self._ripple_age = None
            self.ripple.enabled = False
            return
        self.ripple.scale = max(.01, RIPPLE_SCALE * progress)
        self.ripple.color = color.rgba32(190, 215, 255, int(200 * (1.0 - progress)))

    def set_status_visible(self, visible: bool) -> None:
        self.team_status.enabled = visible
        self.info_panel.enabled = visible
        if visible:
            self.team_status.text = self._status_text()

    def _status_text(self) -> str:
        """Tab: this character's abilities and the three rosters."""
        game = self.game
        kit = game.sentry.kit
        character_id = kit.character_id
        lines = [f"{kit.display}   |   {'CAN FLY' if kit.can_fly else 'GROUND-BOUND: CANNOT FLY'}",
                 kit.description, ""]
        lines.append("ABILITIES:")
        lines.extend(f"   {ability.binding:<26} {ability.name}" for ability in SCHEMA[character_id])
        if kit.can_fly:
            lines.append(f"   {'T':<26} Time Stop (30 seconds)")
        lines.append("PASSIVE: " + ", ".join(PASSIVES[character_id].names))
        lines.append("Q locks a target and the wheel changes it. E, R and the mouse buttons do nothing. Strength, stamina "
                     "and energy are unlimited.")
        lines.append("")
        state = game.teams.state
        for team, label in TEAM_LABELS.items():
            members = [KITS[member].display for member in state.members(team)]
            lines.append(f"{label}: {', '.join(members) if members else '-'}")
        return "\n".join(lines)

    def _status_line(self, vitals) -> str:
        parts = [name for status, name in STATUS_NAMES.items() if vitals.has(status)]
        if vitals.downed:
            parts.insert(0, f"DOWN {vitals.downed_for:.0f}s")
        return "  ".join(parts)

    def update(self) -> None:
        self._step_ripple()
        sentry = self.game.sentry
        vitals = sentry.vitals
        self.health_bar.set(vitals.health / max(1.0, vitals.max_health))
        self.notification.text = (self.game._notification
                                  if self.game.elapsed < self.game._notification_until else "")
        # Text rebuilds are the costly part of a HUD, so these run a few times a second.
        now = perf_counter()
        if now < self._text_timer:
            return
        self._text_timer = now + TEXT_INTERVAL
        self.help.enabled = now < self._help_until  # the keys stay on the pause menu; play keeps its screen
        team = TEAM_LABELS[self.game.teams.state.team_of(sentry.kit.character_id)]
        status = f"{sentry.kit.display}   |   {team}   |   {sentry.flight_status}"
        extra = self._status_line(vitals)
        if extra:
            status += f"   |   {extra}"
        self.status.text = status
        self.numbers.text = f"HP {vitals.health:.0f}/{vitals.max_health:.0f}"
        line = self._target_line(sentry)
        self.target_text.text = line
        self.target_text.color = _LOCKED_TEXT if line.startswith("LOCKED") else _TARGET_TEXT
        self.target_panel.enabled = bool(line)
        tuning = self.game.tuning
        parts = []
        if sentry.flight.is_flying and tuning.flag("show_flight_speed"):
            parts.append(f"{sentry.flight.speed_kmh:.0f} km/h")
        if sentry.flight.is_flying and tuning.flag("show_altitude"):
            parts.append(f"ALT {max(0.0, float(sentry.y)):,.0f} m")
        laser = sentry.powers.abilities.get("laser_vision")
        if laser is not None:
            parts.append(f"LASER {laser.mode}")
        squad = sentry.powers.abilities.get("squad_summon")
        if squad is not None and squad.active:
            parts.append(squad.status_line())
        threat = self.game.combat.nearest_threat(sentry)
        if threat is not None:
            parts.append(f"HEARD: {threat[0]} {threat[1]:.0f} m")
        self.details.text = "  |  ".join(parts)
        for ability, slot in self._bound_slots:
            slot.set_state(ability.hud_state(), True)

    def _target_line(self, sentry) -> str:
        combat = self.game.combat
        manual = combat.targets.manual
        if manual is not None:
            brain = getattr(manual, "brain", None)
            vitals = getattr(manual, "vitals", None)
            health = (vitals.health, vitals.max_health) if vitals else (brain.health, brain.maximum_health)
            metres = (combat.targets.point_of(manual) - SimVec3(sentry.x, sentry.y, sentry.z)).length()
            return (f"LOCKED: {manual.display_name}   {health[0]:.0f}/{health[1]:.0f} HP   "
                    f"{metres:,.0f} m")
        if not combat.targets.enabled:
            return "AUTO-TARGET OFF"
        target = combat.shown_target
        if target is None:
            return ""
        vitals = target.vitals
        dx, dy, dz = target.x - sentry.x, target.y - sentry.y, target.z - sentry.z
        return (f"TARGET: {target.display_name}   {vitals.health:.0f}/{vitals.max_health:.0f} HP   "
                f"{(dx * dx + dy * dy + dz * dz) ** .5:,.0f} m")

    def _on_config_button_clicked(self) -> None:
        self.game.toggle_power_panel()

    def set_paused(self, paused: bool) -> None:
        self.pause_menu.set_visible(paused)

    def set_atlas_visible(self, visible: bool) -> None:
        """Keep gameplay HUD text from competing with a full-screen menu."""
        for entity in (self.readout_panel, self.status, self.numbers, self.details, self.help,
                       self.target_text, self.target_panel, self.config_button, self.notification,
                       self.countdown,
                       *self.crosshair,
                       *self.health_bar.entities):
            entity.enabled = not visible
        for slot in self.slot_row:
            for entity in slot.entities:
                entity.enabled = slot.wanted and not visible


__all__ = ["ABILITIES", "SentryHUD"]
