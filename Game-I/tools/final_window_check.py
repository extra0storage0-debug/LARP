"""Play the finished game in a real window: keys, powers, swaps, menus, screenshots, timings.

Your saves are never touched: everything goes to a temporary folder.
Run from the project folder: .venv\\Scripts\\python.exe tools\\final_window_check.py [low|medium|high]
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
_saves = Path(tempfile.mkdtemp(prefix="sentry_final_"))
os.environ["SENTRY_DESTRUCTION_SAVE"] = str(_saves / "island_destruction.json")
os.environ["SENTRY_PROFILE_FILE"] = str(_saves / "profiles.json")
os.environ["SENTRY_ROSTER_FILE"] = str(_saves / "roster.json")
os.environ["SENTRY_POWER_FILE"] = str(_saves / "powers.json")

import main  # noqa: E402
import game.game_manager as manager  # noqa: E402
from config.power_schema import SCHEMA  # noqa: E402
from movement.flight_physics import FlightPhase, Vec3 as SimVec3  # noqa: E402
from panda3d.core import Filename  # noqa: E402
from powers.aiming import trace  # noqa: E402
from ursina import application, camera, held_keys, mouse, scene, window  # noqa: E402

manager.save_settings = lambda _settings: None
OUTPUT = ROOT / "screenshots" / "powers"
SAMPLE_SECONDS = float(os.environ.get("SENTRY_BENCH_SECONDS", "8"))
FLYERS = ("WHITE", "BLACK", "YELLOW", "GREEN")


class _Counters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def memory_mb() -> float:
    counters = _Counters()
    counters.cb = ctypes.sizeof(counters)
    psapi, kernel = ctypes.WinDLL("psapi"), ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD)
    psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return round(counters.WorkingSetSize / (1024.0 * 1024.0), 1)


class Check:
    def __init__(self, game, app, quality: str) -> None:
        self.game, self.app, self.quality = game, app, quality
        self.results: dict = {"quality": quality, "checks": {}, "fps": {}}

    def tick(self) -> None:
        # Anyone touching the real mouse during a run would swing the camera and spoil the aim.
        if mouse.locked:
            mouse.locked = False
        self.game.update()
        self.app.step()

    def frames(self, count: int) -> None:
        for _ in range(count):
            self.tick()

    def run_for(self, seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            self.tick()

    def sample(self, name: str, length: float = SAMPLE_SECONDS, during=None) -> None:
        times, end = [], time.perf_counter() + length
        previous = time.perf_counter()
        next_action = previous
        while time.perf_counter() < end:
            if during is not None and time.perf_counter() >= next_action:
                next_action = time.perf_counter() + during()
            self.tick()
            now = time.perf_counter()
            times.append(now - previous)
            previous = now
        ordered = sorted(times, reverse=True)
        low = ordered[:max(1, len(ordered) // 100)]
        self.results["fps"][name] = {
            "fps": round(len(times) / sum(times), 1), "low_1pct": round(len(low) / sum(low), 1),
            "worst_ms": round(ordered[0] * 1000.0, 1), "over_50ms": sum(t > .05 for t in times),
            "memory_mb": memory_mb(), "entities": len(scene.entities)}

    def shot(self, name: str) -> None:
        self.frames(2)
        OUTPUT.mkdir(parents=True, exist_ok=True)
        application.base.win.saveScreenshot(
            Filename.from_os_specific(str(OUTPUT / f"{self.quality}_{name}.png")))

    def check(self, name: str, passed, detail="") -> None:
        # A repeated name must not overwrite an earlier failure.
        base, count = name, 2
        while name in self.results["checks"]:
            name, count = f"{base} (#{count})", count + 1
        self.results["checks"][name] = {"passed": bool(passed), "detail": str(detail)}
        print(("PASS " if passed else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)

    def hold(self, keys: dict, seconds: float) -> None:
        for key in keys:
            held_keys[key] = 1
        self.run_for(seconds)
        for key in keys:
            held_keys[key] = 0

    def press_key(self, key: str, seconds: float = 0.0) -> None:
        """A key down and up, through the handler real keyboard events go to."""
        self.game.input(key)
        self.run_for(seconds) if seconds else self.tick()
        self.game.input("left mouse up" if key == "left mouse down" else (
            "right mouse up" if key == "right mouse down" else f"{key} up"))

    def click(self, entity) -> bool:
        """Pick at the entity's real screen spot, through Ursina's own UI collision test.

        This run cannot own the Windows cursor (another window may have focus), so the ray is
        aimed from code; what it hits, and the button handler that runs, are the real ones.
        """
        x, y = entity.x, entity.y
        mouse._pickerNP.reparent_to(scene.ui_camera)
        mouse._pickerRay.set_from_lens(camera._ui_lens_node, x * 2 / window.aspect_ratio, y * 2)
        mouse._picker.traverse(camera.ui)
        mouse.find_collision()
        hovered = mouse.hovered_entity
        mouse.input("left mouse down")
        self.game.input("left mouse down")
        self.frames(1)
        mouse.input("left mouse up")
        self.game.input("left mouse up")
        self.frames(1)
        return hovered is entity

    def face(self, target_x: float, target_z: float, pitch: float = 8.0) -> None:
        from math import atan2, degrees
        player = self.game.sentry
        self.game.camera.yaw = degrees(atan2(target_x - player.x, target_z - player.z))
        self.game.camera.pitch = pitch
        self.frames(4)

    def run(self) -> None:
        game, teams = self.game, self.game.teams
        self.set_ai_powers(False)
        self.frames(40)
        self.results["start_memory_mb"] = memory_mb()
        self.check("exactly five characters", len(teams.characters) == 5, list(teams.characters))
        self.sample("ground_idle")
        self.shot("ground")
        self.check_movement()
        self.check_quality_keys()
        self.check_menus()
        self.check_switching()
        self.check_powers()
        self.check_new_controls()
        self.check_bars_and_targeting()
        self.check_destruction()
        self.check_performance()

    def set_ai_powers(self, on: bool) -> None:
        self.game.profiles.set("common_enemies", "ai_uses_powers", 1 if on else 0, notify=False)
        self.game.apply_sentry_config()

    def _clear_spot(self, distance: float) -> tuple[float, float]:
        """Level ground with nothing between the two characters, so aim alone is being tested."""
        game = self.game
        world = game.world
        best, best_rise = (0.0, 0.0), 1e9
        for ix in range(-6, 7):
            for iz in range(-6, 7):
                x, z = ix * 22.0, iz * 22.0
                heights = [world.height_at(x, z + distance * f * .2) for f in range(6)]
                rise = max(heights) - min(heights)
                origin = SimVec3(x, heights[0] + 1.6, z)
                hit = trace(game, origin, SimVec3(0.0, 0.0, 1.0), distance, ignore=(), characters=(),
                            terrain=False)
                if hit.kind == "none" and rise < best_rise and (x or z):
                    best, best_rise = (x, z), rise
        return best

    def check_movement(self) -> None:
        game = self.game
        player = game.sentry
        here = (player.x, player.z)
        self.hold({"w": 1}, 1.2)
        moved = ((player.x - here[0]) ** 2 + (player.z - here[1]) ** 2) ** .5
        self.check("W walks", moved > 2.0, f"{moved:.1f} m")
        floor = game.world.height_at(player.x, player.z) + .25
        game.input("space")
        peak = player.y
        for _ in range(25):
            self.tick()
            peak = max(peak, player.y)
        self.check("Space jumps without flying", peak > floor + .3 and not player.flight.is_flying)
        self.run_for(1.0)
        game.input("f")
        self.check("F takes off", player.flight.is_flying)
        self.hold({"space": 1}, 1.5)
        altitude = player.y - game.world.height_at(player.x, player.z)
        self.check("Space rises in flight", altitude > 5.0, f"{altitude:.0f} m")
        held_keys["w"] = held_keys["shift"] = 1
        self.sample("fast_flight")
        held_keys["w"] = held_keys["shift"] = 0
        self.check("500 m ceiling holds", player.y <= 500.0, f"{player.y:.0f} m")
        player.position = (0.0, game.world.height_at(0.0, 0.0) + 8.0, 0.0)
        player.flight.velocity = SimVec3()
        game.input("f")
        end = time.perf_counter() + 20.0
        while player.flight.phase is not FlightPhase.GROUNDED and time.perf_counter() < end:
            self.tick()
        self.check("F lands", player.flight.phase is FlightPhase.GROUNDED)
        spot = (player.x, player.z)
        self.press_key("q")
        self.run_for(.4)
        self.check("Q dashes", ((player.x - spot[0]) ** 2 + (player.z - spot[1]) ** 2) ** .5 > 1.0)

    def check_quality_keys(self) -> None:
        game = self.game
        start = game.settings.quality
        for key in ("1", "2", "3"):
            self.press_key(key, .1)
            game.sentry.powers.cancel_all()
        self.check("keys 1, 2 and 3 never change quality", game.settings.quality == start, start)
        game.input("escape")
        self.frames(2)
        menu = game.hud.pause_menu
        self.check("Esc opens the pause menu", game.paused and menu.enabled)
        self.shot("pause_menu")
        self.frames(2)
        menu.show_graphics()
        self.frames(2)
        self.shot("graphics_settings")
        self.check("Graphics Settings has Low, Medium and High",
                   set(menu.quality_buttons) == {"low", "medium", "high"})
        menu.show_main()
        game.input("escape")
        self.frames(2)
        self.check("Esc resumes", not game.paused)

    def check_menus(self) -> None:
        game = self.game
        panel = game.power_panel
        game.input("p")
        self.frames(3)
        self.check("P opens Character Power Configuration", panel.visible)
        self.shot("config_sentry")
        before = game.elapsed
        self.frames(4)
        self.check("the menu stops gameplay", game.elapsed == before)
        for character_id in SCHEMA:
            hit = self.click(panel.tabs[character_id])
            self.check(f"clicking the {character_id} tab selects it",
                       panel.character_id == character_id, f"hovered={hit}")
        self.shot("config_soldier_boy")
        for character_id in SCHEMA:
            panel.select_character(character_id)
            self.frames(2)
            self.shot(f"config_{character_id.lower()}")
            shown = [card for card in panel.cards if card.ability is not None]
            self.check(f"{character_id} shows a card for each of its {len(SCHEMA[character_id])} abilities",
                       len(shown) == len(SCHEMA[character_id])
                       and all(card.name.text and card.description.text for card in shown))
        panel.select_character("WHITE")
        self.frames(2)
        row = panel.card_of("heat_vision").rows["damage"]
        self.click(row.value)
        for key in "250":
            game.input(key)
        game.input("enter")
        self.frames(2)
        self.check("typing a value moves the slider",
                   panel.current("WHITE", "heat_vision", "damage") == 250.0
                   and abs(row.knob.x - (row.track_left + .25 * row.param.fraction(250.0))) < .01)
        self.click(row.track)
        after = panel.current("WHITE", "heat_vision", "damage")
        self.check("clicking a slider changes its value", after != 250.0, f"250 to {after}")
        self.check("the value box shows the slider's value", row.value.text == f"{after:.0f}", row.value.text)
        panel.set_pending(row, 250.0)
        panel.refresh_rows()
        self.shot("config_heat_vision")
        self.click(panel.apply_button)
        self.check("the Apply button saves it", game.combat.settings.get("WHITE", "heat_vision", "damage") == 250.0)
        self.click(panel.max_button)
        self.check("MAX ALL restores the maximum", game.combat.settings.get("WHITE", "heat_vision", "damage") == 3000.0)
        game.input("p")
        self.frames(3)
        self.check("P closes it", not panel.visible)

        switcher = game.team_panel
        game.input("m")
        self.frames(3)
        self.check("M opens the character switcher", switcher.visible)
        self.shot("switcher")
        hit = self.click(switcher.rows["GREEN"][2])
        self.check("clicking PLAY takes over an enemy", game.sentry.kit.character_id == "GREEN", f"hovered={hit}")
        self.shot("switcher_after_click")
        game.input("m")
        self.frames(3)
        game.teams.swap("YELLOW")

    def check_switching(self) -> None:
        game, teams = self.game, self.game.teams
        for character in teams.characters.values():  # earlier checks fire at full power
            character.powers.hard_reset()
        order = ("WHITE", "RED", "BLACK", "GREEN", "YELLOW", "RED", "WHITE")
        for character_id in order:
            teams.swap(character_id)
            self.run_for(1.0)  # a long-distance swap can stream chunks on the way
            body = teams.characters[character_id]
            distance = ((game.camera.pivot.x - body.x) ** 2 + (game.camera.pivot.z - body.z) ** 2) ** .5
            self.check(f"take over {character_id}: camera and HUD follow",
                       game.sentry is body and body.kit.display in game.hud.status.text and distance < 30.0,
                       f"{distance:.1f} m")
        self.check("exactly one player-controlled body",
                   sum(c.controlled for c in teams.characters.values()) == 1)
        self.run_for(1.0)
        self.shot("superman_after_swap")
        red = teams.characters["RED"]
        teams.swap("RED")
        game.input("f")
        self.hold({"space": 1}, .5)
        self.run_for(.6)
        self.check("Soldier Boy cannot fly", not red.flight.is_flying
                   and red.y < game.world.height_at(red.x, red.z) + 3.0, red.flight.phase.name)
        self.shot("soldier_boy")
        here = (red.x, red.z)
        self.hold({"w": 1, "shift": 1}, .8)
        ran = ((red.x - here[0]) ** 2 + (red.z - here[1]) ** 2) ** .5
        self.check("Soldier Boy runs", ran > 2.0, f"{ran:.1f} m")

    def _place(self, character_id: str, enemy_id: str, distance: float = 25.0):
        game, teams = self.game, self.game.teams
        teams.swap(character_id)
        body = game.sentry
        body.powers.hard_reset()
        body.release_motion()
        spot, spot_z = self._clear_spot(distance)
        body.position = (spot, game.world.height_at(spot, spot_z) + .25, spot_z)
        body.flight.phase = FlightPhase.GROUNDED
        body.flight.velocity = SimVec3()
        body.ground.velocity = SimVec3()
        for other_id, other in teams.characters.items():
            if other_id not in (character_id, enemy_id):
                teams.state.assignment[other_id] = "available"
        enemy = teams.characters[enemy_id]
        teams.state.assignment[enemy_id] = "enemy_team"
        teams._apply_roster()
        enemy.powers.apply_passives()
        enemy.powers.hard_reset()
        enemy.vitals.regen = 0.0
        enemy.vitals.max_health = enemy.vitals.health = 1e7  # survives to show what happens next
        enemy.position = (spot, game.world.height_at(spot, spot_z + distance) + .25, spot_z + distance)
        enemy.flight.phase = FlightPhase.GROUNDED
        enemy.flight.velocity = SimVec3()
        body.local_yaw = 0.0
        # Settle the chase camera first: it follows the body with some lag, and aim comes from it.
        self.face(spot, spot_z + distance, 4.0)
        self.run_for(.8)
        enemy.position = (spot, game.world.height_at(spot, spot_z + distance) + .25, spot_z + distance)
        enemy.flight.phase = FlightPhase.GROUNDED
        enemy.flight.velocity = SimVec3()
        enemy.vitals.add_status("held", 30.0)  # stands still as a target, unlike normal AI
        self.frames(2)
        return body, enemy

    def check_powers(self) -> None:
        """Every ability a key reaches, in a real window, at the default maximum values."""
        game = self.game
        body, enemy = self._place("WHITE", "BLACK")
        self.press_key("1")
        self.check("Superman: heat vision stays on after the key comes up",
                   body.powers.abilities["heat_vision"].active)
        self.run_for(1.0)
        self.shot("superman_heat_vision")
        self.press_key("1")
        self.check("Superman: heat vision hits with no aiming", enemy.vitals.damage_taken > 0.0,
                   f"{enemy.vitals.damage_taken:.0f} dmg")
        self.check("Superman: pressing 1 again stops it", not body.powers.abilities["heat_vision"].active)
        self._check_ground_execution()
        body, enemy = self._place("WHITE", "BLACK")
        self.press_key("r")
        self.check("Superman: Solar Overcharge starts at once", body.powers.abilities["solar_overcharge"].active)
        self.run_for(1.2)
        self.shot("superman_solar")
        self.press_key("r")
        self.check("Superman: R again ends it", not body.powers.abilities["solar_overcharge"].active)

        body, enemy = self._place("BLACK", "WHITE")
        self.press_key("1")
        self.run_for(1.0)
        self.shot("homelander_laser")
        self.press_key("1")
        self.check("Homelander: laser vision", enemy.vitals.damage_taken > 0.0)
        self.press_key("r")
        self.check("Homelander: Laser Overdrive starts at once", body.powers.abilities["laser_overdrive"].engaged)
        self.press_key("r")

        body, enemy = self._place("YELLOW", "BLACK")
        self.press_key("r")
        self.run_for(1.8)  # past the opening flash, so the darkened body itself can be seen
        self.shot("sentry_void")
        self.check("Sentry: Void Unleashed changes him",
                   body.powers.abilities["void_unleashed"].engaged and body.pose_root.hasColorScale())
        self.press_key("r")
        self.frames(2)
        self.check("Sentry: R again returns his own look", not body.pose_root.hasColorScale())

        body, enemy = self._place("GREEN", "BLACK")
        self.press_key("1")
        self.run_for(.5)
        self.shot("omni_charge")
        self.check("Omni-Man: flight charge rams", enemy.vitals.damage_taken > 50.0, f"{enemy.vitals.damage_taken:.0f} dmg")
        body.release_motion()
        body, enemy = self._place("GREEN", "BLACK", 5.0)
        self.press_key("4")
        self.frames(2)
        self.shot("omni_punch")
        self.check("Omni-Man: shockwave punch lands on the press", body.powers.abilities["shockwave_punch"].strikes > 0)
        body, enemy = self._place("GREEN", "BLACK", 25.0)
        self.press_key("r")
        ok = body.motion is not None
        self.run_for(3.0)
        self.shot("omni_dive_bomb")
        self.check("Omni-Man: dive bomb", ok and body.motion is None and enemy.vitals.damage_taken > 0.0,
                   f"under way on the press={ok}")

        body, enemy = self._place("RED", "BLACK", 10.0)
        before = body.powers.abilities["radioactive_discharge"].discharges
        self.press_key("r")
        self.frames(3)
        self.shot("soldier_boy_discharge")
        self.check("Soldier Boy: maximum discharge fires at once and nullifies Homelander",
                   body.powers.abilities["radioactive_discharge"].discharges == before + 1
                   and enemy.vitals.nullified)
        self.check("Homelander cannot fly while nullified", not enemy.flight_allowed)
        self.run_for(1.0)
        for character in game.teams.characters.values():
            character.powers.hard_reset()

    def _check_ground_execution(self) -> None:
        """Superman's key 4 from start to finish, with a screenshot of every stage."""
        game = self.game
        body, enemy = self._place("WHITE", "BLACK", 60.0)
        enemy.vitals.clear_status("held")
        self.face(body.x, body.z - 100.0, 4.0)  # looking away: it must need no aiming
        craters, sky = len(game.world.terrain_impacts), game.environment._time
        self.press_key("4")
        self.check("Superman: 4 stops time at once", game.combat.time_stopped)
        phases, end = [], time.perf_counter() + 25.0
        shots = {"lift", "fall", "burn", "away"}
        while body.motion is not None and time.perf_counter() < end:
            phase = body.motion.phase
            if not phases or phases[-1] != phase:
                phases.append(phase)
                if phase in shots:
                    self.tick()
                    self.tick()
                    self.shot(f"superman_execution_{phase}")
                    continue
            self.tick()
        self.check("Superman: execution runs every stage in order",
                   phases == ["rush", "hold", "lift", "fall", "burn", "away"], phases)
        self.check("Superman: execution does real damage and marks the ground",
                   enemy.vitals.damage_taken > 0.0 and len(game.world.terrain_impacts) > craters,
                   f"{enemy.vitals.damage_taken:.0f} dmg")
        self.check("Superman: execution gives time and control back",
                   not game.combat.time_stopped and body.motion is None)
        self.frames(4)
        self.check("Superman: world time runs again after the execution", game.environment._time > sky)
        self.shot("superman_execution_after")

    def _time_stop_runs_out(self) -> bool:
        end = time.perf_counter() + 15.0
        while self.game.combat.time_stopped and time.perf_counter() < end:
            self.tick()
        return not self.game.combat.time_stopped

    def check_new_controls(self) -> None:
        """The controls update, through the handler real keyboard events reach."""
        game = self.game
        for character_id in ("WHITE", "BLACK", "YELLOW", "GREEN"):
            enemy_id = "WHITE" if character_id == "BLACK" else "BLACK"
            name = character_id.lower()
            body, enemy = self._place(character_id, enemy_id, 60.0)
            enemy.vitals.clear_status("held")
            self.face(body.x, body.z - 100.0, 4.0)  # looking away: none of this needs aiming
            self.press_key("2")
            self.check(f"{name}: 2 starts the attack at once", body.motion is not None)
            self.frames(4)
            self.shot(f"{name}_high_speed_attack")
            self.run_for(1.2)
            self.check(f"{name}: 2 hit the nearest enemy and gave control back",
                       enemy.vitals.damage_taken > 0.0 and body.motion is None,
                       f"{enemy.vitals.damage_taken:.0f} dmg")
            body, enemy = self._place(character_id, enemy_id, 40.0)
            enemy.vitals.clear_status("held")
            sky_before = game.environment._time
            self.press_key("3")
            self.check(f"{name}: 3 stops time at once", game.combat.time_stopped)
            self.run_for(.45)
            self.shot(f"{name}_time_stop")
            self.check(f"{name}: wind, waves and clouds stand still", game.environment._time == sky_before)
            self.check(f"{name}: time comes back", self._time_stop_runs_out())
            self.check(f"{name}: 3 hurt and threw the enemy, and gave control back",
                       enemy.vitals.damage_taken > 0.0 and body.motion is None,
                       f"{enemy.vitals.damage_taken:.0f} dmg")
            self.frames(4)
            self.check(f"{name}: world time runs again", game.environment._time > sky_before)
            body, enemy = self._place(character_id, enemy_id, 4.0)
            enemy.vitals.clear_status("held")
            self.face(body.x, body.z - 100.0, 4.0)
            melee = body.powers.abilities["melee"]
            self.press_key("=")
            self.frames(3)
            self.check(f"{name}: the + key punches", melee.attacks == 1 and melee.kicks == 0
                       and enemy.vitals.damage_taken > 0.0)
            self.shot(f"{name}_punch")
            self.press_key("-")
            self.frames(3)
            self.check(f"{name}: the - key kicks", melee.kicks == 1)
            self.shot(f"{name}_kick")
            for key in ("e", "left mouse down", "right mouse down"):
                attacks, taken = melee.attacks, enemy.vitals.damage_taken
                self.press_key(key)
                self.frames(2)
                self.check(f"{name}: {key} does nothing", melee.attacks == attacks and body.motion is None
                           and enemy.vitals.damage_taken == taken)
            game.input("f")
            self.check(f"{name}: F takes off", body.flight.is_flying)
            game.input("f")
            self.run_for(.5)

        for character_id in ("YELLOW", "RED"):
            name = character_id.lower()
            body, enemy = self._place(character_id, "BLACK", 120.0)
            enemy.vitals.clear_status("held")
            bomb = body.powers.abilities["bomb_mode"]
            self.press_key("1")
            self.check(f"{name}: 1 throws a bomb at once", bomb.active and bomb.flying)
            self.frames(6)
            self.shot(f"{name}_bomb_in_flight")
            self.check(f"{name}: the bomb travels and has not gone off",
                       bomb.flying and enemy.vitals.damage_taken == 0.0, f"{bomb.travelled:.0f} m")
            self.run_for(.8)
            self.shot(f"{name}_bomb_explosion")
            self.check(f"{name}: the bomb goes off at the enemy", enemy.vitals.damage_taken > 0.0,
                       f"{enemy.vitals.damage_taken:.0f} dmg")
            self.press_key("1")
            thrown = bomb.thrown
            self.run_for(1.2)
            self.check(f"{name}: 1 again stops new bombs", not bomb.active and not bomb.flying
                       and bomb.thrown == thrown)
            body, enemy = self._place(character_id, "BLACK", 90.0)
            blast = body.powers.abilities["massive_blast"]
            self.press_key("4")
            self.check(f"{name}: 4 sets off one massive blast", blast.blasts == 1
                       and enemy.vitals.damage_taken > 0.0, f"{enemy.vitals.damage_taken:.0f} dmg")
            self.frames(6)
            self.shot(f"{name}_massive_blast")
            self.run_for(1.0)
            self.shot(f"{name}_massive_blast_after")
        red = game.teams.characters["RED"]
        for key in ("2", "3", "=", "-", "e", "left mouse down", "right mouse down", "f"):
            self.press_key(key)
            self.frames(2)
            self.check(f"Soldier Boy: {key} does nothing", not game.combat.time_stopped and red.motion is None
                       and not red.flight.is_flying)
        game.landmarks.restore_all()
        for character in game.teams.characters.values():
            character.powers.hard_reset()

    def check_bars_and_targeting(self) -> None:
        """Every health bar on screen above its own body, and automatic targeting in real use."""
        game, teams = self.game, self.game.teams
        partners = {"WHITE": "BLACK", "BLACK": "WHITE", "YELLOW": "BLACK", "GREEN": "BLACK", "RED": "BLACK"}
        for character_id, enemy_id in partners.items():
            body, enemy = self._place(character_id, enemy_id, 7.0)
            enemy.vitals.health = enemy.vitals.max_health * .5
            self.frames(4)
            tag = teams.tags[enemy_id]
            self.check(f"{character_id}: enemy bar shows its health", abs(tag.fraction - .5) < .02,
                       f"{tag.fraction:.2f}")
            self.check(f"{character_id}: no bar over their own head", teams.tags[character_id].root.isHidden())
            self.check(f"{character_id}: nearest enemy is targeted", game.combat.shown_target is enemy
                       and enemy.display_name in game.hud.target_text.text, game.hud.target_text.text)
            self.shot(f"bars_{character_id.lower()}")
        body, enemy = self._place("YELLOW", "BLACK", 40.0)
        self.face(body.x, body.z - 100.0, 4.0)  # looking directly away from the enemy
        yaw = game.camera.yaw
        self.press_key("=")
        self.run_for(.6)
        self.check("an enemy behind the camera is hit without aiming", enemy.vitals.damage_taken > 0.0,
                   f"{enemy.vitals.damage_taken:.0f} dmg")
        self.check("targeting does not move the camera", game.camera.yaw == yaw)
        self.shot("target_behind")
        for character in teams.characters.values():
            character.powers.apply_passives()
            character.powers.hard_reset()

    def check_destruction(self) -> None:
        game, combat = self.game, self.game.combat
        world = game.world
        teams = game.teams
        game.landmarks.restore_all()  # the powers checks have already blown up what was nearby
        self.frames(2)
        teams.swap("YELLOW")
        body = game.sentry
        building = next(i for i in game.landmarks.items if getattr(i, "display_name", "") == "Building")
        body.position = (building.x, world.height_at(building.x, building.z - 45.0) + 15.0, building.z - 45.0)
        body.flight.phase = FlightPhase.CRUISE
        body.flight.velocity = SimVec3()
        self.face(building.x, building.z, 0.0)
        self.shot("destruction_building_before")
        health = building.health.maximum_health
        building.take_damage(health * .6, impact_position=SimVec3(building.x, building.y, building.z - 8.0))
        self.frames(4)
        self.shot("destruction_building_damaged")
        self.check("buildings show progressive damage", building.damage_stage >= 2 and not building.health.broken,
                   f"stage {building.damage_stage}")
        combat.blast(body, SimVec3(building.x, building.y, building.z), 30.0, 1000.0, 40.0,
                     crater=(10.0, 2.0, "check"))
        self.run_for(.5)
        self.shot("destruction_building_collapse")
        self.check("buildings collapse", building.health.broken)
        vehicle = next(i for i in game.landmarks.items if getattr(i, "display_name", "") == "Vehicle")
        vehicle.take_damage(1000.0, impact_position=SimVec3(vehicle.x, vehicle.y, vehicle.z))
        self.frames(3)
        self.check("vehicles break", vehicle.health.broken)
        tree = next(t for chunk in world.chunks.values() for t in chunk.tree_colliders
                    if t.tree_health >= world.TREE_MAX_HEALTH)
        combat.elements.ignite_tree(tree)
        self.frames(2)
        self.shot("destruction_tree_burning")
        tree_id = tree.tree_id
        world.damage_tree(tree, 1000.0, SimVec3(1.0, 0.0, 0.0))
        self.run_for(1.0)
        self.check("trees fall and persist", world.tree_states[tree_id]["destroyed"])
        x, z = body.x, body.z + 25.0
        before = world.height_at(x, z)
        world.terrain_impact(SimVec3(x, before, z), radius=8.0, depth=3.0, intensity=1.5, surface="check")
        self.run_for(1.0)
        self.check("terrain craters change the ground", world.height_at(x, z) < before - 1.0)
        self.check("debris stays in budget", len(world.debris) <= world.debris_budget.maximum_live_pieces,
                   len(world.debris))

    def check_performance(self) -> None:
        game, teams = self.game, self.game.teams
        self.set_ai_powers(True)
        for character_id in teams.characters:
            teams.assign(character_id, "enemy_team") if character_id != teams.state.player else None

        beam = {"on": False}

        def beams():
            if not beam["on"]:
                beam["on"] = True
                self.press_key("1")
            return 3.0

        teams.swap("WHITE")
        spot = 700.0
        game.sentry.position = (spot, game.world.height_at(spot, spot) + .25, spot)
        self.sample("sustained_beam", during=beams)

        def fighting():
            player = game.sentry
            player.vitals.health = player.vitals.max_health
            return 1.0

        self.sample("ai_fight_with_beam", during=fighting)
        self.press_key("1")

        turn = {"at": 0}

        def superman_powers():
            """Real abilities at their default maximum, switched on and off twice a second."""
            game.sentry.vitals.health = game.sentry.vitals.max_health
            key = ("1", "r", "=", "-")[turn["at"] % 4]
            turn["at"] += 1
            game.input(key)
            game.input(f"{key} up")
            return .5

        self.sample("max_power_superman", during=superman_powers)
        game.sentry.powers.cancel_all()
        teams.swap("RED")

        def soldier_boy_powers():
            """His largest attacks, one after another: the worst case for destruction."""
            game.sentry.vitals.health = game.sentry.vitals.max_health
            key = ("r", "4")[turn["at"] % 2]
            turn["at"] += 1
            game.input(key)
            game.input(f"{key} up")
            return 1.0

        self.sample("max_power_soldier_boy", during=soldier_boy_powers)
        teams.swap("YELLOW")
        self.press_key("1")
        self.sample("bomb_mode_on", during=fighting)
        self.press_key("1")
        teams.swap("WHITE")

        cycle = {"count": 0}

        def blasts():
            player = game.sentry
            cycle["count"] += 1
            x = player.x + (cycle["count"] % 7) * 16.0 - 48.0
            z = player.z + 40.0 + (cycle["count"] % 5) * 14.0
            game.combat.blast(player, SimVec3(x, game.world.height_at(x, z), z), 25.0, 500.0, 40.0,
                              crater=(7.0, 1.5, "bench"), cracks=True)
            return .5

        self.sample("heavy_destruction", during=blasts)
        self.results["after_destruction"] = {"debris": len(game.world.debris),
                                             "craters": len(game.world.terrain_impacts),
                                             "effects": len(game.world.effects)}

        def fixed_entities() -> int:
            world = game.world
            streamed = sum(len(chunk.entities) for chunk in world.chunks.values())
            return len(scene.entities) - streamed - len(world.debris) - len(world.effects) * 3

        self.set_ai_powers(False)
        self.run_for(10.0)
        entities_before = fixed_entities()
        memory_before = memory_mb()
        order = list(teams.characters)
        index = {"at": 0}

        def swaps():
            teams.swap(order[index["at"] % 5], save=False)
            index["at"] += 1
            return .25

        self.sample("rapid_switching", during=swaps)
        self.run_for(1.0)
        self.check("switching adds no entities", fixed_entities() <= entities_before + 8,
                   f"{entities_before} to {fixed_entities()}")
        self.set_ai_powers(True)
        teams.swap("YELLOW")
        held_keys["w"] = 1
        self.sample("extended_session", SAMPLE_SECONDS * 4.0)
        held_keys["w"] = 0
        self.results["memory_growth_mb"] = round(memory_mb() - memory_before, 1)
        self.results["end_entities"] = len(scene.entities)


def run(quality: str, output: str) -> None:
    app, game = main.build_game("onscreen")
    game.sentry_config.config_path = _saves / "sentry_settings.json"
    game.sentry_config.reset()
    game.profiles._values = {name: {} for name in game.profiles._values}
    application.asset_folder = ROOT
    game.apply_sentry_config()
    game.set_quality(quality)
    width, height = os.environ.get("SENTRY_BENCH_RESOLUTION", "1600x900").split("x")
    window.size = (int(width), int(height))
    check = Check(game, app, quality)
    check.run()
    failed = [name for name, entry in check.results["checks"].items() if not entry["passed"]]
    check.results["failed"] = failed
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(check.results, indent=1), encoding="utf-8")
    print("FAILED: " + ", ".join(failed) if failed else "ALL WINDOW CHECKS PASSED", flush=True)
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    level = sys.argv[1] if len(sys.argv) > 1 else "low"
    target = sys.argv[2] if len(sys.argv) > 2 else str(OUTPUT / f"results_{level}.json")
    try:
        run(level, target)
    except BaseException:
        import traceback
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        os._exit(2)


__all__ = ["camera", "FLYERS"]
