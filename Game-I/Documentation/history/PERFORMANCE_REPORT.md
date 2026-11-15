# Sentry Performance Audit and Optimization Report

Date: 2026-11-02

## Measurement setup

- Machine: Intel Core i5-1335U with Intel Iris Xe integrated graphics, 16 GB RAM.
- Benchmark: existing `tools/performance_benchmark.py`, windowed 1600x900, Low quality, six 2-second scripted scenarios. It used isolated temporary save files.
- CPU is reported as process utilization relative to one logical core. Geometry count is a Panda `GeomNode` traversal and an upper bound for draw calls, not a GPU hardware counter.
- GPU utilization was unavailable: the broad Windows GPU Engine counter query timed out. Therefore this pass identifies a CPU-side bottleneck but does not claim a measured GPU bottleneck.
- Short runs are noisy and do not provide reliable sustained 1% lows or long-term memory-leak conclusions.

## Baseline and final measurements

| Scenario | FPS before → after | P95 frame time before → after | Working set before → after |
|---|---:|---:|---:|
| Downtown / idle | 33.7 → 59.0 | 37.2 → 18.4 ms | 355 → 354 MB |
| Dense forest | 39.8 → 45.1 | 30.6 → 32.4 ms | 365 → 361 MB |
| Ground movement | 14.4 → 38.7 | 145.2 → 32.7 ms | 379 → 365 MB |
| Super speed | 27.0 → 54.9 | 103.6 → 30.4 ms | 379 → 367 MB |
| Flight at 500 m | 27.7 → 47.2 | 51.8 → 30.5 ms | 378 → 367 MB |
| Terrain streaming | 18.9 → 29.9 | 198.2 → 73.1 ms | 379 → 375 MB |

Other comparisons:

- Ground movement averaged 69.3 ms/frame before and 25.8 ms/frame after.
- Terrain sector `GeomNode` count decreased from 431 to 242 in the downtown/ground scenarios (about 44%). The measured triangle count stayed in the same range; terrain sample density was not reduced.
- Process CPU remained high (roughly 81–97% of one core after the change), consistent with a CPU-bound update/streaming path.
- In movement/streaming scenarios, `_build_chunk` calls fell from as many as 150 in two seconds to 8–12. Chunk generation remains synchronous and still produces noticeable streaming hitches.
- Working set stayed roughly 354–375 MB after the change. Per-scenario two-second deltas ranged from 0 to about 3 MB after warmup; this short sample cannot establish leak-free behavior over long sessions.

Raw measurements: `tools/performance_cleanup_baseline.json` and `tools/performance_cleanup_optimized_final.json`.

## Bottleneck findings and changes

The baseline showed the main hitch came from repeated distant vegetation LOD rebuilds during chunk streaming: a 2-second sample could trigger roughly 150 `_build_chunk` calls and spend about 931 ms in chunk building during ground movement. The game also created 256 small terrain-sector meshes, adding scene nodes and draw overhead.

Changes were limited to `world/island_generator.py`:

1. In natural-only mode, distant LOD remains static while nearby detailed chunks stream. This prevents rebuilding the same distant LOD mesh on every chunk transition while keeping the same island coverage and deterministic tree layout.
2. Terrain sector grouping changed from 16×16 sectors to 8×8. Terrain sampling/triangle detail and deformation math are retained; fewer larger meshes reduce node/draw submission overhead.

The LOD change brought ground movement from 14.4 FPS / 145.2 ms P95 to 35.0 FPS / 31.7 ms P95 before terrain batching. Final batching reached 38.7 FPS / 32.7 ms P95 for that short scenario. The dense-forest P95 varied slightly upward between samples, so the short benchmark is not evidence of a universal improvement in every condition.

## Verification

- `python -m compileall -q .`: passed.
- `python -m unittest discover -s tests -q`: passed, 121 tests.
- `python main.py --smoke-test`: passed for startup, terrain/persistence, movement, super speed, flight/landing, island boundaries, altitude limit, camera, and powers.
- Six windowed benchmark scenarios completed; screenshots were captured and visually inspected.
- No GPU counter data was captured, and no automated graphics-artifact detector is available in the existing harness.

## Remaining issues

- Terrain chunk creation is still synchronous; terrain-streaming P95 remains about 73 ms and can visibly hitch. Async generation would need a separate design and regression pass.
- CPU saturation remains high in the more demanding scenarios. GPU utilization and actual GPU frame time are not measured by the current harness.
- The benchmark is a short scripted comparison, not a sustained-session memory or stability test. Results should not be generalized as a 60 FPS guarantee.
- No NPC or traffic workload was active in the current natural-island startup, so this run does not measure AI scaling.
