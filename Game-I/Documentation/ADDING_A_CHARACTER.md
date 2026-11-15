# Adding a character

A new character is one Python file in `characters/supes/`. The game finds it at startup. Selection, teams, Powers & Abilities, the HUD, AI, combat and saves all pick it up with no other change.

## The short way

1. Copy `characters/supes/_template.py` to `characters/supes/your_name.py`. Files starting with an underscore are skipped, so the template itself never appears in the game.
2. Change `character_id`, the names and the description.
3. Start the game. Your character is in Character Selection under AVAILABLE. Add them to a team and press PLAY.

If the file has a mistake, the game starts without that character and prints why, for example `Character file your_name.py left out: power powers.superman:Beam does not exist`. The rest of the roster is not affected.

## What a character defines

| Field | What it is | Required |
|---|---|---|
| `character_id` | Stable ID in capitals. Saves use it, so never change it after playing. | yes |
| `kit` | Display name, description, whether they can fly, costume options (`CharacterKit`) | yes |
| `abilities` | The cards on keys, with their editable range, damage and speed | yes |
| `slots` | Key to ability: `{"1": "heat_vision"}` | yes |
| `passives` | Health, strength, resistances and trait names (`Passives`) | yes |
| `powers` | The code behind the abilities, as `"module:Class"` | yes |
| `keyless` | Abilities they have that no key reaches | no |
| `model` | Folder under `assets/characters/`. Defaults to `character_id`, and can borrow another character's body. | no |
| `palette` | Costume colours for lower-detail bodies | no |
| `movement`, `stance` | How they walk, run, fly and stand | no |
| `personality` | AI: reaction, aggression, aim rate, ranged bias, strafe | no |
| `default_team` | `my_team`, `enemy_team` or `available` (default). A save's own choice wins. | no |
| `run_speed`, `fly_speed`, `boost_speed` | Starting speeds in m/s. A value set on Powers & Abilities wins. | no |
| `punch`, `impact`, `impact_sound`, `cape_colors`, `card_tint` | Effects, sound and menu colour | no |
| `order` | Place on the roster lists | no |
| `seed` | Fixes their AI's random choices; generated if left out | no |
| `starts_as_player` | A brand-new save starts as this character | no |

## Powers

- **Reuse existing powers.** Any class in `powers/` can go on anyone: list it in `powers` and give it a card with the same ability ID. The template gives its character Superman's Heat Vision this way.
- **Write a new power.** Subclass the ability base in `powers/base.py` with its own `ability_id`, then name it in `powers`. It can live in your character's file.
- `F` in the air (Ground Slam) is added for everyone automatically. `T` (Time Stop) comes from `powers.universal:WorldTimeStop`.

## A body of their own

Bake a model into `assets/characters/<CHARACTER_ID>/` with `tools/character_pipeline/`, then remove `model=` from the definition. For a portrait, add `assets/portraits/<character_id in lower case>.png`, or run `tools/make_portraits.py` to render every character.

## What is not yet independent

- `YELLOW` (Sentry) is the first body the game builds, so that file must stay.
- Omni-Man's squad belongs to `GREEN`: `squad_summon` only works on him.
- Some powers expect a particular body part or partner, such as Soldier Boy's thrown shield. Try a borrowed power before relying on it.

Trying a character without touching the project: put its file in any folder and set `NLTL_EXTRA_SUPES` to that folder.
