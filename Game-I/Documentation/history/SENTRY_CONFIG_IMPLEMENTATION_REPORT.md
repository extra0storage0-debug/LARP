> **Superseded.** The final specification removed the systems described here. See SENTRY_FINAL_OVERHAUL_REPORT.md.

# Sentry configuration report

Date: 2026-11-02. The two-profile system already existed (built earlier the same day), so this work audited it against the brief and fixed the gaps instead of rebuilding it.

Backup: `SENTRY_backup_before_config_system_2026-11-02` (261 files, hash-verified; excludes `.venv` and `Delete`).

## Gaps fixed

| Problem | Now |
|---|---|
| Out-of-range numbers were silently clamped, and decimals rounded | Refused with a message; the old value stays. Applies to both settings screens and to saved files |
| Typing 0 in the quick panel silently became 1; bad entries silently became the default | Refused with a message |
| Typing after clicking added to the old number (82, then 90, gave 8290) | The first digit replaces the value; Backspace edits it |
| A 19th digit was dropped with no message | Message: "18 digits maximum" |
| Closing the panel lost unapplied changes | Closing applies and saves them |
| Resetting the enemy profile copied the player's speeds (9,999 m/s) | Enemies have their own defaults: 50 walking, 100 flight, 500 boost |
| Boost Multiplier 0 crashed the camera (division by zero) | Minimum is now 1% |
| A huge blast radius hung the game | The search stops at the island's width |
| FOV of 180° or more breaks the projection | Maximum 179 |
| Heat "Visual Intensity" also changed knockback, tree damage and crater size | It is visual only; gameplay at the default value is unchanged |

## Defaults and units

Defaults were not changed. They come from the game's original values.

| Setting | Default | Unit |
|---|---|---|
| Follow distance / height | 950 / 355 | cm |
| Field of view | 82 | degrees (1–179) |
| Mouse sensitivity | 100 | % |
| Walking / flight / boost speed | 50 / 100 / 500 | m/s |
| Player / enemy health | 100 / 300 | points |

Names ending `_cs` are hundredths of a second, and `_cm` are centimetres. Enemy damage uses 0.01 units, so 240 means 2.4.

## Tests

| Check | Result |
|---|---|
| Compilation, smoke test | Passed |
| Automated tests | All 363 passed (includes the time-stop tests) |
| Extreme values: every number on both profiles at its largest allowed value and its minimum, in a running game | 0 problems after the fixes above |
| Your settings files during all of this | Unchanged (hash-checked) |

## Known limitations

- **Your saved values still apply:** enemy Walking Speed 1, enemy Flight Speed 111, enemy Heat Visual Intensity 100,000%, and your Boost Speed 1 are lower than your 9,999 flight speed. **Reset Profile** restores the defaults.
- **Apply on demand:** changes apply on Apply or on closing the panel, not per keystroke. The game is paused while the panel is open, so the result is the same.
- **Hand-edited files:** a value below 1 in `sentry_settings.json` still loads as 1.
- **Cloud sync:** if OneDrive blocks the atomic file replace, saving falls back to a direct write.
- **Extreme values:** the stress run proves no crash or hang over a few frames, not that play is sensible at those values.
- **No human test:** settings entry was driven through the game's input handlers, not clicked by hand.
