# Hardware and Performance Report

## Test machine

Collected from Windows system inventory during this run:

- CPU: 13th Gen Intel Core i5-1335U, 10 cores / 12 logical processors
- GPU: Intel Iris Xe Graphics, driver 31.0.101.4502
- Installed memory: 15.7 GiB (reported as 16 GB)
- OS: Windows; Ursina 8.3.0 using Panda3D's `wglGraphicsPipe`
- Python: 3.14.7

## Measured result

### Spherical planet milestone (2026-11-01)

Automated six-second render-loop samples after a 60-frame warm-up, with VSync enabled and no movement in the preset comparison. The window reported `SetForegroundWindow() failed`; foreground focus was not confirmed. Worst frame is the longest single frame in the sample, not a rolling one-percent low.

| Preset | Resolution | Frames / duration | Average FPS | Mean `GameManager.update()` | Worst frame | NPCs / vehicles |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Low | 1280×720 | 237 / 6.03 s | 39.29 | 9.98 ms | 55.23 ms | 8 / 6 |
| Medium | 1600×900 | 206 / 6.00 s | 34.32 | 13.14 ms | 80.94 ms | 14 / 6 |
| High | 1920×1080 | 160 / 6.01 s | 26.64 | 18.48 ms | 80.77 ms | 22 / 6 |

The scripted Low flight sample used F takeoff, W/Shift acceleration and D steering for six seconds: 172 frames / 6.02 s, 28.56 FPS, 11.13 ms mean update, 48.30 ms worst frame, 42.5 m altitude and 1322 km/h. It did not continuously activate destruction or heat vision. The district had 135 buildings, 8 civilians, 6 vehicles and 156 tracked interactive objects. Static geometry is batched, but there is no visibility counter, global chunk streaming, or distance/frustum culling.

These are short automated samples, not sustained benchmarks. Active Low flight did not meet the historical 42 FPS sample, and High idle averaged below 30 FPS. The focus limitation may affect frame pacing.

### Aiming, character blockout, and Sun pass (2026-11-01)

Six-second idle render-loop samples after a 60-frame warm-up, using one `GameManager.update(1/60)` call per rendered frame. VSync was enabled. The window again reported `SetForegroundWindow() failed`, so foreground focus was not confirmed. Minimum FPS is the reciprocal of the single worst measured frame interval, not a rolling one-percent low.

| Preset | Resolution | Frames / duration | Average FPS | Minimum FPS | Mean frame time | Worst frame | Mean manager update |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Low | 1280Ã—720 | 211 / 6.016 s | 35.07 | 13.00 | 28.51 ms | 76.95 ms | 18.06 ms |
| Medium | 1600Ã—900 | 183 / 6.002 s | 30.49 | 10.56 | 32.80 ms | 94.73 ms | 21.63 ms |
| High | 1920Ã—1080 | 141 / 6.021 s | 23.42 | 11.54 | 42.70 ms | 86.62 ms | 30.71 ms |

These are short idle samples from the earlier character blockout with the Sun cycle initialized. They were run after the earlier spherical-planet samples; do not compare them as a controlled before/after because window focus was not confirmed. Active flight, charging/firing heat vision, debris-heavy destruction, and sustained play were not included.

### Full hair and unbounded camera pass (2026-11-01)

Low preset at 1280×720, six-second idle render loop after a 60-frame warm-up. The completed head-attached hair shell and animated locks were enabled. The window reported `SetForegroundWindow() failed`, so foreground focus was not confirmed.

| Frames / duration | Average FPS | Mean frame time | Worst frame | Mean `GameManager.update()` |
| ---: | ---: | ---: | ---: | ---: |
| 238 / 6.007 s | 39.62 | 25.24 ms | 76.45 ms | 20.07 ms |

This is a short automated idle sample on the i5-1335U / Iris Xe system, not a sustained or foreground-focused benchmark. Flight and heat-vision runtime behavior were checked separately, but not timed in this sample.

### Sentry-inspired character pass (2026-11-01)

Low preset at 1280×720, six-second scripted idle render loop after a 60-frame warm-up, with the golden hair and animated cape enabled. Foreground focus was not explicitly verified.

| Frames / duration | Average FPS | Mean frame time | Worst frame | Mean `GameManager.update()` |
| ---: | ---: | ---: | ---: | ---: |
| 237 / 6.012 s | 39.42 | 25.36 ms | 36.39 ms | 20.27 ms |

This short sample includes the slightly larger cape mesh update and the attached hair locks. It does not measure flight or heat vision load and is not a sustained-play guarantee.

### Final gameplay flight benchmark

