> **Superseded.** The final specification removed the systems described here. See SENTRY_FINAL_OVERHAUL_REPORT.md.

# Sentry character and power overhaul report

Date: 2026-11-02. Backup: `SENTRY_backup_before_overhaul_2026-11-02` (275 files, hash-verified; excludes `.venv` and `Delete`).

## Roster

Five characters remain. Purple and Blue are removed from the spawn list, AI, kits and settings, and old saves can't bring them back. A test confirms this.

| Slot | Character | Powers |
|---|---|---|
| Yellow (you) | Sentry | Walk, run, fly, time stop, telekinetic hold, beatdown, throw |
| White | Superman | Flight, heat vision, punches, grab-and-beat hold |
| Green | Omni-Man | Flight, punches, hold, lethal takedown, explosive high-speed collisions. Strongest, toughest and fastest |
| Black | Homelander | Flight, heat vision, punches, grab-and-beat hold |
| Red | Soldier Boy | No flight. Punches, hold, shield bash and block, chest blast that depowers you for 4 s |

- **Omni-Man:** his speed is always at least 1.2× yours, whatever you set yours to. He deals 2× damage and takes 1/2.5 of it.
- **Lethal takedown:** if you're at 25% health or less when his hold ends, it kills you.
- **Chest blast:** it charges for 0.6 s and hits where you were, so moving dodges it.
- **Depowered:** you keep walking and flying but lose time stop and telekinesis, and you drop any enemy you're holding.
- **Holds:** using time stop, or grabbing the enemy holding you, breaks a hold.

## Appearance: please read

**These are stylised costumes, not faithful likenesses.** No character models exist in the project, so each one is the shared body with a new palette, hair, ears, emblems and gear made from simple shapes. All four share the same face geometry.

You can tell them apart by costume, moustache, helmet and shield, as in `screenshots/overhaul/`. They do not look like the film and TV actors. Getting closer would need real character models or an artist.

## Configuration

Still exactly two profiles. COMMON ENEMY SENTRIES gained hold, shield, blast and collision settings, and strength, durability and speed percentages for Omni-Man and Soldier Boy. Powers no enemy has now, such as freeze and slam, are hidden from it, and your old saved values load safely.

## Tests

| Check | Result |
|---|---|
| Compilation and smoke test | Passed |
| Exactly five characters; Purple and Blue can't return | Passed (tests) |
| Each character's powers, damage, cooldowns, toggles | Passed (tests) |
| Time stop and resume | Passed (tests and real window) |
| Health bars, both profiles, saved settings | Passed (tests) |
| Full automated suite | All 394 passed |
| Time stop loop in a real window | All 16 checks passed; about 30 FPS at 1600×900 on Low, up from about 22 with six enemies |

### Live 90-second fight (`tools/roster_fight_check.py`)

The AI chose everything itself on default settings, with your health refilled to keep the fight going. Yellow stood still for 45 s, then hovered for 45 s. Beam counts are per decision while a beam is firing.

| Character | Beam | Punches | Holds | Shield | Blasts | Flew | Top speed |
|---|---:|---:|---:|---:|---:|---|---:|
| Superman | 119 | 13 | 5 | none | none | Yes | 73 m/s |
| Omni-Man | none | 46 | 10 | none | none | Yes | 96 m/s |
| Homelander | 117 | 9 | 7 | none | none | Yes | 57 m/s |
| Soldier Boy | none | 33 | 5 | 22 | 6 | No | 0 m/s |

Two things this run did **not** show:
- **Omni-Man's collisions:** he caused no collision blast in this final run (one in an earlier run), because he rarely hits anything. Tests cover the blast directly.
- **Top speeds:** a short fight doesn't reach full speed. Omni-Man's configured speed is the highest, and a test confirms that.

## Known limitations

- **Your saved enemy values still apply:** enemy Walking Speed 1 will make Soldier Boy crawl, since he can't fly. Enemy Flight Speed 111 also limits the flyers. **Reset Profile** on COMMON ENEMY SENTRIES restores the defaults.
- **Soldier Boy vs a flying player:** he can only reach you with the chest blast, which has a 90 m range.
- **Retired code:** freeze, slam and object-throw code stays because tests and shared classes use it, but no character can use it.
- **Sound:** every power reuses the one impact sample, and nobody has listened to it.
- **No human playtest:** balance is untested by a real player.
