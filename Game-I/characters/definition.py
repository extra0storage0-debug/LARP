"""Everything one character is, in one place. No game imports: plain data, read by whichever system needs it.

A new character is one file in characters/supes/ holding a DEFINITION. See Documentation/ADDING_A_CHARACTER.md.
Only the first six fields have no default.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CharacterDefinition:
    character_id: str              # stable: saves and settings are keyed on it, so it never changes
    kit: object                    # display name, description, flight, costume parts (characters.costume_parts.CharacterKit)
    abilities: tuple               # the cards on keys, with their editable values (config.ability_cards)
    slots: dict                    # key -> ability id
    passives: object               # health, strength and other fixed traits (config.ability_cards.Passives)
    powers: tuple                  # the code behind the abilities, as "module:Class"

    keyless: tuple = ()            # abilities the character has that no key reaches
    order: int = 100               # place on every roster list
    default_team: str = "available"  # "my_team", "enemy_team" or "available"; a save's own choice always wins
    starts_as_player: bool = False   # a new save starts as this character
    model: str | None = None       # folder under assets/characters, if not the character's own
    palette: tuple = (((.3, .3, .3),) * 6)  # suit, lit suit, shaded suit, accent, trim, cape
    personality: tuple = (.2, 1.0, 2.4, 0.0, 1.0)  # AI: reaction, aggression, aim rate, ranged bias, strafe
    seed: int | None = None        # AI's random choices; stable, so that a new character changes nobody else's
    movement: dict = field(default_factory=dict)  # walk, run and flight style (movement.character_styles.Style)
    stance: dict | None = None     # how they stand and lean (characters.skinned_visual)
    cape_colors: tuple | None = None
    punch: tuple = ((235, 235, 235, 170), (240, 240, 240), -165.0, -30.0)  # trail, flash, right and left arm swing
    impact: tuple = ((225, 225, 225), (235, 235, 235, 230))  # ground slam: tint, ring, optional dust puffs and burst
    card_tint: tuple = (150, 150, 150)  # the character's colour on menus
    impact_sound: str | None = None     # played by the ground slam, on top of the explosion
    run_speed: float | None = None      # m/s; None moves as the profile and passives say
    fly_speed: float | None = None
    boost_speed: float | None = None