- Preset/resolution: Low, 1280×720, VSync enabled
- Scenario: scripted cruise at 82 m/s, W/Shift acceleration followed by A/D steering
- Duration/frame count: 6.02 seconds / 175 frames
- Measured average: 29.05 FPS
- Average Python `GameManager.update()` time in the same sample: 11.39 ms
- World content: 135 buildings, 8 Low-preset civilians, 6 vehicles

This is a historical pre-planetary sample. Neither it nor the new samples injected physical mouse movement or sustained heat vision, destruction, or debris.

### Previous baseline (before controls/camera pass)

- Preset/resolution: Low, 1280×720, VSync enabled
- Scenario: four seconds of scripted forward boost followed by Q ground-impact input and landing
- Duration/frame count: 6.12 seconds / 257 frames
- Measured average: 42.0 FPS
- Average Python `GameManager.update()` time in the same sample: 7.18 ms
- Scene entity count: 421, including the Character, HUD, civilians, traffic, and static scene mesh entities
- District content: 135 damageable buildings, 8 Low-preset civilians, 6 vehicles

This short sample is a measurement from the specified machine, not a guarantee for all play states. The planetary milestone now includes separate Medium and High idle measurements above.

## Recommendations

- Keep Low as the first-run preset on Iris Xe. It uses 1280×720, a 360-unit far plane, and 8 civilians.
- Use Medium (1600×900) only after checking frame pacing in flight. High (1920×1080) is optional and performance-dependent.
- Static road, park, lamp, tree, and building façade geometry is batched. Avoid reintroducing per-window or per-road-strip entities.
- Benchmark with boost, heat vision, ground impact, and maximum debris before increasing effects or NPC counts.

### Planetary atmosphere and orbital environment (2026-11-01)

Six-second windowed idle samples after warm-up, with the procedural planet, ocean, cloud and atmosphere shaders and shadow maps active. The benchmark called one `GameManager.update(1/60)` and rendered one frame per sample step. VSync was enabled. The window reported `SetForegroundWindow() failed`; foreground focus was not confirmed. Minimum FPS is the reciprocal of the single worst frame interval, not a rolling one-percent low.

| Preset | Resolution | Frames / duration | Average FPS | Minimum FPS (single worst frame) | Mean frame time | Worst frame | Mean manager update |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Low | 1280 x 720 | 170 / 6.01 s | 28.29 | 17.57 | 35.35 ms | 56.91 ms | 8.07 ms |
| Medium | 1600 x 900 | 146 / 6.01 s | 24.31 | 5.08 | 41.14 ms | 196.90 ms | 10.06 ms |
| High | 1920 x 1080 | 129 / 6.02 s | 21.42 | 7.82 | 46.69 ms | 127.86 ms | 13.06 ms |

The unconfirmed focus and large worst-frame spikes make the minimum-FPS values especially sensitive to this short run. These are measurements from the i5-1335U / Iris Xe system, not sustained-play guarantees. Movement, heat vision, water entry, and destruction were not active during the samples. Repeatable capture and benchmark helpers are in `Documentation/`.


### Current planetary rendering run (2026-11-01)

Six-second windowed idle samples after warm-up, on the same i5-1335U / Iris Xe system. VSync was enabled. The window reported `SetForegroundWindow() failed`, so foreground focus was not confirmed. Minimum FPS is the reciprocal of the single worst frame interval. These latest samples include the local Copernicus mesh and the complete Earth capture path.

| Preset | Resolution | Frames / duration | Average FPS | Minimum FPS | Mean frame time | Worst frame | Mean manager update |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Low | 1280 x 720 | 156 / 6.076 s | 25.67 | 8.89 | 38.95 ms | 112.43 ms | 9.91 ms |
| Medium | 1600 x 900 | 147 / 6.011 s | 24.45 | 17.47 | 40.89 ms | 57.26 ms | 11.15 ms |
| High | 1920 x 1080 | 134 / 6.004 s | 22.32 | 13.04 | 44.81 ms | 76.68 ms | 13.62 ms |

This short capture benchmark is not a sustained gameplay result. Focus loss and the single worst-frame spikes limit interpretation; active flight, heat vision, water entry, and destruction were not included.

### Regional Copernicus tile ingestion run (2026-11-01)

Six-second idle samples after installing the GLO-30 Gurugram tile and GLO-90 reference-location tiles. The benchmark window again reported `SetForegroundWindow() failed`; these are unfocused samples and should not be treated as a controlled before/after result.

| Preset | Resolution | Frames / duration | Average FPS | Minimum FPS (single worst frame) | Mean frame time | Worst frame | Mean manager update |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Low | 1280 x 720 | 97 / 6.043 s | 16.05 | 9.92 | 62.30 ms | 100.76 ms | 17.16 ms |
| Medium | 1600 x 900 | 90 / 6.050 s | 14.88 | 6.76 | 67.22 ms | 147.87 ms | 19.37 ms |
| High | 1920 x 1080 | 75 / 6.088 s | 12.32 | 6.79 | 81.17 ms | 147.23 ms | 24.50 ms |

