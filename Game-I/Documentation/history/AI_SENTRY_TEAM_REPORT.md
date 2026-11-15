> **Superseded.** The final specification removed the systems described here. See SENTRY_FINAL_OVERHAUL_REPORT.md.

# AI Sentry team and two-profile configuration report

Date: 2026-11-02. Hardware: Intel Core i5-1335U, Intel Iris Xe, 16 GB RAM.

## Summary

The game now has six AI enemy Sentries (red, purple, blue, green, black and white) that hunt the player as a team, and a settings screen with two profiles, MY SENTRY and COMMON ENEMY SENTRIES.

The fight works end to end in a real window:

- A perfect-aim bot standing still beat all six in 27.9 s, finishing with 8.6 of 100 health.
- A passive player was eliminated in 26.4 s.

All 299 automated tests and the smoke test pass.

**Frame rate is the main shortfall.** With all six enemies active, the game runs at 27–36 FPS at 1600×900 on the Low preset, against 33–49 FPS without them. Neither reaches 60. The AI costs about 3 ms per frame; most of the rest appears to be rendering.

## Decisions to review

| Topic | What happens now | How to change it |
|---|---|---|
| Your 999,999 heat vision damage | Still applies to terrain and trees, but enemies take at most 75 damage per second. Without a cap, one frame would kill an enemy. | Superpowers: **Heat: Damage to Sentries** |
| Your 999,999 ground impact power | Enemies take at most 95 damage, within 42 m | Superpowers: **Ground Impact: Damage** and **Area** |
| Your 9,999 m/s flight speed | Enemy speeds copy yours until the first **Apply & Save**, then the two profiles are independent. The island takes about a second to cross at this speed, which leaves little real fighting in the air. | Flight Advanced, on each profile |
| Permanent island damage | Enemy slams and beams dig craters and burn trees into your save file, like your own powers. There is no in-game reset. | Crater Budget, Crater Size, Terrain Damage and Tree Damage on the enemy profile |
| Freeze duration default | The player's freeze lasts 3 s, down from the original 5 s, so one hit can't remove an enemy for too long. | Superpowers: **Freeze: Duration** |

## What did not exist beforehand

- **Two-profile system:** the request described it as existing, but the project had one page of 8 settings. It was built new.
- **Implementation report:** this file is new; there was no earlier report to update.
- **Other work during this session:** tree destruction (`world/tree_destruction.py` and related edits) appeared at about 11:32, from outside this work. It was kept and built on. **The backup predates it, so restoring the backup would remove it.**

Backup: `SENTRY_backup_before_ai_team_2026-11-02`, verified identical to the project when it was made.

## Enemy team architecture

| Layer | File | Responsibility |
|---|---|---|
| Tactics, with no engine code | `ai/enemy_team_ai.py` | `TeamDirector`: roles, strategy, formation, attack limits. `EnemyBrain`: one enemy's decisions. Steering and aim prediction. `AITuning`: settings in decision units. |
| Character | `characters/enemy_sentry.py` | `EnemySentry` subclasses the player's `SentryCharacter`, so it runs the same flight, ground and posture code. An `EnemyContext` answers its camera, collision and impact calls for that enemy alone. |
| Model copy | `characters/sentry_clone.py` | Copies the player's built model rather than making a new one, and recolours only the costume |
| Team control | `game/enemy_team.py` | Spawning, staggered updates, attacks, damage routing, victory and defeat |
| Powers | `powers/enemy_powers.py` | Subclasses of the real `HeatVision`, `FreezeBreath` and `SuperStrength`, aimed by AI |

**Roles** are reassigned every 2.5 s and immediately after a death: Leader, Interceptor, Attacker, Ranged Attacker, Flanker and Support. Each role holds a different distance and bearing, which produces a surround rather than a line.

**Strategy** switches between Pursue, Encircle and Assault. Each enemy has its own reaction time, aim rate and attack preferences.

### Character colours

Only the costume changes. Skin, face and hair stay shared with the original.

