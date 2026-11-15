# Game settings

Press **P** or use the **CONFIG** HUD button to open the settings panel. Click a value, type a number, and press Enter or click **Apply**. **Reset** restores defaults. Applying and resetting save the values to `config/sentry_settings.json`.

All eight settings are integers bounded from 1 to 999,999. Missing or invalid stored values use the defaults below.

| Setting | Default | Used by |
| --- | ---: | --- |
| Flight Speed | 100 | Flight cruise speed |
| Flight Boost Speed | 500 | Flight boost speed |
| Ground Speed | 50 | Walking and running speed |
| Heat Vision Damage | 100 | Heat vision damage rate |
| Heat Vision Range | 500 | Heat vision targeting range |
| Freeze Breath Range | 100 | Freeze breath targeting range |
| Throwing Force | 500 | Force applied to thrown objects |
| Ground Impact Power | 100 | Ground impact damage and force scaling |

Graphics settings use the separate `settings.json` file. Press **1**, **2**, or **3** to select Low, Medium, or High; changes save automatically. The current quality presets set render distance, civilian count, debris lifetime, resolution, and lighting quality.

Controls are defined centrally in `game/controls.py`: WASD movement, mouse and arrow camera orbit, Space/Home rise, Ctrl/End descend, F flight/impact, Shift/Alt flight speed, Q camera reset, E grab/release, Period heat vision/throw, C freeze breath, Z ground super speed, P settings, K fullscreen, Esc pause, and 1–3 quality.
