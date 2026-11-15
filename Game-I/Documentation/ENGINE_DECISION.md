# Engine decision

**Decision: stay on Python, Ursina and Panda3D for now. Godot 4 is the path if the game outgrows them, and it is proven only for rendering.**

Measured on the target laptop: i5-1335U, Iris Xe, 16 GB.

## Why the question came up

The original build averaged 36 FPS at Low on mains power. The game is limited by one CPU thread, not by the GPU, so lowering the resolution barely helped (720p ran at about the same rate as 1600x900).

## What helped without changing engine

Panda3D's `threading-model Cull/Draw` moves culling and drawing to their own threads. In a 25-second test at Low, it took the game from 38 to 57 FPS and p95 frame time from 34.6 to 20 ms.

## The Godot prototype

`prototypes/godot_spike/` is a rendering test in Godot 4.7.2: five characters, 432,000 primitives, shadows and SSAO. It has no game logic.

| Renderer | 1600x900 | 1280x720 | Frames over 100 ms |
|---|---|---|---|
| Mobile | 343 FPS | 460 FPS | none |
| Forward+ | 182 FPS | 251 FPS | none |

## Why not migrate yet

- **The prototype passes on rendering only.** It says nothing about 22,000 lines of game logic, which would have to be rewritten and re-verified.
- **The current engine plays.** After threading, the Python build passes most of the agreed measures, though not all: it still has occasional frames over 100 ms.
- **A port would put working gameplay at risk**, including powers, AI, destruction and saves, all of which now have tests against this code.

## When to revisit

Migrate if any of these becomes the main limit: frames over 100 ms that can't be fixed in Python, a much larger roster fighting at once, or a need for higher visual quality than Panda3D can give on this hardware. Character definitions in `characters/supes/` are plain data, so they would carry over more easily than the code behind them.

## Physics

Bullet was measured against the game's own physics, per step:

| Bodies | Custom | Bullet | Bullet worst case |
|---|---|---|---|
| 64 | 0.012 ms | 0.287 ms | |
| 144 | 0.032 ms | 0.674 ms | |
| 320 | 0.062 ms | 1.72 ms | 23.7 ms |
| 480 | 0.092 ms | 3.27 ms | 58.7 ms |

The custom physics stays. Jolt was not installed: the only PyPI package found was an unvetted `jolt-python` 0.1.5.
