> **Superseded.** The final specification removed the systems described here. See SENTRY_FINAL_OVERHAUL_REPORT.md.

# Sentry time manipulation report

Date: 2026-11-02. Backup: `SENTRY_backup_before_time_stop_2026-11-02` (261 files, hash-verified; excludes `.venv` and `Delete`).

Yellow Sentry can now stop time, walk or fly through the frozen world, grab an enemy, beat them and throw them. When time resumes, the enemy keeps flying and takes impact damage.

## Controls

| Key | Action |
|---|---|
| T | Stop or resume time |
| E | Hold the enemy you're aiming at, or release them |
| R | Start or stop the beatdown |
| Period (`.`) | Throw where you're aiming |
| F | Take off; in the air, land (the dive attack is gone) |
| Shift | Run on the ground; boost in flight |

## How it works

- **One clock (`game/world_clock.py`):** `game.elapsed` is world time and slows with the scale. Yellow Sentry and the camera use real time. AI, cooldowns, physics, debris and effects all run from world time, so nothing jumps on resume. Engine time is never changed.
- **Old player powers:** heat, freeze, ground impact, grab, super speed and strikes no longer respond to input and are hidden from MY SENTRY. The classes stay because enemies share them.
- **Knockback:** beatdown knockback is stored and applied on release, so it starts moving when world time allows.
- **Crashes:** a thrown enemy can hit terrain (a lasting crater), trees, other enemies or the island edge.

## Settings (MY SENTRY > Superpowers)

| Setting | Default |
|---|---|
| World Speed | 1 (= 0.001×; 0 = full pause; maximum 1000 = normal) |
| Time stop duration / cooldown | 10 s / 5 s |
| Only While Key Held | Off |
| Time stop energy use | 0 per second |
| Grab range / aim cone | 150 m / 12° |
| Holding distance / maximum hold / hold cooldown | 7 m / 15 s / 0.5 s |
| Beatdown damage / time between hits / knockback | 12 / 0.18 s / 12 |
| Throw velocity / strength | 140 m/s / 100% |
| Impact damage / blast radius | 50 per 100 m/s / 10 m |

Each power also has an on/off toggle, and the keys can be rebound.

## Test results

Windowed results are from a real 1600×900 window, using the real game and engine loop. A script pressed the keys through the game's handlers.

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Old powers disabled | Pass | Tests |
| 2 | Flight works | Pass | Tests; window |
| 3 | World freezes | Pass | Window: about 0.0045 s of world time in 5.2 s; enemies moved at most 0.11 m |
| 4 | Yellow Sentry controllable | Pass | Window: walked 17 m while stopped |
| 5 | Enemies can't attack | Pass | Tests; window: no damage while stopped |
| 6 | Hold during a stop | Pass | Window |
| 7 | Beatdown damages | Pass | Window: 300 to 180 health |
| 8 | Throw during and after a stop | Pass | Window: 0.17 m drift while stopped, then 564 m flight and 59 impact damage |
| 9 | World resumes correctly | Pass | Window: no time jump |
| 10 | Enemies keep their powers | Pass | Window: 19 attacks after resuming |
| 11 | Settings persist | Pass | Test |
| 12 | No major FPS regression | Pass | See below. Memory was **not measured**, but only a few small objects were added |

Also: compilation and the smoke test pass, and all 363 automated tests pass. Your settings files were unchanged by every run.

### Frame rate

Two 20-second samples per build, in a real window on default settings:

| Build | Average FPS | 1% low |
|---|---:|---:|
| Before | 23.9, 20.6 | 12.8, 10.8 |
| After | 22.1, 22.0 | 9.7, 13.1 |

The difference is within the run-to-run noise. Absolute FPS is below the 27–36 in the earlier AI team report. That wasn't investigated, but the "before" build shows the same drop, so this work didn't cause it.

## Known limitations

- **Desaturation:** this is a grey-blue wash, not a true desaturation filter, which would add a full-screen render pass.
- **Permanent craters:** thrown enemies leave craters in your island save, as requested.
- **Buildings:** the island has no buildings today, so that part of the impact code has nothing to hit.
- **No human playtest:** real mouse feel and game balance are untested.
- **Silent exit:** one run of the check tool ended with no output and no results. It didn't recur, and the earlier AI team report describes a similar exit, so the cause is still unknown.
- **`verify_sentry_panel.py`:** it failed before this work. It also expects eight quick-panel rows, and there are now three.
