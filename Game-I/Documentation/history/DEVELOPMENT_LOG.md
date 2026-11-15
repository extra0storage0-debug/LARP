# Development Log

## Python conversion milestone

The project began as a standalone Python prototype. The existing Unreal project remains alongside it and is not overwritten or converted in place. The implementation uses Ursina with procedural geometry and no additional runtime library beyond the pinned Ursina package.

### Implemented

- Isolated flight dynamics with grounded, takeoff, cruise, landing, and impact phases, speed control, acceleration, braking, and a controllable descent.
- Ground movement, super-speed toggle, follow/orbit camera response, mouse look, speed-based field of view, camera follow-distance response, and brief impact vibration.
- Procedurally assembled Character blockout with proportions, costume colors, a custom shield motif, simple walk limb motion, flight tilt, and a deforming cape mesh.
- Seeded city blockout with roads, sidewalks, towers, park, trees, streetlights, props, traffic vehicles, and fleeing civilians.
- Heat vision raycast damage, short freeze effect, grab/throw interactions, ground impact, supersonic shockwave, damageable structures, bounded debris, and simple impact damage.
- HUD, pause overlay, and low/medium/high quality presets.
- Unit tests for flight dynamics, damage/debris budget, and civilian behavior.
- Corrected all byte-valued palette calls to use Ursina's `rgb32`/`rgba32` helpers. Ursina 8.3 `rgb()` expects normalized 0â€“1 values; the previous 0â€“255 values clamped almost every world material to white, causing the blank-looking scene.
- Moved the camera back to scene root and computed its orbit in world space, keeping the camera UI transform independent from the follow pivot.
- Batched the ground, roads, park paths, tree geometry, and streetlights into static meshes. Merged each tower's shell and faÃ§ade into one rendered mesh and corrected faÃ§ade coordinates that had been multiplied twice by the scaled tower parent.
- Set the default preset to Low at 1280Ã—720. Medium and High select 1600Ã—900 and 1920Ã—1080. Shifted the HUD inward to keep text inside the screen.

### Validation

- Python 3.14.7 environment created in `.venv`; Ursina 8.3.0 installed from `requirements.txt`.
- `python -m compileall -q .`: passed.
- `python -m pytest -q`: 13 tests passed, including new quality preset/resolution regression checks.
- `python -m compileall -q .`: passed; `python main.py --smoke-test`: passed with 135 buildings, 6 traffic vehicles, and 8 Low-preset civilians.
- A windowed Ursina scene rendered the character, city, roads, lighting colors, faÃ§ade windows, and HUD at 1280Ã—720. The Panda RAM screenshot buffer is upside down, so the verification capture was vertically flipped before inspection; this is a capture orientation detail, not an in-game display transform.
- Measured 257 frames over 6.12 seconds (42.0 average FPS) at 1280Ã—720, Low preset, on the specified i5-1335U / Iris Xe / 16 GB system. The run scripted four seconds of forward boost followed by a ground-impact input and landing; the measured scene contained 423 entities during the impact. It is a short sample, not a long-session guarantee.
- Ursina and Panda3D emitted no runtime exception during the render capture. The standard package supplied a `wglGraphicsPipe` on this Windows system.
- Scripted live-loop checks exercised F takeoff, WASD/Shift boost, Q ground impact and return to grounded. Separate runtime ray tests confirmed grab/throw, heat-vision damage, and freeze against a damageable prop. These were code-driven checks, not manual playtesting.

### Known limitations and next work

- Window rendering is now verified. The scripted flight and ray-interaction checks passed, but manual keyboard/mouse playtesting and sustained destruction/NPC reaction checks remain outstanding.
- Character proportions and costume are a primitive blockout. There is no authored skeletal mesh, face, material set, flight animation, or Chaos Cloth. Cape movement is procedural mesh deformation rather than cloth simulation.
- The city and traffic are generated blockout geometry. Vehicles follow a simple back-and-forth route; civilians flee without pathfinding or navigation meshes.
- Destruction uses generic health and a bounded set of simulated cubes. It is not structural building damage or authored physics fracture. Heat vision and impacts use simple generated effects without audio or Niagara.
- The scene uses 421 Ursina entities at Low startup after static geometry batching. Only the Low idle baseline has been measured; high activity and Medium/High performance remain unverified.
- No Unreal build was attempted for this migration. The Unreal project is unchanged; its previously documented build limitations still apply.

## Suggested next milestone

