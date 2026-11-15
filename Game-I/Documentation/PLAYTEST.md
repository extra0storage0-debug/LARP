# NO LIMIT TO LARP playtest notes

## Active build

The active build is the island sandbox. Nearby city, residential, coastal, forest, mountain, and rural chunks stream as Sentry moves. The playable character, camera, HUD, powers, settings, pause, and fullscreen systems remain available. The island boundary and 500 metre flight ceiling remain enforced.

## Controls

| Input | Action |
| --- | --- |
| WASD | Walk; W/S fly forward/backward and A/D fly laterally |
| Mouse / arrow keys | Rotate the camera |
| Space / Home; Ctrl / End | Rise / descend during flight |
| F | Take off or trigger airborne ground impact |
| Shift / Alt | Accelerate / brake during flight |
| Q | Restore the default camera view |
| E | Grab/release an object |
| Period (`.`) | Heat vision or throw a held object |
| C | Freeze the targeted object |
| Z | Toggle ground super speed |
| P | Open Powers & Abilities |
| K | Toggle fullscreen |
| Esc | Pause |
| 1 / 2 / 3 | Select Low / Medium / High quality |

## Manual playthrough checklist

1. Confirm the starting district loads and the character is grounded above the terrain.
2. Walk, run, and toggle ground super speed; check that the camera follows without obstructing movement.
3. Rotate the camera with mouse and arrow keys, then press Q to reset it.
4. Take off, fly horizontally and vertically, descend, and land. Confirm the coastline boundary and 500 metre ceiling.
5. Aim at a building, vehicle, tree, or movable prop. Check damage, heat, freeze, grab/throw, and ground-impact interactions where applicable.
6. Damage an object, travel far enough to unload its chunk, then return and verify its damaged or collapsed state remains. Restart the game to check the saved damage state.
7. Open settings and pause, change a quality preset, and test fullscreen/windowed round-trip.

## Automated checks

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m compileall -q .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --smoke-test
```

The smoke test checks world startup, streamed content, grounding, movement, super speed, flight/landing, camera aim and reset, coastline/altitude limits, powers, and updates. Camera input math has unit coverage for mouse and arrow controls. The scripted smoke test is not a substitute for a complete manual playthrough.

## Scope notes

The island and many of its buildings and props are procedural prototype geometry. Destruction uses staged damage, debris limits, and persistent rubble; it does not yet simulate detailed structural fracture, authored collapse animation, or full building interiors. NPC behavior is lightweight.