| Enemy | Suit (RGB) | Accent: gloves, boots, belt | Cape |
|---|---|---|---|
| Red | 188, 28, 32 | 74, 6, 12 | 138, 14, 22 |
| Purple | 112, 44, 178 | 40, 12, 76 | 78, 28, 132 |
| Blue | 28, 84, 200 | 8, 26, 84 | 18, 58, 150 |
| Green | 26, 142, 58 | 6, 54, 22 | 16, 102, 44 |
| Black | 30, 31, 36 | 10, 10, 12 | 20, 20, 24 |
| White | 226, 228, 232 | 198, 202, 210 | 216, 219, 226 |

### Powers

| Power | Enemy use | Status |
|---|---|---|
| Flight | Same flight model, including takeoff, landing, pursuit and interception | Working |
| Heat vision | The real beam class. It can miss, and trees block and burn from it. | Working |
| Freeze breath | The real power; slows the player for 1.1 s | Working |
| Super strength | Close-range strikes with knockback | Working |
| Ground impact | Dive attack using the real crater and explosion code, limited to one crater per 12 s | Working |
| Grab and throw | Real code, tested with a crate | **Never triggers in normal play:** the natural island has no grabbable objects, for you or for enemies |
| Super speed | Sprint multiplier setting on ground movement | Working |

### Additions the fight needed

- **Player defeat:** the player had no death state; there is now a defeat screen, and Enter restarts the battle.
- **Airborne strike:** R now hits a nearby enemy while flying. Previously it did nothing in the air.
- **Enemy freeze effect:** being frozen slows the player's movement briefly.

## Configuration

Open with **P**, then **ALL SETTINGS: MY SENTRY / ENEMIES**.

| Category | MY SENTRY | COMMON ENEMY SENTRIES |
|---|---:|---:|
| Camera & Sensitivity | 15 | 2 (AI aim only) |
| Movement & Controls | 13 | 11 |
| Flight Advanced | 14 | 13 |
| Superpowers | 49 | 45 |
| Combat | 8 | 11 |
| AI Behaviour | none | 14 |
| Health & Defence | 11 | 11 |
| Destruction | 12 | 9 |
| Visual & Audio | 11 | 2 |
| Gameplay & Debug | 11 | none |
| Input & Controls | 18 | none |
| **Total** | **162** | **118** |

- **Number entry:** every number is typed directly and saved exactly, with no upper limit. Entry stops at 18 digits. The old 999,999 cap on the original 8 settings is gone.
- **Defaults:** values such as Follow Distance (950 cm = 9.5 m) use whole units so the original camera stays exact. The original camera has no pitch limit, so the pitch limit defaults of ±999,999 mean "no limit".
- **Respawn:** Maximum Health is labelled RESPAWN and applies at the next battle. Everything else applies on Apply & Save.
- **Saving:** settings are stored in `config/sentry_settings.json` (the original 8) and `config/sentry_profiles.json`, which is created on the first save.
- **Keys:** rebinding refuses keys already in use, and P, Esc and Enter are reserved. Resetting the Input & Controls category restores default controls.

### New systems added so settings have something to control

Each defaults to off or no effect, so the original behaviour is unchanged until you set it:

- **Jump:** strength 0 means none.
- **Power energy:** cost 0.
- **Block:** the B key, which was previously unused.
- **Target lock aim assist:** 0%.
- **Motion blur:** 0%, and the filter isn't installed at all at 0.
- **Flight trail:** 0%.
- **Damage numbers and debug readouts:** off.
- **Power sounds:** 0%, except ground impact, which uses its original sound.

### Requested settings not included

| Setting | Reason |
|---|---|
| Environmental Sound Volume | The game has no ambient audio; the only sound file is the impact sample. Adding it would be a control that does nothing. |
| Combat Reaction Time, Evasion Sensitivity, Attack Sensitivity for the player | These describe AI behaviour, so they exist only on the enemy profile |
| Strength, Duration and similar parameters that don't apply to a given power | Your brief asked for "all relevant parameters", so a power only lists the parameters it actually uses. Super Speed, for example, has only its toggle and multiplier. |
| Freeze Area and Flight Impact Force on enemies | There is only one player to spread a freeze to, and enemies never crash-crater, so these would do nothing on that profile. Both remain on MY SENTRY. |

