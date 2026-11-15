# Sentry fast-flight performance report

## Summary

The main profiled cost is deterministic chunk generation: each new 500 m chunk samples terrain repeatedly while placing grass and trees. The first visit to a chunk still builds synchronously, so this change does not eliminate first-visit frame spikes. It does avoid regenerating natural chunk data when a high-speed route returns to recently visited areas.

The repeated-route cache is bounded to 48 chunks, is used only for the current natural-only island, and is invalidated when terrain is deformed or graphics quality changes. Cached data contains deterministic vegetation geometry and tree placement only; scene entities and colliders are recreated through the existing main-thread world path. The character, controls, physics, flight limit, camera, powers, settings, island dimensions, and save data were left unchanged.

## Checkpoint

Full project backup created before source edits:

`C:\Users\raoha\OneDrive\Desktop\1000 moggin suns\SENTRY_backup_before_fast_flight_2026-11-02`

## Profiling and measurements

The pre-change focused windowed probe ran at 1600×900 on the Low preset. It used real movement and boosted flight, sampled for six seconds per row, and recorded frame time, game-update duration, chunk builds, and memory:

| Scenario | Average FPS | p95 frame | Worst frame | Chunk builds |
|---|---:|---:|---:|---:|
| Walking | 49.7 | 29.3 ms | 50.9 ms | 6 |
| Maximum speed, straight | 45.7 | 42.7 ms | 58.0 ms | 29 |
| Maximum speed, turning | 34.7 | 56.1 ms | 81.5 ms | 58 |

A `cProfile` sample identified repeated terrain-height evaluation during grass placement. Reusing the exact interpolated terrain-mesh heights within each chunk reduced one representative chunk build from 134 ms and 191,456 calls to 65 ms and 102,356 calls (about 51% less measured CPU time). In the updated profile, `height_at()` fell from 5,207 calls to 207; the same-grid vertex cache serves the repeated grass samples. GPU utilization could not be collected reliably from the available Windows GPU Engine counters.

After the change, the eight-second Low repeated-fast-travel probe recorded 31 chunk builds across 45 unloads with the 48-chunk cache, compared with 40 builds in the earlier 12-chunk-cache probe. Chunk-build time fell from 2,120 ms to 1,805 ms between those two short runs. FPS was approximately 19 in both runs, so the cache reduces repeat-route CPU work but did not establish an overall FPS improvement in this test.

The updated eight-second maximum-speed turning probe recorded 20.8 FPS, p95 86.5 ms, and a 117.4 ms worst frame, with 58 chunks built in 1,818 ms total. The previous eight-second turning probe recorded 17.6 FPS, p95 102.6 ms, and a 291.8 ms worst frame, with 49 chunks built in 2,436 ms total. The shorter probes indicate lower per-chunk generation cost and fewer severe frame spikes, but the high-speed performance target is **not yet met**. Results vary between runs and are shorter than the requested 60-second samples.

The benchmark harness is available at [tools/fast_flight_benchmark.py](tools/fast_flight_benchmark.py). Raw focused probe data is in [tools/fast_flight_baseline_probe.json](tools/fast_flight_baseline_probe.json), [tools/fast_flight_cached_repeat_probe48.json](tools/fast_flight_cached_repeat_probe48.json), and [tools/fast_flight_terrain_sampling_after.json](tools/fast_flight_terrain_sampling_after.json).

## Files changed

- `world/island_generator.py` — bounded natural-chunk data cache, reuse on reload, quality and crater invalidation, and cached terrain-grid sampling during grass placement.
- `tools/fast_flight_benchmark.py` — focused real-flight scenarios, frame-time and chunk telemetry, isolated destruction save, and per-quality/1600×900 controls.
- `FAST_FLIGHT_PERFORMANCE_REPORT.md` — this report.

## Validation

- `python -m compileall -q .` — passed.
- `python -m unittest discover -s tests` — 95 tests passed.
- `python main.py --smoke-test` — passed; movement, super speed, flight, landing, boundaries, altitude, camera, powers, terrain persistence, and chunk reload were exercised.
- Natural chunk cache reload check — passed; moving from the origin to an adjacent chunk and back built 3 new chunks outbound and 0 on return, with 9 active chunks afterward.
- Windowed game startup at 1600×900 — launched during focused probes.
- Full 60-second scenario matrix across Low, Medium, and High — not completed. The windowed benchmark process exited during startup on repeated attempts, and several short runs had inconsistent frame rates. No 60-second FPS or memory claim is made.

## Remaining work

The cache helps repeated routes, but first-time chunk generation can still cause substantial frame spikes. A reliable full-duration windowed benchmark and further optimization of terrain sampling are needed before claiming stable 60 FPS or completion of the requested performance target. The Low/Medium/High 60-second scenario matrix should be rerun after the windowed benchmark lifecycle is stable.