1. Play through every power and movement state, recording any behavior that differs from the playtest guide.
2. Measure Medium/High frame rates and active-flight/destruction load before changing their presets.
3. Replace the Character blockout with a properly licensed rigged character and authored animations; use Chaos Cloth only if the project returns to Unreal and a cloth-ready cape asset is available.
4. Improve city variety, vehicle routing, and civilian navigation after the core playable loop has been confirmed.

## Controls, flight steering, and camera pass (2026-11-01)

- Centralized the requested controls in `game/controls.py`; removed the old P pause, Q impact, and left-mouse power bindings. Period normalizes from either `.` or `period`; while holding an object, Period throws it and suppresses heat vision until release.
- F now takes off while grounded and starts ground impact while airborne. Controlled landing remains available by descending with Ctrl close to the ground. Q restores camera yaw, pitch, follow distance, and default FOV from either movement state.
- Airborne mouse yaw and A/D steering update the same camera/flight heading, and the velocity continues turning toward that heading while coasting without W. Flight movement uses W/S along that heading and camera pitch, Space/Ctrl add vertical control, flight velocity turns at a bounded rate, and Character yaw/pitch follows actual velocity. Ground movement remains camera-relative.
- Reworked the chase camera to use a world-space orbit, upright look-at, bounded pitch, smoothed follow/distance/FOV, speed-sensitive framing, and a raycast shortening the camera offset before nearby geometry.
- Updated HUD and pause help. Added regression tests for control uniqueness/aliases, flight direction, velocity steering, body-orientation conversion, and angle wrap.
- Validation in this pass: Python compileall passed, 22 tests passed, and the headless smoke test passed with 135 buildings, 6 traffic vehicles, and 8 civilians. The tests verify mouse yaw/pitch math and combined mouse+A/D steering without a graphics dependency.
- The updated 1280Ã—720 window was captured and visually inspected. A temporary rear-wall collider reduced camera distance from 9.5 to 4.55 units; a scripted airborne Q reset restored the defaults. The scripted Low flight sample measured 183 frames / 6.02 seconds (30.4 FPS) and 10.22 ms average `GameManager.update()` time. The run used flight acceleration and A/D, not injected physical mouse movement. This is below the earlier 42.0 FPS boost/impact sample; the scenarios differ and the short result is not a sustained-load guarantee.
- Manual mouse feel, full in-game keyboard play, and sustained power/destruction/NPC interactions remain unverified. The screenshot confirms a visible, centered Character and upright horizon; the city and Character remain procedural blockout art.

## Final gameplay overhaul (2026-11-01)

- Added Up/Down/Left/Right camera-only rotation, Home/End ascent/descent aliases, and K fullscreen toggle. Flight heading and pitch now track mouse plus A/D separately from arrow camera orbit, so arrows do not alter airborne movement. WASD remains the movement input.
- Flight root is kept at zero pitch and roll in takeoff, cruise, landing, impact, and hover. Horizontal yaw follows velocity while vertical movement preserves yaw. Arms extend outward, legs stay together, and cape deformation/flap scales with speed while remaining quiet near hover.
- Added a fixed center four-line reticle and dot, target name/grab prompt, release prompt, notifications, and fullscreen-safe normalized HUD positioning. The same center camera ray feeds target selection, heat vision, and freeze breath; grabbing prefers the aimed movable object and excludes anchored buildings.
- Replaced the single beam with paired, eye-originating red-orange cores and outer glows that splay past the Character silhouette and converge at the center aim point. Reused impact glow/spark entities avoid per-frame particle creation. Objects heat tint while taking continuous damage; beam visuals disappear when Period is released or an object is held.
- Improved held-object placement and damping, offsetting the object beside the Character so it remains visible. Period throws held objects along the camera aim and suppresses heat vision for that press. E reports grab/release through the HUD.
- K now preserves the selected windowed resolution. Fixed a pre-existing damage bug: `Damageable.apply()` returns applied damage, so treating its nonzero return as a broken flag caused every damaged prop to break immediately. Props now create debris only after health reaches zero.
- Automated verification: compileall passed, 28 tests passed, and headless scene smoke passed (135 buildings, 6 traffic vehicles, 8 civilians). Windowed scripted checks verified fullscreen round-trip, Q reset, center-ray target, upright flight root, heat damage/render/stop, grab/release/throw, and freeze. Render captures were visually inspected for crosshair, heat beams, held-object framing, and upright posture.
- Low flight benchmark: 29.05 FPS / 175 frames over 6.02 seconds, 11.39 ms mean `GameManager.update()`; this run did not remain foreground. A separate confirmed-foreground sample measured 28.74 FPS / 173 frames and 11.18 ms. Both used 1280Ã—720 with scripted acceleration/A-D, and both are short measurements. No improvement is claimed; physical mouse input and extended destruction load remain unverified.

