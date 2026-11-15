"""Repeatable on-screen benchmark; writes JSON and uses an isolated save."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

_bench_game = None


def update():
    if _bench_game is not None:
        _bench_game.update()


def process_metrics():
    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                           ctypes.POINTER(ProcessMemoryCounters),
                                           wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileTime),
                                       ctypes.POINTER(FileTime), ctypes.POINTER(FileTime),
                                       ctypes.POINTER(FileTime)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    process = kernel.GetCurrentProcess()
    memory = ProcessMemoryCounters()
    memory.cb = ctypes.sizeof(memory)
    if not psapi.GetProcessMemoryInfo(process, ctypes.byref(memory), memory.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    creation, exit_time, kernel_time, user_time = FileTime(), FileTime(), FileTime(), FileTime()
    if not kernel.GetProcessTimes(process, ctypes.byref(creation), ctypes.byref(exit_time),
                                  ctypes.byref(kernel_time), ctypes.byref(user_time)):
        raise ctypes.WinError(ctypes.get_last_error())
    cpu_100ns = (((kernel_time.high << 32) | kernel_time.low)
                 + ((user_time.high << 32) | user_time.low))
    return {"working_set_mb": memory.WorkingSetSize / (1024 * 1024),
            "private_mb": memory.PrivateUsage / (1024 * 1024),
            "cpu_100ns": cpu_100ns}


def scene_geometry(base, scene):
    paths = base.render.findAllMatches("**/+GeomNode")
    geoms = triangles = 0
    for path in paths:
        node = path.node()
        geoms += node.getNumGeoms()
        for geom_index in range(node.getNumGeoms()):
            geom = node.getGeom(geom_index)
            for primitive_index in range(geom.getNumPrimitives()):
                triangles += geom.getPrimitive(primitive_index).decompose().getNumPrimitives()
    return {"scene_entities": len(scene.entities), "geom_nodes": paths.getNumPaths(),
            "draw_call_upper_bound": geoms, "triangle_count": triangles}


def main():
    save_root = Path(tempfile.mkdtemp(prefix="sentry_perf_save_"))
    os.environ["LOCALAPPDATA"] = str(save_root)
    save_file = save_root / "Sentry" / "island_destruction.json"
    os.environ["SENTRY_DESTRUCTION_SAVE"] = str(save_file)
    project_root = Path(__file__).resolve().parents[1]
    os.chdir(project_root)
    sys.argv[0] = str(project_root / "main.py")
    sys.path.insert(0, str(project_root))

    from ursina import application, held_keys, scene, window
    from panda3d.core import Filename
    from movement.flight_physics import FlightPhase, Vec3 as SimVec3
    import config as config_module
    from main import build_game
    from world.island_generator import IslandWorld
    from world.interactive_objects import DestructibleEntity, TrafficVehicle
    from characters.civilian import Civilian

    sample_seconds = float(os.environ.get("SENTRY_BENCH_SECONDS", "1.5"))
    quality_override = os.environ.get("SENTRY_BENCH_QUALITY", "").lower()
    if quality_override in {"low", "medium", "high"}:
        preset = config_module.QUALITY_PRESETS[quality_override]
        config_module.load_settings = lambda preset=preset: type(preset)(
            preset.quality, preset.render_distance, preset.civilian_count,
            preset.debris_lifetime, preset.day_length_seconds)
        # Keep the requested common benchmark resolution for every preset.
        config_module.QUALITY_RESOLUTIONS[quality_override] = (1600, 900)
    app, game = build_game("onscreen")
    resolution = os.environ.get("SENTRY_BENCH_RESOLUTION", "1600x900")
    try:
        width, height = (int(value) for value in resolution.lower().split("x", 1))
        window.size = (width, height)
    except (TypeError, ValueError):
        resolution = "configured"
    if quality_override in {"low", "medium", "high"}:
        game._windowed_resolution = (width, height)
    if not game.world.damage_save_path.resolve().is_relative_to(save_root.resolve()):
        raise RuntimeError("Benchmark destruction save escaped its isolated temporary directory")
    global _bench_game
    _bench_game = game
    telemetry = {"scenario": "startup", "counts": {}, "timings": {}}
    active = [telemetry]

    def timed_method(owner, name, counter, timer=None):
        original = getattr(owner, name)
        def wrapped(*args, **kwargs):
            current = active[0]
            current["counts"][counter] = current["counts"].get(counter, 0) + 1
            start = time.perf_counter()
            result = original(*args, **kwargs)
            if timer:
                current["timings"][timer] = current["timings"].get(timer, 0.0) + (time.perf_counter() - start) * 1000
            return result
        setattr(owner, name, wrapped)

    timed_method(IslandWorld, "_build_chunk", "chunk_builds", "chunk_build_ms")
    timed_method(IslandWorld, "_unload_chunk", "chunk_unloads", "chunk_unload_ms")
    timed_method(Civilian, "step", "npc_updates")
    timed_method(DestructibleEntity, "step", "object_physics_steps")
    timed_method(TrafficVehicle, "step", "traffic_updates")

    active[0] = {"counts": {}, "timings": {}}
    original_update = game.update
    def measured_update(dt=None):
        start = time.perf_counter()
        result = original_update(dt)
        current = active[0]
        current["counts"]["game_updates"] = current["counts"].get("game_updates", 0) + 1
        current["timings"]["game_update_ms"] = current["timings"].get("game_update_ms", 0.0) + (time.perf_counter() - start) * 1000
        return result
    game.update = measured_update
    app.taskMgr.step()  # finish window/lens initialization before sampling

    scenarios = [
        ("empty_coastline", 0, 4_600, 0, "ground"),
        ("downtown", 0, 0, 0, "ground"),
        ("dense_forest", -3_000, 0, 0, "ground"),
        ("residential", 2_500, 0, 0, "ground"),
        ("busy_traffic", 0, 0, 0, "ground"),
        ("ground_movement", 0, 0, 0, "move"),
        ("super_speed", 0, 0, 0, "speed"),
        ("flight_100m", 0, 0, 100, "flight"),
        ("flight_300m", 0, 0, 300, "flight"),
        ("flight_500m", 0, 0, 500, "flight"),
        ("maximum_speed_flight", 0, 0, 100, "flight_max"),
        ("building_destruction", 0, 0, 0, "destruction"),
        ("repeated_powers", 0, 0, 0, "powers"),
        ("multiple_simultaneous_explosions", 0, 0, 0, "explosion_burst"),
        ("ground_punch", 0, 0, 0, "ground_punch"),
        ("large_ground_impact", 0, 0, 0, "ground_impact"),
        ("building_collision_low", 0, 0, 0, "collision_low"),
        ("building_collision_medium", 0, 0, 0, "collision_medium"),
        ("building_collision_max", 0, 0, 0, "collision_max"),
        ("chain_reaction", 0, 0, 0, "chain_reaction"),
        ("terrain_chunk_streaming", 0, 0, 0, "terrain_stream"),
    ]
    requested_scenarios = {name.strip() for name in
                           os.environ.get("SENTRY_BENCH_SCENARIOS", "").split(",")
                           if name.strip()}
    if requested_scenarios:
        scenarios = [scenario for scenario in scenarios
                     if scenario[0] in requested_scenarios]
        if not scenarios:
            raise ValueError("SENTRY_BENCH_SCENARIOS did not match any benchmark scenario")
    results = []
    for name, x, z, altitude, mode in scenarios:
        row = {"name": name, "counts": {}, "timings": {}}
        active[0] = row
        game.super_speed.enabled = mode == "speed"
        if mode == "speed":
            game.sentry.super_speed_enabled = True
        else:
            game.sentry.super_speed_enabled = False
        held_keys["w"] = mode in ("move", "speed", "flight", "flight_max")
        if mode in ("flight", "flight_max") or mode.startswith("collision_"):
            game.sentry.flight.phase = FlightPhase.CRUISE
        else:
            game.sentry.flight.phase = FlightPhase.GROUNDED
        game.sentry.flight.velocity = SimVec3()
        game.sentry.ground.velocity = SimVec3()
        base_position = (x, game.world.height_at(x, z) + max(.25, altitude), z)
        game.sentry.position = base_position
        for _ in range(20):
            app.taskMgr.step()

        samples = []
        started = time.perf_counter()
        cpu_start = process_metrics()["cpu_100ns"]
        memory_start = process_metrics()
        power_timer = 0.0
        collision_index = 0
        while time.perf_counter() - started < sample_seconds:
            frame_start = time.perf_counter()
            if mode not in ("move", "speed", "flight", "flight_max"):
                game.sentry.position = base_position
            else:
                scenario_speed = (700 if mode == "flight_max" else
                                  420 if mode == "speed" else 35)
                game.sentry.position = (base_position[0] + min(700, (time.perf_counter() - started) * scenario_speed),
                                        base_position[1], base_position[2])
            if mode == "destruction" and power_timer <= 0:
                game.world.damage_nearby(SimVec3(*base_position), 1_000, radius=180)
                power_timer = .25
            elif mode == "powers" and power_timer <= 0:
                game.input("c")
                game.heat_vision.update(1 / 60, True)
                power_timer = .4
            elif mode == "explosion_burst" and power_timer <= 0:
                game.world._acquire_explosion(SimVec3(*base_position), 36.0, 2.8)
                power_timer = .12
            elif mode == "ground_punch" and power_timer <= 0:
                game.ground_punch()
                power_timer = .5
            elif mode == "ground_impact" and power_timer <= 0:
                game.ground_impact(SimVec3(*base_position))
                power_timer = .8
            elif mode.startswith("collision_") and power_timer <= 0:
                targets = [obj for obj in game.world.buildings
                           if obj.enabled and not obj.health.broken]
                if targets:
                    target = targets[collision_index % len(targets)]
                    collision_index += 1
                    speed = {"collision_low": 18.0, "collision_medium": 40.0,
                             "collision_max": 120.0}[mode]
                    floor = game.world.height_at(target.x, target.z)
                    start_pos = SimVec3(target.x - abs(target.scale_x) * .5 - 4.0,
                                        max(floor + 1.0, target.y), target.z)
                    end_pos = SimVec3(start_pos.x + 8.0, start_pos.y, start_pos.z)
                    game.sentry.flight.phase = FlightPhase.CRUISE
                    game.sentry.flight.velocity = SimVec3(speed, 0.0, 0.0)
                    game.sentry.position = (end_pos.x, end_pos.y, end_pos.z)
                    game.world.resolve_sentry(game.sentry, previous_position=start_pos)
                power_timer = .32
            elif mode == "chain_reaction" and power_timer <= 0:
                game.world.damage_nearby(SimVec3(*base_position), 2_400,
                                          radius=120.0, impulse=50.0)
                power_timer = .65
            elif mode == "terrain_stream" and power_timer <= 0:
                point = SimVec3(*base_position)
                game.world.terrain_impact(point, radius=10.0, depth=1.0,
                                          intensity=1.2, surface="benchmark")
                game.sentry.position = (base_position[0] + 520.0,
                                        base_position[1], base_position[2])
                power_timer = .65
            power_timer -= 1 / 60
            app.taskMgr.step()
            samples.append((time.perf_counter() - frame_start) * 1000)
        elapsed = time.perf_counter() - started
        cpu_end = process_metrics()["cpu_100ns"]
        memory_end = process_metrics()
        ordered = sorted(samples)
        row.update({"frames": len(samples), "elapsed_seconds": elapsed,
                    "average_fps": len(samples) / max(elapsed, 1e-9),
                    "frame_ms_mean": statistics.fmean(samples),
                    "frame_ms_p95": ordered[min(len(ordered)-1, int(len(ordered)*.95))],
                    "one_percent_low_fps": 1000 / max(ordered[min(len(ordered)-1, int(len(ordered)*.99))], .001),
                    "process_cpu_percent_one_core": (cpu_end - cpu_start) / 100_000 / max(elapsed, 1e-9),
                    "working_set_mb": memory_end["working_set_mb"],
                    "private_mb": memory_end["private_mb"],
                    "working_set_delta_mb": memory_end["working_set_mb"] - memory_start["working_set_mb"],
                    "active_chunks": len(game.world.chunks),
                    "active_objects": len(game.world.objects),
                    "active_npcs": len(game.world.civilians),
                    "active_traffic": len(game.world.traffic),
                    "active_debris": len(game.world.debris),
                    "pooled_debris": len(game.world._debris_pool),
                    "active_explosions": len(game.world._active_explosions),
                    "terrain_craters": len(game.world.terrain_impacts),
                    **scene_geometry(application.base, scene)})
        row["counts"].setdefault("npc_updates", 0)
        row["counts"].setdefault("traffic_updates", 0)
        row["counts"].setdefault("object_physics_steps", 0)
        for key in ("game_update_ms", "chunk_build_ms", "chunk_unload_ms"):
            if key in row["timings"]:
                row["timings"][key] = round(row["timings"][key], 2)
        results.append(row)
        if name in {"downtown", "dense_forest", "flight_500m",
                    "ground_punch", "large_ground_impact", "building_collision_max",
                    "chain_reaction"}:
            screenshot_dir = project_root / "screenshots" / "performance"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            application.base.graphicsEngine.renderFrame()
            screenshot_path = screenshot_dir / f"{game.settings.quality}_{name}.png"
            native_path = Filename.fromOsSpecific(str(screenshot_path))
            if application.base.screenshot(native_path, defaultFilename=False) is None:
                raise RuntimeError(f"Could not save benchmark screenshot for {name}")
        print(f"{name}: {row['average_fps']:.1f} fps, p95={row['frame_ms_p95']:.1f} ms, RAM={row['working_set_mb']:.0f} MB, entities={row['scene_entities']}, chunks={row['active_chunks']}", flush=True)

    held_keys["w"] = False
    output = Path(os.environ.get("SENTRY_BENCH_OUTPUT", "tools/performance_results.json"))
    output.write_text(json.dumps({"quality": game.settings.quality,
                                  "duration_per_scenario": sample_seconds,
                                  "isolated_save_path": str(save_root),
                                  "resolution": resolution,
                                  "geometry_method": "Panda GeomNode traversal; geoms are a draw-call upper bound",
                                  "gpu_utilization": "not captured; broad Windows GPU Engine counter query timed out",
                                  "scenarios": results}, indent=2), encoding="utf-8")
    print(f"Wrote {output.resolve()}")
    application.base.userExit()
    _bench_game = None


if __name__ == "__main__":
    main()
