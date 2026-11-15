# Sentry aesthetic and performance report

Date: 2026-11-02. Hardware: Intel Core i5-1335U, Intel Iris Xe, 16 GB RAM.

The game now has one art direction, a warm late-afternoon stylised look, and runs faster than before. The biggest speed gain came from fixing a CPU bottleneck, not from cutting visuals.

## Visual changes

| Area | Change | Cost |
|---|---|---|
| Terrain | Painted meadow patches, rock on steep slopes, beaches blending into grass; sun and cool shade baked into vertex colours | None per frame |
| Trees | Two stacked cones, dark below and sunlit at the tips | 14 triangles per tier |
| Grass | Colour gradient from root to tip | None per frame |
| Wind | Grass and nearby trees sway in the vertex shader; distant trees stay still | One shared value |
| Sky | One dome with a colour gradient, sun glow and soft clouds from a baked noise tile | Two texture reads per sky pixel |
| Water | One surface with shallows, a foam line at the shore, smooth ripples, reflection tint and sun glints | One shader, no textures |
| Atmosphere | Fog fading into the sky's horizon colour; warm light and cool shade grading on all lit objects | A few shader lines |
| Shadows | Softer and neutral on Medium and High, with 4 samples per pixel instead of 16 | Lower than before |
| HUD | Readable panel over bright sky, aligned bars, dimmer help text | One extra quad |
| Camera | Smaller shake values (nothing triggers shake now) | None |

The effects work (soft glows, a new shockwave ring and softer craters) is mostly unseen now, because the final specification removed all powers and explosions. Character work is in `SENTRY_FINAL_OVERHAUL_REPORT.md`.

## Performance fixes

| Fix | Result |
|---|---|
| Removed Ursina re-sending the camera position to about 480 objects every frame | **About 28 to 44 FPS** with vsync off, same scene and session; engine step about 27 to 16 ms |
| Sky and wind values use shared arrays instead of changing state on the scene root each frame | Avoids a scene-wide state change every frame; the cost that removed wasn't measured separately |
| 4 shadow samples instead of 16 per pixel | Not isolated; Medium and High only |
| Removed powers, combat AI, health bars and beams | Not isolated |

Hiding the sky or water changed FPS by only about 1–4 in a test where frame rate was limited elsewhere, so they are cheap. Resolution barely changed FPS (640×360 was about the same as 1600×900), so this game is limited by CPU work, not by pixels.

## Benchmarks

Real window on default settings.

| Preset, 1600×900 | Before: idle ground | Before: fast traversal | After: idle ground | After: fast flight |
|---|---:|---:|---:|---:|
| Low | 29.0 | 21.6 | 49.6 | 49.8 |
| Medium | 19.4 | 14.9 | 48.5 | 47.3 |
| High | 24.1 | 16.7 | 46.0 | 44.6 |

**This is not a pure measure of the art work:**
- "Before" still had combat AI and four attacking enemies, and "after" has no combat.
- "Before" was probably on battery: the laptop was discharging when checked shortly afterwards, and the power state wasn't logged for that run. "After" was on mains power.
- The two flight tests differ slightly: "before" forced 160 m/s, while "after" held the real boost key.

The earlier direct comparison, with the art changes but before the bottleneck fix, was alternating before and after runs on Low: idle 28–30 vs 27–29 FPS, combat 21–22 vs 19–21 FPS. So at that stage the visuals cost little or nothing measurable.

| Worst frames and memory | Low | Medium | High |
|---|---:|---:|---:|
| Fast flight worst frame | 54 ms | 100 ms | 169 ms |
| Extended session worst frame | 41 ms | 90 ms | 257 ms |
| Peak memory, after | 552 MB | 606 MB | 684 MB |
| Starting memory, before | 402 MB | 514 MB | 637 MB |
| Starting memory, after | 519 MB | 577 MB | 615 MB |
| Memory change in extended session | -5.7 MB | -6.1 MB | -1.9 MB |

No memory growth showed up over the 32-second extended session. A session of hours hasn't been tested.

## Not done

- **Sunrise, sunset and day/night:** the game has one fixed time of day, since no cycle existed to build on.
- **True ambient occlusion and reflections:** only painted shading and a reflection tint.
- **Instancing:** vegetation stays batched per chunk rather than GPU-instanced.
- **Fast-flight spikes on Medium and High:** see limitation 1 in the final report.
- **Flicker and clipping:** only sampled through screenshots and scripted runs. Nobody has watched it in long play, so "no glitches" isn't proven.
- **Colour taste:** I judged this from screenshots. Your eye on the moving game is the real test.