## Spherical planet foundation (2026-11-01)

### Audit and implementation

- Audited the complete Python source inventory (`main.py`, settings, game managers, camera/input/targeting, Character/civilian, movement, powers, city/buildings/objects/traffic, HUD/menus, AI/combat, and all test modules) plus `DEVELOPMENT_LOG.md`, `Documentation/PLAYTEST.md`, and `HARDWARE_REPORT.md`. The Unreal project was not accessed or changed.
- Added `world/planet.py`: a 12,000 m radius sphere, inverse-square radial gravity, local up/east/north frame, chart-to-globe mapping, tangent movement, surface orientation, and procedural ocean/continent/mountain/ice vertex colors with cloud and atmosphere shells.
- Bent the existing seeded roads, park paths, towers, windows, trees, lamps, props, traffic and civilians onto the globe. Tower and actor orientation follows local surface up. Existing district gameplay and damageable-object systems remain in use.
- Ground movement reprojects to spherical altitude; Character collision prevents underground travel. Flight, controlled landing and ground impact use local radial direction. Hands-off cruise now counters radial gravity and settles vertical drift into a hover; directional flight continues to use the existing thrust, steering and lift behavior. The upright body frame and chase camera use local planetary up. Space camera framing adapts to altitude, and the globe remains a real mesh.
- Added preset-based planet mesh detail and runtime rebuilds when graphics quality changes. NPC counts now follow Low/Medium/High. This is preset-level mesh LOD; distance-based terrain/chunk streaming and frustum culling are not implemented.
- Added planet tests for surface projection at multiple chart positions, radial gravity, tangent movement, orientation, powered/unpowered flight, landing and impact.

### Validation

- `python -m compileall -q .`: passed.
- `python -m unittest discover -q`: 37 tests passed. The project's `.venv` does not contain `pytest`, so the existing standard-library `unittest` suite was used without adding a dependency.
- `python main.py --smoke-test`: passed; initialized 135 buildings, 6 vehicles and 8 Low-preset civilians.
- Scripted Ursina runtime check passed for walking while preserving 0.25 m altitude at an offset on the sphere, takeoff/ascent, local-up character orientation and radial ground impact/landing. The check reached 54.46 m before impact.
- Captured and inspected the Low window at ground level and at 20,000 m altitude. The ground capture shows the starting district; the space capture shows the spherical globe under the Character. These are render inspections, not manual keyboard/mouse playtesting.
- Six-second scripted render-loop measurements on the i5-1335U / Iris Xe are in `HARDWARE_REPORT.md`. The window reported `SetForegroundWindow() failed`, so focus was not confirmed; treat the results as automated samples.

### Current scope and limitations

- This is a scaled spherical prototype, not a physically sized Earth. The globe uses procedural vertex colors, not satellite maps or authored cloud textures. Surface collision is sea-level; mountains, rivers, lakes, biomes, bridges and road networks have not been generated around the globe.
- The current city remains one seeded district near the chart origin. Other continents are colored planet geometry only. There is no global terrain/city streaming, chunk queue, distance-based object LOD, frustum culling, or NPC/traffic simulation in remote regions.
- Planetary gravity, surface projection, camera-up and upright orientation have automated coverage. Returning from space and landing at multiple remote locations were not manually tested. Atmospheric re-entry effects are absent.
- Existing heat vision, freeze breath, grab/throw, destruction, debris, civilian response and traffic were preserved, but were not all re-run in a full playthrough after the planetary changes. Face/hair remain the previous primitive blockout; cape motion remains procedural.
- High-preset idle performance averaged below 30 FPS in this sample. Active Low flight also ran below the historical 42 FPS sample; these short measurements do not establish sustained performance.

## Aiming, earlier character blockout, and Sun pass (2026-11-01)

### Audit and fixes