The eleven installed preprocessed Copernicus tiles occupy 107,520,000 bytes of float32 raster storage (about 102.5 MiB), excluding the local crop and metadata. The runtime LRU remains capped at eight tiles; the largest possible eight-tile raster set from the current assets is about 92.2 MB before small Python object overhead. This is a tile-data bound, not a measured process RSS. The benchmark ran while the window lacked confirmed foreground focus, so its low rates do not establish a terrain-ingestion performance regression. Active flight and streaming are not benchmarked.

### Solar navigation pass (2026-11-01)

Six-second windowed idle samples after the physical course navigation, body shading, and scene visibility updates were added. VSync was enabled; the window again reported `SetForegroundWindow() failed`, so focus was not confirmed. These numbers are poor and are not representative of focused play, but record the actual run rather than assuming the earlier baseline still applies.

| Preset | Resolution | Frames / duration | Average FPS | Minimum FPS (single worst frame) | Mean frame time | Worst frame | Mean manager update |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Low | 1280 x 720 | 60 / 6.038 s | 9.94 | 4.87 | 100.64 ms | 205.15 ms | 25.53 ms |
| Medium | 1600 x 900 | 51 / 6.060 s | 8.42 | 6.49 | 118.82 ms | 154.05 ms | 28.58 ms |
| High | 1920 x 1080 | 40 / 6.007 s | 6.66 | 5.19 | 150.18 ms | 192.53 ms | 35.28 ms |

The sample ran idle on the i5-1335U / Iris Xe laptop with the procedural local world and offscreen solar bodies initialized. It did not sample active interplanetary flight. Performance remains a known limitation and needs focused profiling; this run does not meet a smooth-play target.

## City-runtime cleanup benchmark (2026-11-01)

The active runtime no longer constructs the solar atlas or global Earth render shells. NPC obstacle avoidance uses a local building-cell index; actors beyond 60 m and 180 m update at 20 Hz and 10 Hz respectively. The Low preset no longer renders dynamic Sun shadows, while Medium and High retain them at reduced resolutions. Wildlife is not spawned in the current urban runtime.

The same six-second, stationary, windowed benchmark harness was run before and after cleanup on the i5-1335U / Iris Xe system. `SetForegroundWindow() failed` appeared in these runs, so focus was not confirmed. Results vary between repeats; minimum FPS is the reciprocal of the single worst frame, not a rolling one-percent low.

| Preset | Resolution | Baseline average FPS | Current average FPS | Baseline min FPS* | Current min FPS* | Baseline mean frame | Current mean frame | Baseline mean update | Current mean update | Current worst frame |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Low | 1280×720 | 16.64 | 29.97 | 13.12 | 10.79 | 60.08 ms | 33.36 ms | 13.71 ms | 7.09 ms | 92.65 ms |
| Medium | 1600×900 | 14.34 | 16.51 | 11.70 | 11.56 | 69.73 ms | 60.58 ms | 16.15 ms | 7.19 ms | 86.50 ms |
| High | 1920×1055 actual window** | 9.86 | 17.50 | 4.46 | 15.96 | 101.40 ms | 57.13 ms | 22.80 ms | 6.65 ms | 62.67 ms |

\* Reciprocal of one worst frame, not a rolling one-percent low. **The High preset's window was 1920×1055 because of window decorations; the pre-cleanup sample recorded a nominal 1920×1080.

The benchmark indicates lower Python update time at each preset, but rendered FPS remains below 30 at Medium and High. The latest Low sample was 29.97 FPS; other cleanup repeats ranged from 24.65 to 30.59 FPS. Stable 30 FPS is not established. These measurements are short idle samples and do not cover movement, heat vision, or destruction.

The latest preset runs reported startup times of 1.52/1.45/1.79 seconds (Low/Medium/High), peak working sets of 304.4/341.5/417.3 MiB, and process CPU use of 7.09/7.65/8.06 percent normalized across all logical processors. On this 12-thread system, those CPU percentages are approximately 85/92/97 percent of one logical processor. Peak working set and CPU were not measured in the pre-cleanup run, so no before/after claim is possible for those values.

The current source/assets tree occupies 923,288,949 bytes (about 880.5 MiB), excluding the backup archive, linked virtual environment, and transient Python caches. This is essentially unchanged because retained geography/source assets still dominate project size. The required pre-cleanup backup archive is 714,227,433 bytes; it is not loaded by the game.
