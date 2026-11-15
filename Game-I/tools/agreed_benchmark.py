"""The agreed benchmark: one scenario per process, in a real window, with temporary saves.

    python tools/agreed_benchmark.py <scenario> --size 1600x900 --seconds 60 --out result.json

SENTRY_BENCH_ROOT points it at another copy of the game, so a baseline can be measured from the
untouched original with exactly the same tool as the current build.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(os.environ.get("SENTRY_BENCH_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.dont_write_bytecode = True
_saves = Path(tempfile.mkdtemp(prefix="sentry_bench_"))
os.environ["SENTRY_DESTRUCTION_SAVE"] = str(_saves / "island_destruction.json")
os.environ["SENTRY_PROFILE_FILE"] = str(_saves / "profiles.json")
os.environ["SENTRY_ROSTER_FILE"] = str(_saves / "roster.json")
os.environ["SENTRY_POWER_FILE"] = str(_saves / "powers.json")
os.environ["SENTRY_VSYNC"] = "0"
os.environ.setdefault("SENTRY_THREADING", "Cull/Draw")

SCENARIOS = ("idle", "boost_flight", "ai_fight", "beam", "nuclear", "squad")
WARMUP_SECONDS = 5.0


class _Counters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def memory_mb() -> tuple[float, float]:
    counters = _Counters()
    counters.cb = ctypes.sizeof(counters)
    psapi, kernel = ctypes.WinDLL("psapi"), ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD)
    psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return counters.WorkingSetSize / 1048576.0, counters.PeakWorkingSetSize / 1048576.0


def on_ac_power() -> bool | None:
    class Status(ctypes.Structure):
        _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("percent", ctypes.c_ubyte),
                    ("saver", ctypes.c_ubyte), ("life", wintypes.DWORD), ("full", wintypes.DWORD)]
    status = Status()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))
    return {0: False, 1: True}.get(status.ac)


def percentile(ordered: list[float], share: float) -> float:
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))]


def by_name(game, name: str):
    for character_id, character in game.teams.characters.items():
        if character.display_name.lower().replace("-", "").replace(" ", "") == name:
            return character_id
    raise RuntimeError(f"No character called {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--size", default="1600x900")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--quality", default="low")
    parser.add_argument("--out", required=True)
    parser.add_argument("--shot", default="")
    parser.add_argument("--threading", default=None)
    args = parser.parse_args()
    width, height = (int(value) for value in args.size.lower().split("x"))
    if args.threading is not None:
        os.environ["SENTRY_THREADING"] = args.threading

    import config as config_module
    config_module.QUALITY_RESOLUTIONS[args.quality] = (width, height)
    preset = config_module.QUALITY_PRESETS[args.quality]
    config_module.load_settings = lambda: preset
    import game.game_manager as manager
    manager.save_settings = lambda _settings: None
    manager.load_settings = lambda: preset
    import main as game_main
    from movement.flight_physics import FlightPhase, Vec3 as SimVec3
    from panda3d.core import Filename, WindowProperties
    from ursina import application, held_keys, mouse, scene

    started_load = time.perf_counter()
    app, game = game_main.build_game("onscreen")
    if hasattr(game, "sentry_config"):
        game.sentry_config.config_path = _saves / "sentry_settings.json"
    load_seconds = time.perf_counter() - started_load
    mouse.locked = False

    win = application.base.win
    properties = WindowProperties()
    properties.setForeground(True)
    win.requestProperties(properties)

    def tick() -> tuple[float, float]:
        mouse.locked = False
        begin = time.perf_counter()
        game.update()
        middle = time.perf_counter()
        app.step()
        end = time.perf_counter()
        return middle - begin, end - middle

    teams, combat, world = game.teams, game.combat, game.world
    state = {"next": 0.0}

    def player(name: str) -> None:
        teams.swap(by_name(game, name), save=False)

    def gather_enemies(reach: float = 25.0) -> None:
        import math
        me = game.sentry
        for index, enemy in enumerate(teams.enemies):
            angle = index * 2.0 * math.pi / max(1, len(teams.enemies))
            x, z = float(me.x) + math.sin(angle) * reach, float(me.z) + math.cos(angle) * reach
            enemy.position = (x, world.height_at(x, z) + .25, z)

    scenario = args.scenario
    during = None
    if scenario == "boost_flight":
        game.input("f")
        for _ in range(10):
            tick()
        sentry = game.sentry
        sentry.position = (float(sentry.x), float(world.height_at(float(sentry.x), float(sentry.z))) + 100.0, float(sentry.z))
        held_keys["w"] = held_keys["shift"] = 1
        game.camera.pitch = 0.0
        game.camera.yaw = 35.0

        def during(now: float) -> None:
            if max(abs(float(game.sentry.x)), abs(float(game.sentry.z))) > 3500.0:
                game.camera.yaw = (game.camera.yaw + 170.0) % 360.0
    elif scenario == "ai_fight":
        gather_enemies()
    elif scenario == "beam":
        player("superman")
        gather_enemies(40.0)
        game.input("1")
    elif scenario == "nuclear":
        player("soldierboy")
        gather_enemies(60.0)
        game.input("1")

        def during(now: float) -> None:
            if now >= state["next"]:
                state["next"] = now + 5.0
                x, z = float(game.sentry.x) + 90.0, float(game.sentry.z) + 90.0
                combat.blast(None, SimVec3(x, world.height_at(x, z), z), 150.0, 400.0, 30.0,
                             crater=(10.0, 1.5, "smoke"))
    elif scenario == "squad":
        player("omniman")
        gather_enemies(60.0)
        game.input("1")

    warm_end = time.perf_counter() + WARMUP_SECONDS
    while time.perf_counter() < warm_end:
        if during is not None:
            during(time.perf_counter())
        tick()

    begin_memory = memory_mb()[0]
    cpu_begin = time.process_time()
    frames, updates, steps, foreground_frames = [], [], [], 0
    begin = previous = time.perf_counter()
    end = begin + args.seconds
    max_characters = 0
    while time.perf_counter() < end:
        if during is not None:
            during(time.perf_counter())
        update_seconds, step_seconds = tick()
        now = time.perf_counter()
        frames.append((now - previous) * 1000.0)
        updates.append(update_seconds * 1000.0)
        steps.append(step_seconds * 1000.0)
        previous = now
        foreground_frames += bool(win.getProperties().getForeground())
        max_characters = max(max_characters, len(list(combat.in_world)))
    elapsed = time.perf_counter() - begin
    cpu = time.process_time() - cpu_begin
    finish_memory, peak_memory = memory_mb()
    ordered = sorted(frames)
    low = ordered[-max(1, len(ordered) // 100):]
    result = {
        "scenario": scenario, "size": args.size, "quality": args.quality, "seconds": round(elapsed, 2),
        "root": str(ROOT), "threading": os.environ.get("SENTRY_THREADING", ""), "ac_power": on_ac_power(), "window": [win.getXSize(), win.getYSize()],
        "foreground_share": round(foreground_frames / max(1, len(frames)), 3),
        "load_seconds": round(load_seconds, 2), "frames": len(frames),
        "average_fps": round(len(frames) / elapsed, 2), "frame_ms_mean": round(statistics.fmean(frames), 2),
        "frame_ms_p50": round(percentile(ordered, .5), 2), "frame_ms_p95": round(percentile(ordered, .95), 2),
        "frame_ms_p99": round(percentile(ordered, .99), 2), "worst_frame_ms": round(ordered[-1], 2),
        "one_percent_low_fps": round(1000.0 * len(low) / sum(low), 2),
        "frames_over_33ms": sum(value > 33.33 for value in frames),
        "frames_over_50ms": sum(value > 50.0 for value in frames),
        "frames_over_100ms": sum(value > 100.0 for value in frames),
        "update_ms_mean": round(statistics.fmean(updates), 2), "update_ms_max": round(max(updates), 2),
        "step_ms_mean": round(statistics.fmean(steps), 2), "step_ms_max": round(max(steps), 2),
        "process_cpu_percent_of_one_thread": round(100.0 * cpu / elapsed, 1),
        "working_set_begin_mb": round(begin_memory, 1), "working_set_end_mb": round(finish_memory, 1),
        "working_set_peak_mb": round(peak_memory, 1), "entities_end": len(scene.entities),
        "characters_in_world_max": max_characters, "player": game.sentry.display_name,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("scenario", "size", "average_fps", "frame_ms_p95", "frame_ms_p99",
                                                   "worst_frame_ms", "update_ms_mean", "foreground_share")}), flush=True)
    if args.shot:
        Path(args.shot).parent.mkdir(parents=True, exist_ok=True)
        win.saveScreenshot(Filename.from_os_specific(args.shot))
    application.base.userExit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