- Re-read the project guide, playtest guide, hardware report, development log, and the Python modules/tests. The already-corrected camera framing and mouse/arrow steering path remain in place.
- Traced the sideways heat-vision hit to Ursina 8.3's shared internal raycaster. The chase camera casts backward for wall avoidance immediately before the aim ray casts forward. Reversing that ray nearly 180 degrees hits Ursina's fallback rotation path, which can preserve a stale horizontal axis and mirror left/right aim.
- Added `game/world_raycast.py` to reset the shared ray entity before casting. Both camera obstruction checks and the target ray now use this helper, so they do not inherit a prior cast's orientation.
- Removed the intentionally splayed heat-vision waypoints. Each rendered eye beam now uses one straight segment to the shared center-ray world hit point. Misses use the camera ray's configured range.

### Added

- Heat vision now charges over a configurable 0.58 seconds and fades over 0.28 seconds after release. It adds eye glow, bounded charge particles, three beam layers, moving sparks, target sparks, small flame/smoke effects, and progressive target damage. Particle counts are reduced on Low. Heat distortion is represented by pulsing geometry and glow; there is no refractive heat shader.
- This earlier character pass temporarily used a procedural face mask that hid the human facial details. It was removed, along with its README and captures, in the later character redesign entry below.
- Integrated the existing `SunCycle` into the game loop and removed the startup ambient light and duplicate directional light. The runtime now has one directional Sun light and no ambient light. Earth, clouds, roads, ground, lamps, and trees receive directional lighting. The Sun's visible disc and light share the same animated direction.

### Validation

- Before edits: 38 `unittest` tests passed; compileall and headless startup passed.
- After edits: 44 `unittest` tests passed; compileall passed; headless startup initialized 135 buildings, 6 vehicles, and 8 Low-preset civilians.
- Scripted world-ray checks passed at yaw 0 and +/-18 degrees and at upward/downward camera pitches. Both beam cores aligned to their target endpoints within 0.02 m. A charged shot damaged its target, the release fade hid the beams, and aiming also acquired a target while airborne.
- A render capture aimed at a real starting-district building was inspected. It shows the reticle and both beams converging on the same building point. Earlier front, side, back and upright-flight character captures were inspected and later deleted; the current captures are linked in `Documentation/PLAYTEST.md`.
- Scene inventory reported one `DirectionalLight` and zero `AmbientLight` nodes. No performance benchmark was run for this change.

### Remaining limitations

- Heat vision is still a low-cost geometric effect. It has no true refraction shader, audio, physically simulated fire, or material-specific heating. Live mouse movement and arrow-key turning were covered by the existing input math tests and scripted ray checks, not a physical-input playthrough.
- The earlier face-mask blockout used generated primitives rather than an imported asset; that character version is superseded by the redesign entry below.
- The Sun/day-night system is a lightweight approximation. Directional shadows are disabled, the globe is vertex-colored rather than geographically authored, and atmospheric scattering, cloud shadows, oceans/water physics, remote terrain collision, global streaming/LOD, and re-entry remain incomplete.
- New six-second idle samples were collected after that character blockout, charge effects, and Sun integration; see `HARDWARE_REPORT.md`. The render window did not confirm foreground focus, and active heat vision, flight, and destruction load were not benchmarked.

## Character redesign and unbounded camera (2026-11-01)

### Changes

- Removed the earlier panda-mask geometry and face-hiding code. The human facial features remain visible. Deleted the generated mask README and mask screenshots; the old mask implementation is superseded by this entry.
- Replaced the separate bald cap and floating locks with one mesh covering the skull, a connected side/rear curtain extending to the nape, seven tapered head-attached locks, low-contrast strand sweeps, and a front curl. The mesh root is parented to the real head node and cancels the head ellipsoid scale. Locks sway subtly with flight speed.
- Removed camera yaw wrapping and pitch clamps. Mouse and arrow input can accumulate through multiple full rotations. Flight and ground body yaw track the nearest equivalent camera heading without wrapping the stored value; the Character's surface orientation still uses local planetary up.
- Left world systems, aiming, and heat-vision geometry intact.

### Validation

- `python -m compileall -q .`: passed.
- `python -m unittest discover -v`: 45 tests passed, including accumulated yaw/pitch, arrow controls, and continuous heading across 360 degrees.
- `python main.py --smoke-test`: passed; initialized 135 buildings, 6 vehicles and 8 civilians.
- Scripted camera updates passed at yaw 725/1080/1440/1800/2160 degrees and pitch 10/95/185/275/450 degrees. The camera returned finite positions, pressing F at yaw 725 preserved that yaw, and the character remained attached to the planet-up frame.
- Charged heat vision hit and damaged the same real building from grounded and cruise states. Front, side, rear, top and close-up hair renders were captured and inspected; gameplay and camera-pole screenshots are linked in `Documentation/PLAYTEST.md`.
- A six-second Low idle render sample measured 39.62 FPS, with 20.07 ms mean manager update. Foreground focus was not confirmed; see `HARDWARE_REPORT.md`.