### Settings that have no visible effect yet

**Building Damage** and **Chain Reaction Strength** are connected to real code, but the natural island has no buildings, so you won't see a change today.

## Test results

| Check | Result |
|---|---|
| `compileall` | Passed |
| Unit and integration tests | **299 passed** (202 new) |
| `main.py --smoke-test` | Passed; now also requires all six enemies |
| Windowed gameplay and lineup screenshots | Completed; see `screenshots/ai_team/` |
| `verify_sentry_panel.py` | **Fails, and did before this work.** It expects factory defaults but your saved settings differ; the backup fails at the same check. |
| Your settings file during testing | Unchanged by the tests |

One test fails if any setting in the table isn't read by game code. It only proves a name is referenced somewhere, so the enemy profile was also audited by hand, which found six dead or partial enemy settings: four were fixed and two removed. Behaviour tests cover the main groups below, not every one of the 280 settings individually.

### Requested scenarios

| # | Scenario | Result | Evidence |
|---|---|---|---|
| 1 | All six spawn correctly | Pass | Test: on land, clear of trees, spaced apart |
| 2 | Correct costume colours | Pass | Test and screenshots |
| 3 | Original model | Pass | Test: triangle totals match the player exactly |
| 4 | Working flight | Pass | Test and windowed run |
| 5 | Use existing powers | Pass, except grab and throw in normal play | Tests; windowed attack counts |
| 6 | Detect and pursue | Pass | Windowed: closed to 4–75 m |
| 7 | Team coordination | Pass | Tests: roles and reassignment |
| 8 | Surround the player | Pass | Test: no gap over 200° around the player |
| 9 | Attack only the player | Pass | Test: teammates took no damage |
| 10 | Player can kill enemies | Pass | Windowed: all six killed using real heat vision |
| 11 | Enemies damage the player | Pass | Windowed: player eliminated |
| 12 | Health bars follow | Pass | Test and screenshots |
| 13 | Dead enemies stop | Pass | Test: no movement, damage or targeting |
| 14 | High-speed flight | Pass | Windowed at 9,889 m/s: 13–86 m in cruise, 29–75 m in boost |
| 15 | Acceptable FPS | **Below 60; see below** | Windowed |

### Requested settings checks

| Check | Result | Evidence |
|---|---|---|
| Mouse sensitivity, axes, invert, smoothing | Pass | Tests through the real camera code, with mouse movement simulated |
| Camera defaults unchanged | Pass | Test: 9.5 m, 3.55 m, 82°, and the original turn rates |
| Player camera sensitivity never changes enemy aim | Pass | Test, at 900% on every sensitivity |
| Enemy aim sensitivity never changes the player's camera | Pass | Test |
| Flight controls and profile independence | Pass | Tests |
| AI settings change decisions | Pass | Tests: detection range, retreat, coordination, flanking, prediction, decision rate |
| Power strength, toggles, energy | Pass | Tests |
| Destruction scales | Pass | Tests |
| Health and resistances | Pass | Tests |
| Large values saved exactly across restart | Pass | Test: 987654321012345678 |
| Keybindings | Pass | Tests: rebind, conflict, reserved keys, restore |

## Performance

Measured in a real window at 1600×900 on the Low preset, with your settings (flight speed 9,999, boost 1,111). The final settings audit came after these runs; its fixes only add checks to settings that are off or at default, so the numbers weren't re-measured. A bot pressed keys through the game's input state and aimed by turning the camera. Solo was measured before and after the team run to catch thermal drift.

| Scenario | Solo, before | Solo, after | Six enemies | 1% low | Worst frame |
|---|---:|---:|---:|---:|---:|
| Ground, surrounded | 49.0 | 47.6 | **33.9** | 22.7 | 57 ms |
| Flight, cruise | 37.1 | 39.4 | **34.7** | 16.5 | 118 ms |
| Flight, boost | 34.9 | 33.3 | **27.5** | 15.1 | 75 ms |
| Killing all six | n/a | n/a | **29.3** | 17.8 | 123 ms |
| Fair fight, player winning | n/a | n/a | **29.9** | 18.7 | 69 ms |
| Passive player eliminated | n/a | n/a | **36.2** | 23.1 | 59 ms |

