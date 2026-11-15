"""Real-window FPS, frame spikes and memory at 1600x900, one quality per process.

Usage: python aesthetic_benchmark.py <low|medium|high> <seconds per scenario> <output json>
Runs the project in the current directory, so a backup can be measured the same way.
Your saves are never written: everything goes to a temporary folder.
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
from unittest import mock

sys.path.insert(0, os.getcwd())
_saves = Path(tempfile.mkdtemp(prefix="sentry_bench_"))
os.environ["SENTRY_DESTRUCTION_SAVE"] = str(_saves / "island_destruction.json")
os.environ["SENTRY_PROFILE_FILE"] = str(_saves / "profiles.json")

import main  # noqa: E402
import game.game_manager as manager  # noqa: E402
from movement.flight_physics import FlightPhase, Vec3 as SimVec3  # noqa: E402
from panda3d.core import Filename  # noqa: E402
from ursina import application, window  # noqa: E402

manager.save_settings = lambda _settings: None


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
    psapi = ctypes.WinDLL("psapi")
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD)
    psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return round(counters.WorkingSetSize / (1024.0 * 1024.0), 1)


def run(quality: str, seconds: float, output: str) -> None:
    app, game = main.build_game("onscreen")
    game.sentry_config.config_path = _saves / "sentry_settings.json"
    game.sentry_config.reset()
    game.profiles._values = {name: {} for name in game.profiles._values}
    game.apply_sentry_config()
    game.set_quality(quality)
    window.size = (1600, 900)
    team, player = game.enemy_team, game.sentry
    shots = Path(output).with_suffix("")
    shots.mkdir(parents=True, exist_ok=True)

    def tick() -> None:
        game.update()
        app.step()

    def sample(name: str, length: float, each=None) -> dict:
        times, end = [], time.perf_counter() + length
        previous = time.perf_counter()
        minimized = 0
        while time.perf_counter() < end:
            player.health = player.maximum_health
            if each is not None:
                each()
            tick()
            now = time.perf_counter()
            times.append(now - previous)
            previous = now
            # Panda sleeps .1 s per frame while minimized, which would poison the numbers.
            minimized += bool(application.base.win.getProperties().getMinimized())
        results.setdefault("minimized_frames", 0)
        results["minimized_frames"] += minimized
        application.base.win.saveScreenshot(Filename.from_os_specific(str(shots / f"{name}.png")))
        ordered = sorted(times, reverse=True)
        low = ordered[:max(1, len(ordered) // 100)]
        return {"fps": round(len(times) / sum(times), 1), "low_1pct": round(len(low) / sum(low), 1),
                "worst_ms": round(ordered[0] * 1000.0, 1),
                "over_33ms_pct": round(100.0 * sum(t > 1 / 30 for t in times) / len(times), 1),
                "memory_mb": memory_mb()}

    for _ in range(60):
        tick()
    results = {"quality": quality, "start_memory_mb": memory_mb()}
    team._attacks_allowed_at = game.elapsed + 1000.0
    results["ground_idle"] = sample("ground_idle", seconds)

    player.flight.phase = FlightPhase.CRUISE
    player.y = game.world.height_at(player.x, player.z) + 60.0
    game.camera.pitch = -6.0

    def traverse() -> None:
        player.flight.phase = FlightPhase.CRUISE
        player.flight.velocity = SimVec3(0.0, 0.0, 160.0)

    with mock.patch.object(game.input_manager, "movement", return_value=(SimVec3(0.0, 0.0, 1.0), 0.0)):
        results["flight_traversal"] = sample("flight_traversal", seconds, traverse)

    player.position = (0.0, game.world.height_at(0.0, 0.0) + .25, 0.0)
    player.flight.phase = FlightPhase.GROUNDED
    player.flight.velocity = SimVec3()
    team._attacks_allowed_at = game.elapsed
    results["combat"] = sample("combat", seconds)

    next_blast = [0.0]

    def explode() -> None:
        now = time.perf_counter()
        if now >= next_blast[0]:
            next_blast[0] = now + 1.0
            x, z = player.x + 25.0, player.z + 25.0
            game.world.ground_impact(SimVec3(x, game.world.height_at(x, z), z), 300.0, 18.0, 30.0)

    results["explosions"] = sample("explosions", seconds, explode)
    before = memory_mb()
    results["extended_combat"] = sample("extended_combat", seconds * 4.0, explode)
    results["memory_growth_mb"] = round(memory_mb() - before, 1)
    results["draw_regions_note"] = "worst_ms includes any shader compile on first use"
    Path(output).write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(json.dumps(results), flush=True)
    os._exit(0)


if __name__ == "__main__":
    try:
        run(sys.argv[1], float(sys.argv[2]), sys.argv[3])
    except BaseException:
        import traceback
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        os._exit(2)
