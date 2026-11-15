# Sentry final overhaul report

Date: 2026-11-03. This replaces the earlier flight-only report.

**Status:** implemented. 503 automated tests and the headless smoke test pass on this build. **The real-window checks have not yet run on this build**, because the game was open each time they were due; see [Tests and results](#tests-and-results). Nothing below that says "real window" applies to this build until that section says so.

## Controls

Mouse movement moves the camera. In play, `E`, `R`, left mouse and right mouse do nothing for all five characters; the mouse still works in menus.

| Key | Superman | Homelander | Sentry | Omni-Man | Soldier Boy |
| --- | --- | --- | --- | --- | --- |
| 1 | Heat Vision (toggle) | Laser Vision (toggle) | Remote Bomb Mode (toggle) | Flight Charge | Remote Bomb Mode (toggle) |
| 2 | Time-Stop Punch | Time-Stop Punch | Time-Stop Punch | Time-Stop Punch | - |
| 3 | Nuclear Execution | Nuclear Execution | Nuclear Execution | Nuclear Execution | - |
| 4 | Time-Stop Ground Execution | Aerial Neck Grab + Laser Execution | Massive Blast | Shockwave Punch | Massive Blast |
| T | 30-second Time Stop | 30-second Time Stop | 30-second Time Stop | 30-second Time Stop | - |
| R | Nothing | Nothing | Nothing | Nothing | Nothing |
| + | Punch | Punch | Punch | Punch | - |
| - | Kick | Kick | Kick | Kick | - |
| F, Space, Ctrl, Shift | Flight | Flight | Flight | Flight | Walk, jump and run only |

Also for everyone: WASD, Q dash, Tab info, M switcher, P powers, C camera, K fullscreen, Esc pause. The main-row `=` key, with or without Shift, and numpad `+` both punch, because that is how the keyboard reports them.

Taking `T` for Time Stop removed the automatic-targeting toggle, so targeting is now always on. While an enemy is in Range, abilities cannot be aimed at the world instead.

## Abilities

- **Time-Stop Punch (2):** stops the world, charges the nearest enemy, lands one punch that launches them, flies on over and past them, and restarts time. The enemy flies during the break-away, and carries on when time resumes. All four share the same code; each has its own trail colour, flash colour and arm pose.
- **Nuclear Execution (3):** stops the world, rushes and grabs the enemy by the neck, rises to 30 m if they are lower than that, drives them into the ground, punches once, and sets off a spherical explosion. It then restarts time. Half the damage is the punch and half the blast. The ground impact deals no damage on purpose, so that high Damage cannot end the sequence before the explosion. Range sets the radius, up to 220 m. The fireball and flying debris only move once time resumes, 0.3 seconds after the punch.
- **Aerial Neck Grab + Laser Execution (Homelander, 4):** flies to the nearest enemy, lifts them 25 m by the neck, fires both eye lasers into the point between their eyes for exactly 3 seconds, then throws them. Time does not stop for this one. At the default Damage a full-health enemy survives the 3 seconds; at higher Damage they can go down earlier, which ends the laser early as you specified.
- **Time Stop (T):** see below. It has no card, because it has no values to edit.
- **Time-Stop Ground Execution (Superman, 4):** unchanged: rush, grab, hurl down, follow, 1.6 seconds of Heat Vision, fly off.
- **Remote Bomb Mode, Massive Blast, Punch and Kick:** unchanged.

Everyone sent flying by 2, 3 or Homelander's throw uses one new launched motion: gravity, air drag, tumbling, damage to whatever they hit, stopping against buildings that hold, a landing crater and a bounce. Nothing teleports them. Tests measure every frame of the path, and they found two cases where a body did snap to the floor; both are fixed.

## Time Stop on T

Exactly 30 real seconds, to within one frame, counted in real time so that a low frame rate cannot stretch it. It runs for Superman, Homelander, Sentry and Omni-Man, and AI can never trigger it. A second press neither restarts nor extends it.

- **Frozen:** every other character, AI, vehicles, civilians, physics objects, fire, explosions, weather and other characters' shots. World time simply does not advance for them, so nothing has to be saved or restored: each carries on with the velocity, pose and AI state it had. Tests watched characters and shots directly; for civilians and vehicles they confirm the world loop receives zero time, because none spawn near the test position. AI wait timers are moved forward by the length of the stop.
- **Still running:** the player, who can move, fly, attack and use abilities, and the player's own shots and bombs. Damage and craters apply at once.
- **Waits until time resumes:** knockback on a frozen enemy, falling trees, and the fireball and debris of any explosion the player sets off. These stay frozen at their first frame for up to 30 seconds.
- **On screen:** a countdown, a pulsing blue tint, and a ripple when time stops and when it resumes. The whole-screen effect is a tint rather than a real distortion shader.
- **Switching character:** the new character is the free one and the previous one freezes. The clock is unaffected, and this includes switching to Soldier Boy, who cannot start a stop but can play through one.
- **Menus and pause hold the countdown,** because the whole game is paused then. If a 2, 3 or Superman 4 sequence is running when 30 seconds is up, the world resumes when that sequence ends, under a second or two later.

## Power Configuration

Press **P**. There are five character tabs and one card per ability a key reaches. Each card has Range, Damage and Speed, with a slider and an exact value box kept in step, or `N/A` where a value means nothing for that ability. Each tab also has two character-level rows: **Health**, from 1 to 100,000 hp, and **Healing Speed**, from 1 to 100%. Sliders are logarithmic.

| Value | Default | Maximum |
| --- | --- | --- |
| Range | Maximum | Up to 100,000 m (some abilities less) |
| Damage | 20% of maximum | Per ability, for example 3,000 dmg/s for Heat Vision and 20,000 for Massive Blast |
| Speed | Maximum | Per ability |
| Health | The character's own figure (900 to 1,300 hp) | 100,000 hp |
| Healing Speed | 20% | 100% |

- Superman, Homelander, Sentry and Omni-Man have five cards and Soldier Boy two.
- The buttons are Apply, Reset Ability, Reset Character, Reset All, Max All and Max All Characters. The two broad resets ask for a second click. Max All also raises Health and Healing Speed.
- Changing Health keeps the same share of health: a full bar stays full. Bars and vitals update immediately, even in the menu.
- Values are validated, saved independently per character and ability, and survive a restart.

There are no cooldown, charge-time, duration, stamina or energy settings, and those resources no longer exist in the code.

**Save migration:** Healing Speed did not change the save format, so existing version 3 files keep every value and simply gain the 20% default. Before that, the format moved to version 3. Your existing file held every Damage value at maximum, which would have hidden the new 20% default, so on the next launch its values stop being used and it is kept as `config/character_powers.before_v3.json`. The earlier version-1 file is still at `config/character_powers.before_range_damage_speed.json`.

## Healing Speed

Each of the five characters has their own setting, and it is now the only thing that regenerates health.

- **What the number means:** 100% refills a full bar in 10 seconds, so 20% takes 50 seconds. It is a share of maximum health, so it scales with Health: 20% restores 2% of the bar per second, which is 24 hp/s at 1,200 hp and 2,000 hp/s at 100,000 hp.
- **When it runs:** all the time, in and out of combat, with no pause after a hit. It stops at the character's maximum, and while they are downed. Bars rise every frame.
- **Removed, because they would have ignored or contradicted the slider:** the 4 to 6 second pause after damage, the fixed per-character rates (12 to 26 hp/s), and Superman's always-on 10 hp/s Solar Absorption. Solar Absorption did nothing else, so it is also gone from his Tab passive list.
- **Kept:** Void Unleashed still triples healing, as its card says, so it can exceed the 100% rate. Sentry's Energy Absorption still returns health when he is hit. Both still stop at his maximum.
- **In a time stop:** only characters still in time heal: the two in a 2, 3 or Superman 4 sequence, and the player during the T stop.

**Effect on fights with AI.** Measured headless: real AI attacking Sentry (1,300 hp) for 90 seconds while he stood still and did not fight back, one run per row.

| Healing Speed | Enemies | Damage taken | Lowest bar | Downed |
| --- | --- | --- | --- | --- |
| 1% | 2 | 1,491 hp | 12% | No |
| 20% | 2 | 1,755 hp | 97% | No |
| 60% | 2 | 1,487 hp | 98% | No |
| 100% | 2 | 1,950 hp | 98% | No |
| 20% | 4 | 2,390 hp | 96% | No |

**At the 20% default, AI could not wear him down at all**, even four against one, because its damage arrives in small amounts at about the rate he heals. The old fixed rates were similar, but every hit paused them. Lowering Healing Speed brings the danger back. Separately, AI is limited to 6% of a target's health per second, so at 60% or above AI can never down anyone. A character at 100,000 hp also heals faster than a default beam can hurt them: Heat Vision at its default deals about 330 hp/s to Superman, against 2,000 hp/s of healing.

## Limits worth knowing

- **100,000 m Range:** the island is 10 km across, so anything above about 15 km behaves the same. Blast sizes follow Range only up to a cap for each ability, so one punch cannot flatten the island.
- **AI damage limit:** AI deals at most 6% of a target's health per second, however high the values are. This is a fixed rule with no setting. Without it, full-power AI could kill the player almost instantly.
- **Bomb pacing:** the next bomb is produced 0.4 s after the last goes off. This is a small exception to "zero cooldown", because otherwise a close target would take about 20 full explosions a second.
- **Going down:** a downed character recovers after 10 seconds. Switching into a downed body leaves you unable to act until then.

## Abilities with no player key

These lost their key to your specifications, and you asked me not to invent controls:

- **Superman:** Kryptonian Vision, Freeze Breath, Super Breath, Solar Overcharge
- **Homelander:** Aerial Charge, Enhanced Senses, Laser Overdrive, and the sweeping laser mode (its Speed slider is removed)
- **Sentry:** Energy Projection, Golden Shield, Molecular Manipulation, Void Tendrils, Void Unleashed
- **Omni-Man:** Ground Slam, Dive Bomb
- **Soldier Boy:** Shield Combat, Shield Defence, Shield Throw, Chest Blast, Maximum Discharge, Power Nullification

AI characters still use most of these, and they run at their default values. **Grab, Shield Defence, Molecular Manipulation, Golden Shield, Enhanced Senses, Kryptonian Vision and the sweeping laser are used by nobody right now**: the code is kept and tested, but it is unreachable until given a key.

The old `R` abilities lost their key but AI characters still use them, as they do the others here. As a player, Soldier Boy now has only `1`, `4` and `Q`, with no melee and no way to nullify anyone.

## Automatic targeting and health bars

- **Targeting:** one shared system picks the nearest valid enemy, slightly prefers one ahead, and keeps its target unless another is clearly closer. It searches five times a second and refreshes after switches and team changes. It never picks allies, the player, downed or absent characters, and it never moves the camera.
- **Health bars:** every character in the world has a name and bar over their head, including the player. They use team colours, and the targeted enemy's bar is larger with a marker. The bar sits at 3.45 m, and the tallest head measured is 3.11 m. Parked characters show none.

## Soldier Boy and flight

He has no flight input, and no flying ability is reachable by him. Tests cover every key, maximum settings, stale saves, being thrown, and being the target of Superman's execution. He does not receive keys 2, 3, + or -.

## Tests and results

Run on this build, 2026-11-03:

| Check | Result |
| --- | --- |
| Compile | No errors |
| Unit tests | `Ran 503 tests`, `OK` |
| Off-screen renders of laser, punch, nuclear blast, Time Stop, Power panel | Checked by eye; three visual problems found and fixed |
| Headless smoke test | Passed |
| Real-window checks, all four configurations | **Not run on this build** |

The unit tests drive the game through its real input handler and game loop, but they run headless. They do not check how anything looks. `tools/final_window_check.py` has been updated to play the new controls in a real window, and that updated version has not run yet.

`tools/final_window_check.py` still presses `R` and expects the old keys, so it needs updating before it can be run again.

Bugs the tests found and that are now fixed:

- Anything launched from mid-air snapped straight to the floor, and so did a held enemy who went down.
- **Blasts skipped trees and objects:** every blast searched a live list while removing what it destroyed, so each felled tree spared the next one (8 of 13 hit in one measured blast). This is older than this overhaul and also affected Massive Blast. All of them now hit everything in range, which means more destruction per blast.
- **A game crash:** when a Heat Vision or Laser Vision hit felled a tree, the game went on to set the destroyed tree alight and could stop with `AssertionError: !is_empty()`. Superman's execution beam takes the same path. It also exists in the backup from before this overhaul. An AI fight reproduced it, and after the fix all five 90-second AI runs finished. A new test fails if the fix is removed.
- Superman could hang just out of grab range, depending on distance, until the time limit. A sweep test across distances now covers it.
- Bombs flying low could go off about 14 m short on a rise or crater; they now arc.
- The save migration could delete an old settings file if a set-aside copy already existed; it now never deletes one.
- Felled trees left their trunk and canopy registered with the engine for good.

## Performance

Measured off-screen on this build while your game was also running, so only the comparisons mean anything. The ranges come from three runs.

| Moment | Frame time |
| --- | --- |
| Normal play, average | 71 to 90 ms |
| During the T Time Stop, average | 57 to 89 ms, about the same as normal |
| Nuclear Execution, detonation | 160 to 689 ms |
| Nuclear Execution, first moments after time resumes | Worst 613 to 680 ms |

**The nuclear blast causes a visible hitch of up to about 0.7 seconds here**, because it can fell many trees at once. Its radius is capped at 220 m, the same as Massive Blast. Lowering its Range makes it smaller and cheaper. It has not been timed on its own in a real window.

The figures below are older:

**No timings exist for this build yet.** The last real-window figures are from the build before the controls update, on Low at 1600×900, on battery on the Balanced plan. Treat them as a rough guide only.

| Scenario | FPS | 1% low | Worst frame |
| --- | --- | --- | --- |
| Standing idle | 28.9 | 16.3 | 62.6 ms |
| Fast flight | 27.9 | 8.3 | 138.8 ms |
| Sustained beam | 32.2 | 9.8 | 135.0 ms |
| AI fight with beam | 33.1 | 20.4 | 49.9 ms |
| Superman at maximum power | 23.5 | 5.2 | 191.8 ms |
| Soldier Boy at maximum power | 23.5 | 3.2 | 313.5 ms |
| Heavy destruction | 21.7 | 5.6 | 177.9 ms |
| Rapid switching | 21.9 | 7.8 | 127.9 ms |
| Extended session | 27.8 | 13.5 | 102.9 ms |

Memory started at 438 MB and grew 0.2 MB during the extended session; entities ended at 830. That run had 100 checks passing and 3 failing. The failures were traced to the test tool and corrected, but the corrected tool has not been re-run.

- **The 30 FPS target is not met** in that run while idle, flying or in heavy combat. A side-by-side run that day showed about 32 FPS for the backup and about 31 for the new build, so this work did not cause the drop. Earlier runs reached about 51 FPS idle; battery power is the likely reason for the difference, but that is unproven.
- **Massive Blast has never been timed on its own.**
- Added since then: Ursina now skips per-frame checks on static entities, which were costing about 5.7 ms a frame in a profile. Its effect has not been measured.

## Known gaps

- The new moves have only been judged from off-screen stills. Their motion needs your own play or a real-window run. Superman's execution and the bombs have not been judged at all. The Power panel was rendered off-screen and has no overlaps at 1600x900.
- **Motion blur is a streak of light and a particle trail behind the character,** not a true camera blur, which would need a full-screen shader and cost frame rate. At default Speed a charge can be over in one or two frames.
- **Character-specific animation** means different colours and arm poses on the shared body rig. There are no per-character animation clips.
- Your Key 3 specification was cut off in the message at "Visible debris, smoke, dust and impact ef", so anything after that is not implemented.
- The animations reuse the shared body rig, moving arms, legs and posture. They are not hand-animated per character.
- Explosions and fires started during a time stop only animate once time resumes. Damage and craters apply at once.
- The execution's target can go down from the impact at high Damage, in which case the Heat Vision stage is skipped, as you specified for a target that dies.
- `tools/aesthetic_benchmark.py`, `Documentation/capture_gameplay.py`, `tools/fast_flight_benchmark.py` and `tools/performance_benchmark.py` have not been updated and may not run.

## Files changed

- **New:** `powers/universal.py`, `powers/bombs.py`, `powers/targeting.py`, `tests/test_controls_update.py`, `tests/test_gameplay_rules.py`, `tests/test_healing_speed.py`, `tests/test_gameplay_control_update.py`
- **Powers and data:** `config/power_schema.py`, `powers/base.py`, `powers/fx.py`, `powers/common.py`, `powers/aiming.py`, `powers/vitals.py`, `powers/loadout.py`, `powers/superman.py`, `powers/homelander.py`, `powers/sentry_powers.py`, `powers/omni_man.py`, `powers/soldier_boy.py`
- **Game:** `game/game_manager.py`, `game/combat_system.py`, `game/team_manager.py`, `game/controls.py`, `characters/roster_character.py`, `ai/combat_ai.py`, `world/island_generator.py`, `world/tree_destruction.py`, `world/elements.py`, `main.py`
- **Interface:** `ui/character_power_panel.py`, `ui/enemy_team_ui.py`, `ui/hud.py`, `ui/menus.py`
- **Tests and tools:** `tests/power_fixture.py`, `tests/game_fixture.py`, `tests/test_character_powers.py`, `tests/test_power_config.py`, `tests/test_switching_and_world.py`, `tests/test_extreme_values.py`, `tests/test_controls.py`, `tools/final_window_check.py`
- **Docs:** `README.md`, this report

Backup from before this overhaul: `../SENTRY_backup_before_gameplay_overhaul_2026-11-02` (447 files, 0 hash mismatches). A second backup from just before the Homelander, key 2, key 3, R and T changes is at `../SENTRY_backup_before_control_update_2026-11-03` (238 files, compared identical; screenshots excluded). No separate backup was taken before the earlier controls, Health, execution or Healing Speed changes.