### Current limitations

- The face and hair are generated blockout geometry, not a scanned or authored realistic model. Individual hair strands are low-cost static sweeps, and only the larger locks sway; there is no strand simulation or skeletal hair rig.
- The frame-rate sample was idle and short. It does not establish sustained flight, heat-vision, or destruction performance.

## Sentry-inspired character redesign (2026-11-01)

### Changes

- Recolored the active Character model with a fitted gold suit, darker gold panels, gold shoulder/arm details, a dark belt, gloves, and boots. Removed the old chest shield.
- Replaced the loose black hairstyle with a golden-blonde scalp shell, a shoulder-length side/rear curtain, 12 tapered wavy locks attached to the head, and low-cost highlight/shadow strands. The locks sway subtly during flight; the hair is loose with no tie, bun, or braid.
- Rebuilt the cape as a 9Ã—13 dynamic cloth grid with navy vertex shading, gold animated edge piping, and a large gold S attached to the rear of the cape. Airflow deformation uses the existing flight speed and cape animation path.
- Camera, controls, character movement, planetary gravity, aiming, heat vision, freeze breath, grabbing/throwing, impact behavior, and world systems were left unchanged.

### Validation

- `python -m compileall -q .` and `python main.py --smoke-test`: passed; headless startup initialized 135 buildings, 6 vehicles, and 8 civilians.
- `python -m unittest discover -v`: 45 tests passed.
- Captured and inspected front, rear, side, close-up, grounded, and flying views in `Documentation/sentry_*.png`. The rear view shows the full gold S below the hair and the gold trim remains attached to the moving cape.
- A six-second Low-preset idle sample measured 39.42 FPS and 20.27 ms mean manager update on the i5-1335U / Iris Xe system. Focus was not explicitly verified; see `HARDWARE_REPORT.md`.

### Current limitations

- Hair, fabric folds, and the face remain lightweight procedural geometry, not a realistic groom or authored production character. The larger hair locks sway; individual strands are static highlights.
- Flight performance was not timed in this pass. The Low idle sample is short and should not be read as a sustained-play result.

## Planetary atmosphere and orbital environment (2026-11-01)

### Changes

- Replaced the single flat clear color with a shader-driven sky dome. It uses a blue zenith/horizon gradient, warm Sun-facing twilight scattering, an exponential altitude density input, and a continuous fade to black. A coarse local cloud path remains enabled on Low; Medium/High use a more detailed procedural sky cloud field.
- Kept one directional Sun as the only environmental light. Its visible disc uses the same direction as illumination; the light casts quality-scaled shadow maps (512 Low, 1024 Medium, 2048 High). Night windows are emissive geometry rather than extra lights. A configurable 720-second default day cycle moves the Sun locally and rotates the globe in orbital views.
- Added generated Earth, water, cloud, and atmospheric-rim spherical meshes with day/night shading, ocean color/Fresnel/specular response, animated cloud rotation, and a thin blue limb. Globe geometry and camera far distance scale with quality and altitude.
- Added exponential atmospheric density to flight drag and a speed/altitude/descending-dependent re-entry glow. Added radial ocean detection, underwater entry/exit notifications and splashes, submerged flight damping/upward buoyancy, a swim depth clamp, and floating/damped movable objects.
- Preserved the existing Sentry-inspired character, gameplay powers, controls, camera framing, gravity, and city. Added repeatable actual-scene capture and Low/Medium/High benchmark scripts under `Documentation/`.

### Validation

- Python compileall passed; the full standard-library test suite passed (48 tests); `main.py --smoke-test` initialized 135 buildings, 6 vehicles, and 8 civilians. The venv does not contain `pytest`.
- Render captures were generated and inspected for ground, low-angle city shadows, 1/10/20/50 km, above-atmosphere, outer-space Earth, day/night boundary, low-altitude ocean, clouds, sunrise, sunset, and night. See the capture list in `Documentation/PLAYTEST.md`.
- Six-second rendered idle samples on the i5-1335U / Iris Xe machine were Low 28.29 FPS (35.35 ms mean frame, 56.91 ms worst), Medium 24.31 FPS (41.14 ms mean, 196.90 ms worst), and High 21.42 FPS (46.69 ms mean, 127.86 ms worst). Foreground focus was not confirmed; these are short samples, not sustained-performance claims. Full results are in `HARDWARE_REPORT.md`.

