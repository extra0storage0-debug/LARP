# Sentry performance optimization report

**Run date:** 2026-11-02  
**Optimized run:** Low quality, 1600×900, 2 seconds per scenario, windowed Ursina/Panda3D run  
**Save safety:** Benchmark and smoke-test runs used temporary `LOCALAPPDATA` directories. The existing LocalAppData destruction save was not opened or modified.

## Results

| Scenario | Baseline FPS | Optimized FPS | Baseline P95 frame ms | Optimized P95 frame ms | Baseline RAM MB | Optimized RAM MB | Entities, before → after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Empty coastline | 39.2 | 47.1 | 33.6 | 31.0 | 267 | 276 | 1,349 → 287 |
| Downtown | 21.8 | 36.6 | 60.6 | 38.9 | 287 | 282 | 2,035 → 756 |
| Dense forest | 22.6 | 31.7 | 57.3 | 48.9 | 292 | 289 | 2,539 → 750 |
| Residential | 23.6 | 42.1 | 58.2 | 35.5 | 298 | 289 | 2,760 → 472 |
| Busy traffic | 14.9 | 22.7 | 79.2 | 54.5 | 328 | 298 | 3,446 → 756 |
| Ground movement | 13.1 | 26.9 | 95.6 | 45.0 | 329 | 298 | 3,446 → 775 |
| Super-speed | 12.6 | 27.3 | 150.8 | 72.5 | 344 | 308 | 3,948 → 778 |
| Flight at 100 m | 9.4 | 27.3 | 293.6 | 49.4 | 385 | 329 | 5,018 → 783 |
| Flight at 300 m | 8.5 | 26.2 | 337.5 | 49.5 | 413 | 346 | 5,880 → 766 |
| Flight at 500 m | 8.3 | 22.7 | 342.5 | 61.5 | 444 | 365 | 6,742 → 766 |
| Building destruction | 7.2 | 22.9 | 364.5 | 60.6 | 465 | 373 | 7,210 → 826 |
| Repeated powers | 7.5 | 21.3 | 157.5 | 58.6 | 465 | 373 | 7,210 → 823 |

The baseline artifact records Low quality and a 1.5-second sample, but it did not record the window resolution. The optimized run used 1600×900. The FPS/P95 comparison therefore shows the direction and scale of the improvement, but is not a perfectly controlled same-resolution comparison. Run durations also differ. The optimized primary target of a stable 30 FPS is reached in several cases, but **not** consistently in traffic, fast flight, destruction, or repeated powers.

## Implemented changes

- Fixed chunk unloading to destroy Ursina entities and their child wrappers, rather than removing only the Panda node. This addresses the measured growth from 1,349 to 7,210 live scene entities during the baseline route; optimized runs stayed below 830.
- Added chunk spatial buckets for object damage, building proximity, Sentry collision, and moving-object collision. These paths now inspect local candidates instead of scanning every interactive object.
- Added district-wide batched distant LOD meshes, split into 16 sectors. Detailed active chunks are excluded from their sector proxy meshes to avoid duplicate rendering; dirty sector refresh is spread over frames.
- Reduced Low terrain mesh resolution while retaining the same 10 km × 10 km island bounds, district layout, 500 m flight limit, and loaded detail radius.
- Added distance-aware pedestrian visual/simulation LOD and lower-frequency distant traffic updates. Low NPC capacity follows the existing setting rather than growing as chunks stream.
- Skipped physics/update work for anchored static objects, bounded debris count and physics cadence by quality, and fully destroy expired effects/debris.
- Scheduled aim collision queries at 30 Hz on Low, 45 Hz on Medium, and 60 Hz on High. Grab/freeze input forces an immediate query, and heat vision keeps per-frame aim updates.
- Set Low window resolution to 1600×900 to match the requested target. Low shadows remain disabled; higher presets retain shadows and greater terrain/environment detail.

## Validation

- Created a full pre-change backup at [superman_python_backup_before_performance_2026-11-02](</C:/Users/raoha/OneDrive/Desktop/man of steel/superman_python_backup_before_performance_2026-11-02>).
- `python -m compileall -q .`: passed.
- `python -m unittest discover -s tests`: 112 tests passed.
- `python main.py --smoke-test`: passed. This exercised streaming, movement, super-speed, takeoff, flight, landing, bounds, altitude, camera, heat vision, freeze breath, HUD, and settings initialization.
- Windowed Low/Medium/High transitions passed with the expected resolutions (1600×900, 1920×1080, 1920×1080), terrain detail levels, and Low-versus-higher shadow setting. The test stubbed settings persistence and did not alter `settings.json`.
- Launched the windowed game for the on-screen 12-scenario benchmark at 1600×900 and captured gameplay views: [startup](</C:/Users/raoha/OneDrive/Desktop/man of steel/superman_python/screenshots/performance/startup.png>), [downtown](</C:/Users/raoha/OneDrive/Desktop/man of steel/superman_python/screenshots/performance/downtown.png>), and [500 m flight](</C:/Users/raoha/OneDrive/Desktop/man of steel/superman_python/screenshots/performance/flight_500m.png>).
- Raw baseline and optimized samples: [performance_baseline.json](</C:/Users/raoha/OneDrive/Desktop/man of steel/superman_python/tools/performance_baseline.json>) and [performance_optimized_final.json](</C:/Users/raoha/OneDrive/Desktop/man of steel/superman_python/tools/performance_optimized_final.json>).

## Measurement limits and remaining bottlenecks

- Windows GPU Engine counter collection timed out, so GPU utilization and shared GPU memory were not measured. Panda3D's available adapter data did not expose them either.
- `geom_nodes` and `draw_call_upper_bound` are scene traversals, not GPU draw-call counters. The benchmark records triangle counts, but cannot attribute them to a specific frame's submitted draw calls.
- CPU use remained about 84–97% of one logical core in sampled scenes, indicating the remaining bottleneck is largely Python/simulation-side. Chunk generation still happens synchronously when fast travel crosses chunk boundaries, and destruction remains a high-cost workload.
- Distant vegetation/buildings are combined into sector meshes, but near trees remain separate damageable objects; dedicated GPU hardware instancing, asynchronous chunk generation, and pooled vehicles/NPCs were not added. The benchmark also does not provide reliable long-duration 1% lows: a 2-second sample has too few frames for a stable tail statistic.
- The Low, Medium, and High settings are covered by the existing preset tests, but the final on-screen performance benchmark exercised Low only. Results vary with thermal and background load; the stated measurements are not a performance guarantee.
