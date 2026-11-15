# NO LIMIT TO LARP

**NO RULES. NO LIMITS. JUST SUPES.**

An expandable, physics-driven character combat sandbox. Different Supes, with their own powers and abilities, fight each other and tear up a 10 km island with lasting destruction. You can take over any of them at any time.

The roster today is Superman, Homelander, Sentry, Omni-Man and Soldier Boy, and it is not closed: each character is one file in `characters/supes/`, and a new one joins by adding a file. See [Adding a character](Documentation/ADDING_A_CHARACTER.md).

Current status, tests and benchmarks are in [`FINAL_REPORT.md`](FINAL_REPORT.md). The world is bounded to the island and to a 500 metre flight ceiling.

## Setup

Double-click `Play No Limit To Larp.bat` to play. To set it up from nothing, you need Python 3.12 or later. From this directory in PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Use `py -3.12` instead if that is your installed version. Quality (Low, Medium, High, Ultra) and window size (1280x720, 1600x900, 1920x1080) are chosen under **Esc > Graphics Settings**. Medium at 1600x900 is the setting measured for this laptop; Ultra is for stronger machines.

## Controls

| Input | Action |
| --- | --- |
| WASD | Walk; fly forward, backward and sideways |
| Mouse | Camera |
| Mouse wheel | Camera zoom |
| Left and right mouse | Nothing in play (they still work in menus) |
| Space | Jump; rise while flying |
| Ctrl | Descend while flying |
| Shift | Run; flight boost |
| F | On the ground: take off (Soldier Boy: super jump). In the air: dive and ground slam |
| Q | Lock onto the nearest enemy, or release the lock; the wheel changes target while locked |
| 8 | Auto Target Lock on or off (also in the pause menu): runs Q's lock every 4 seconds |
| E, R | Nothing |
| T | Stop time for 30 seconds (the player only; AI never does) |
| Tab | Hold for character, ability and team information |
| M | Character Selection and teams: PLAY takes over any character |
| P | Powers & Abilities |
| C | Reset the camera |
| K | Fullscreen |
| Esc | Pause menu: Save Game, Load Game, Graphics Settings, Game Settings, Main Menu |

"Toggle" below means press once to start and press the same key again to stop.

| Key | Superman | Homelander | Sentry | Omni-Man | Soldier Boy |
| --- | --- | --- | --- | --- | --- |
| 1 | Heat Vision (toggle) | Laser Vision (toggle) | Void Form + Shadow Cycle (toggle) | Viltrumites + Invincible, 30 s in every 60 (toggle) | Nuclear Radiation Blast every 3 s (toggle) |
| 2 | High-Speed Attack | High-Speed Attack | High-Speed Attack | High-Speed Attack | Time-Stop High-Speed Flying Punch |
| 3 | Time-Stop Brutality | Time-Stop Brutality | Time-Stop Brutality | Time-Stop Brutality | Time-Stop Aerial Grab + Blast |
| 4 | Time-Stop Brutal Heat Vision Execution | Aerial Laser Execution + Clone Assault | Void Nuclear Execution | Time-Stop Triple Impact + Squad Assault + Burning Throw | Time-Stop Radioactive Nuclear Execution |
| + | Punch | Punch | Punch | Punch | - |
| - | Kick | Kick | Kick | Kick | - |

The main-row `=` key (with or without Shift) and the numpad `+` both punch. Abilities have no cooldown or charge time, and strength, stamina and energy are unlimited. Attacks go for the nearest enemy automatically. **Q** locks a target and turns the camera to follow it, the wheel changes target while locked (it zooms otherwise), and attacks go for a locked enemy first. In flight, W flies exactly where the centre of the screen points, up and down included; S flies the opposite way, Shift boosts, and Space and Ctrl rise and descend when W and S are not held. The four flyers reach ahead when flying forward, up or down, and put their hands on their hips when hovering or flying backward. **T** stops the world for 30 seconds while you keep moving and fighting. **R** does nothing. **P** edits Range, Damage and Speed for each ability, and Health, Healing Speed, Running Speed, Flying Speed and Flight Boost Speed for each character (Soldier Boy has no flying speeds). Range and Speed start at their maximum, Damage and Healing Speed at 20% of their maximum, and Health at the character's own figure; all can be raised to 100%. Characters heal all the time, in and out of combat; at 100% Healing Speed a full bar refills in 10 seconds.

Abilities that lost their key to these controls (such as Kryptonian Vision, Freeze Breath, Energy Projection, Ground Slam, Shield Combat and Shield Defence) are still in the game and AI characters still use them, but a player cannot use them until they are given a key.

## Saves

Teams, the active character, and each character's health and position are in `config/character_roster.json`. Every ability's values are in `config/character_powers.json`; a file from an older version is set aside beside it as `character_powers.before_v3.json`, and its values are not used. General settings are in `config/sentry_settings.json` and `config/sentry_profiles.json`, and graphics in `settings.json`. World damage is in `%LOCALAPPDATA%\Sentry\island_destruction.json`; **Esc > Restore Island Landmarks** rebuilds the buildings, vehicles and boulders.

## Checks

Run from this directory:

```powershell
.\.venv\Scripts\python.exe -m compileall -q .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --smoke-test
```

`tools/run_tests.py` runs the same tests module by module, in parallel, in about 12 minutes; a single process grows past 4 GB. `tools/play_check.py` plays every character in a real window, and `tools/agreed_benchmark.py` is the benchmark.

The headless smoke test covers the island, landmarks, the five characters, abilities, swapping, flight rules, quality keys and terrain damage. `tools/final_window_check.py` plays every power in a real window and records timings; it uses temporary saves, so yours are never touched.

For current project checks and hardware results, see [`Documentation/PLAYTEST.md`](Documentation/PLAYTEST.md) and [`HARDWARE_REPORT.md`](Documentation/history/HARDWARE_REPORT.md). Optional geography asset tools and provenance are described in [`Documentation/EARTH_DATA_SOURCES.md`](Documentation/EARTH_DATA_SOURCES.md).

## Characters

The bodies in `assets/characters/` are baked by `tools/character_pipeline/build_characters.py` from the CC0 MakeHuman base mesh, morph targets and game rig (MPFB2's data folder, set by `SENTRY_MPFB_DATA`). Costumes, hair and beards are defined in `tools/character_pipeline/costumes.py`. The bake needs no paid or external tools, and the game does not need the source data to run. If the baked files are missing, the game falls back to the older built bodies.

## Compiled maths (optional)

`native/sentry_native.dll` is a small Rust module holding the terrain height, terrain painting and cape calculations. The game uses it automatically and needs no setup; if Windows refuses it or it is missing, the game uses the same maths in Python. To rebuild it after changing `native/sentry_native.rs`, run `tools/build_native.py`. Setting `SENTRY_NO_NATIVE=1` turns it off.

## The name, and the old one

This project used to be called SENTRY. Sentry is still a character on the roster. Older reports are in [`Documentation/history/`](Documentation/history/).

Some internal names keep the old word, because changing them would risk breaking save files and working code for no visible gain: save files (`config/sentry_profiles.json`, `config/sentry_settings.json`), the destruction save folder, `SENTRY_*` environment variables, Python modules and classes such as `game.sentry` (the body the player controls), and the project folder itself. None of them appear in the game.

The logo, backdrop and icon are original, drawn by `tools/make_branding.py`. The fonts, Anton and Barlow Condensed, are under the SIL Open Font License; see [`assets/fonts/`](assets/fonts/).