### Current limitations

- The 12 km-radius globe has synthetic generated geography, not Earth satellite data, realistic topography, or global terrain/city streaming. The atmosphere/clouds/ocean use efficient approximations, not volumetric Rayleigh-Mie integration, authored weather, cloud shadows, or physically based water.
- Water entry and buoyancy are radial-altitude gameplay rules rather than volumetric fluid simulation or collider-based swimming. Underwater and floating behaviors have not received a full manual playthrough.
- The sky was visually checked in the scripted captures, but a manual ascent, re-entry, sunrise/sunset traversal, and sustained gameplay/performance run remain outstanding.

## Solar-system exploration prototype (2026-11-01)

- Added an animated solar-system atlas, selectable planetary destinations, keyboard travel, and Earth return. Procedural body adapters provide local-up orientation, inverse-square gravity, surface projection, biome-colored meshes, and a bounded local terrain/prop tile. Jupiter has a storm mark, Saturn has rings, and gas giants use a cloud-deck boundary without a fabricated solid landing.
- Actual window captures show the atlas, Mars arrival, Saturn cloud deck, and Earth return. The headless smoke test exercised Mars/Jupiter/Moon/Earth travel. Current suite: 101 tests.
- Interplanetary travel is an instant scene transition, not continuous space traversal. Planetary meshes and terrain are simplified procedural content; global terrain chunk streaming and per-region settlement systems remain incomplete. Orbit paths animate in the atlas rather than driving a physically scaled orbital simulation.

## City-runtime cleanup and performance pass (2026-11-01)

### Changes

- Created `Delete/old_backups/Sentry_pre_optimization_backup_2026-11-01.zip` before cleanup because this directory is not a Git repository. The archive includes project assets, ignored settings, and geography source/cache files; it excludes the linked virtual environment and regenerable Python/test caches.
- Removed solar-system atlas construction, input handling, destination transitions, solar hazards, and orbital far-plane work from the active runtime. The independent celestial and atlas modules/tests remain in the project.
- Stopped building the global Earth, ocean, cloud, and atmosphere render meshes for the street-level city runtime. Retained geographic math, local elevation, city terrain, the day/night Sun, and the source assets/tools.
- Added a 40 m building footprint grid for civilian and animal obstacle checks. NPC obstacle queries now inspect their local cell instead of all 135 buildings. Nearby actors update each frame; mid-range actors update at 20 Hz and distant actors at 10 Hz. Character chart coordinates are calculated once per world update and shared with NPC steps.
- Disabled animal spawning in the urban runtime while retaining its source module. Removed the duplicate root `config.py`; graphics configuration remains in the `config/` package.
- Reduced shadow-map sizes to 512/1024 for Medium/High and disabled dynamic shadows on Low. Updated the benchmark tool to run one preset per process, report startup, process CPU, peak working set, and avoid changing persisted settings.
- Updated the README and playtest notes to distinguish active city checks from archived planetary documentation. The smoke test now checks city generation, indexed buildings, character movement, camera, collision, NPC counts, and traffic.

### Validation

- `python -m compileall -q .`: passed.
- `python -m unittest discover -q`: 101 tests passed.
- `python main.py --smoke-test`: passed with 135 buildings, 6 vehicles, 8 civilians, 0 runtime animals, and successful ground movement, camera, collision, and update checks.
- Six-second idle render samples on the i5-1335U / Iris Xe system measured 29.97/16.51/17.50 FPS at Low/Medium/High in the latest run. Low `GameManager.update()` time fell from 13.71 to 7.09 ms; Medium/High measured 7.19/6.65 ms. Peak working sets were 304.4/341.5/417.3 MiB. Window focus was not confirmed; repeat runs varied and a stable 30 FPS target is not established. Detailed results are in `HARDWARE_REPORT.md`.

### Remaining limits

- Ground movement is present, but a dedicated jump action, drivable player vehicles, missions, shops, a minimap, and city streaming are not implemented.
- The preserved original flight and superpower mechanics remain in the active runtime for now. Solar navigation and orbital visuals are inactive.
- The preserved geography assets and caches keep the project footprint large. Removing any would impair retained data-building tools; no asset data was deleted.

