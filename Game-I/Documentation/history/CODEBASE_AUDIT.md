# Sentry project architecture

## Active runtime

`main.py` launches the Sentry open-world superhuman simulation on JEFFREY EPSTEIN ISLAND. `GameManager` composes the existing Sentry character, movement and flight, powers, camera, lighting, HUD, settings panel, pause menu, and active world. `WorldManager` starts `IslandWorld`, which streams deterministic local districts around Sentry.

## Source areas

| Area | Main files | Responsibility |
| --- | --- | --- |
| Startup and coordination | `main.py`, `game/game_manager.py`, `game/world_manager.py` | Ursina startup, input routing, system updates, and world ownership. |
| Sentry character | `characters/sentry.py`, `characters/sentry_shader.py` | The preserved playable model, animation, controller, and character shading. |
| Camera and movement | `game/camera_manager.py`, `game/island_frame.py`, `game/input_manager.py`, `movement/*.py` | Third-person camera, shared input, flight/ground motion, and island coordinates. |
| Powers and damage | `powers/*.py`, `combat/damage_system.py`, `world/destructible_props.py`, `world/interactive_objects.py` | Heat vision, freeze breath, strength, super speed, damage, and bounded debris. |
| Island world | `world/island_generator.py`, `world/buildings.py`, `world/city_generator.py`, `world/vehicles.py` | Streamed island terrain, districts, buildings, traffic, and reusable world generation. |
| UI and configuration | `ui/*.py`, `config/*.py`, `settings.json` | Sentry HUD, pause/settings panels, graphics preferences, and ability settings. |
| Tests and tools | `tests/*.py`, `Documentation/*.py`, `tools/*.py` | Automated checks, reproducible captures, benchmarks, and optional geography preparation. |

The active runtime is island-based. Planetary source, Earth data, related tools and planetary-only tests are archived under `Delete/space_simulation/`; shared island-frame math and active lighting remain in the runtime.

## Saved data and identity migration

Graphics settings remain in `settings.json`; ability settings remain in `config/sentry_settings.json`. World damage remains in `%LOCALAPPDATA%\Sentry\island_destruction.json`. These files do not contain legacy identity keys or character identifiers, so the rebrand does not rewrite, reset, or migrate their contents. Existing world object IDs are unchanged.

## Verification

Run `python -m compileall -q .`, `python -m unittest discover -s tests -v`, and `python main.py --smoke-test` from the project root. This workspace has no Git repository metadata. A complete pre-rebrand backup was created beside the project.