- **AI cost:** the team update takes 2.4–3.2 ms per frame.
- **Vsync:** vsync is on, so a frame just over 16.7 ms waits for the next refresh. That makes small costs look larger in average FPS.
- **Not measured:** Medium and High presets, which add shadows, and GPU utilisation.

### Sharing and optimisation

| Item | Six plain copies | As built |
|---|---|---|
| Triangles per enemy | 75,510 | About 75,500 within 18 m, about 24,000 beyond |
| Draw calls per enemy | 83 | About 31 within 18 m, about 11 beyond |
| Cape | Rebuilt in Python, 1.2 ms per frame each | Deformed on the GPU with the same formula |
| Collision | 0.5 ms per enemy | Cached per chunk and skipped above the trees |

Face and hair geometry is shared by all six. Decisions are staggered, enemies beyond 350 m use a reduced simulation, and only 2 beams can run at once on Low (3 on High).

## Known limitations

1. **FPS:** below 60 in every scenario, including solo. The next gains would likely come from lower-poly models close up or fewer active enemies.
2. **No human playtest:** all windowed runs used a bot. Real mouse movement, clicking through the settings screen by hand, and game feel haven't been tried.
3. **Audio not verified by ear:** the sound code runs, but nobody has listened to the volume settings. All power sounds reuse the one impact sample.
4. **Grab and throw:** works in tests but has nothing to act on in the natural island.
5. **Motion blur:** it is a simple radial speed blur. It was confirmed to turn on and off in a real window, but it wasn't seen at speed or measured for FPS.
6. **Unexplained silent exits:** two benchmark processes ended with exit code 0 and no results. It didn't recur in the later runs, and the cause is unknown. Your earlier `FAST_FLIGHT` report describes a similar exit.
7. **Frame spikes:** worst frames reach about 120 ms in flight and combat. New terrain chunks are a known source; enemy craters may add to it.
8. **Camera blocking:** enemies can stand between the camera and the player, as seen on the defeat screen, because they deliberately don't push the camera in.
9. **Extreme values:** every number is saved exactly, but very large values may make physics behave strangely, since physics uses decimal numbers.
10. **Existing HUD issue, not changed:** the health bar's background and fill are misaligned.

## Files changed

**New**
- `ai/enemy_team_ai.py`
- `characters/enemy_sentry.py`, `characters/sentry_clone.py`
- `combat/sentry_combat.py`
- `config/sentry_profiles.py`
- `game/enemy_team.py`
- `powers/enemy_powers.py`
- `ui/enemy_team_ui.py`, `ui/profile_settings_page.py`, `ui/debug_overlay.py`, `ui/visual_effects.py`
- `tests/test_enemy_team_ai.py`, `tests/test_enemy_team_integration.py`, `tests/test_sentry_profiles.py`
- `tools/ai_team_benchmark.py`, `tools/ai_team_visual_check.py`, and the `tools/ai_team_low_*.json` results
- `screenshots/ai_team/`

**Changed**
- `characters/sentry.py`
- `config/sentry_config.py`
- `game/camera_manager.py`, `game/controls.py`, `game/effects.py`, `game/game_manager.py`, `game/input_manager.py`
- `main.py`, `README.md`
- `movement/flight_physics.py`
- `powers/freeze_breath.py`, `powers/heat_vision.py`
- `ui/config_panel.py`, `ui/hud.py`
- `world/destructible_props.py`, `world/destruction_math.py`, `world/island_generator.py`

## Reproducing

```powershell
.\.venv\Scripts\python.exe -m compileall -q .
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe main.py --smoke-test
.\.venv\Scripts\python.exe tools\ai_team_benchmark.py
.\.venv\Scripts\python.exe tools\ai_team_visual_check.py
```

For a solo baseline, set `$env:SENTRY_ENEMY_TEAM = "0"` before running the benchmark.
