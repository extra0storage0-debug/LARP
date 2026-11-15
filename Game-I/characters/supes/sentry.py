"""Sentry: golden energy, the shield, molecular manipulation and the Void. A new save starts as him."""

from __future__ import annotations

from characters.costume_parts import *  # noqa: F403
from characters.definition import CharacterDefinition
from config.ability_cards import *  # noqa: F403

KIT = CharacterKit(
    "YELLOW", "SENTRY", True,
    "Robert Reynolds. Blue suit with gold insignia, belt, gloves and boots, a golden cape and swept-back blond hair.",
    chest_s=(0.0, 0.0, 0.0))

ABILITIES = (
    card("void_form", "Void Transformation", "1",
          "On until you press 1 again, in cycles of 60 seconds. For the first 10 he is a black shadow and your enemy "
          "is nothing but a shadow on the ground, unable to move or attack. For the other 50 he is himself, and "
          "they are a black figure, slowed, weakened and taking Void damage.",
          damage=2000, damage_unit="dmg/s"),
    high_speed_attack(),
    time_stop(),
    card("void_nuclear_execution", "Void Nuclear Execution", "4",
          "Takes your enemy by the neck and sets off a nuclear sphere, throws them down, holds them as a shadow for "
          "5 seconds, sends his Void copy at them for 5, then charges and one last throw that detonates on landing. "
          "Range sets the size of the explosions.",
          damage=20000, speed=3000),
    physical(),
)

KEYLESS = (
        card("energy_projection", "Energy Projection", "", "", damage=5000, speed=3000),
        card("golden_shield", "Golden Energy Shield", "", "", reach=12),
        card("molecular_manipulation", "Molecular Manipulation", "", "", damage=8000),
        card("void_tendrils", "Void Tendrils", "", "", damage=2000, damage_unit="dmg/s", speed=1000),
        card("void_unleashed", "Void Unleashed", "", "", kind=ULTIMATE, damage=6000),
        card("chest_beam", "Golden Chest Beam", "", "", damage=3000, damage_unit="dmg/s", speed=3000),
        massive_blast(),
    )

DEFINITION = CharacterDefinition(
    character_id="YELLOW",
    order=3,
    default_team="my_team",
    starts_as_player=True,
    kit=KIT,
    abilities=ABILITIES,
    keyless=KEYLESS,
    slots={"1": "void_form", "2": "high_speed_attack", "3": "time_stop",
               "4": "void_nuclear_execution"},
    passives=Passives(("Energy Manipulation", "Extreme Strength", "Extreme Durability", "Extreme Speed",
                        "Advanced Regeneration", "Energy Absorption", "Flight",
                        "Enhanced Perception", "Unlimited Stamina"),
                       strength=1.7, max_health=1300, resistance=50, impact_resistance=80,
                       knockback_resistance=60, absorb=8, speed=1.2,
                       collision_damage=70, hearing_radius=800),
    powers=(
            "powers.sentry_powers:EnergyProjection",
            "powers.sentry_powers:GoldenShield",
            "powers.sentry_powers:MolecularManipulation",
            "powers.sentry_powers:VoidTendrils",
            "powers.sentry_powers:VoidUnleashed",
            "powers.common:Melee",
            "powers.common:Dash",
            "powers.common:Grab",
            "powers.chest_beam:GoldenChestBeam",
            "powers.bombs:MassiveBlast",
            "powers.void:VoidForm",
            "powers.void:VoidNuclearExecutionAbility",
            "powers.universal:HighSpeedAttack",
            "powers.universal:TimeStopNuclearExecution",
            "powers.universal:WorldTimeStop",
    ),
    palette=(rgb(220, 153, 24), rgb(242, 180, 40), rgb(188, 130, 20), rgb(10, 17, 34), rgb(255, 193, 48), rgb(10, 17, 34)),
    personality=(.16, 1.05, 2.7, .05, 1.2),
    seed=2026,
    movement=dict(stride=.9, step=.9, arm_swing=.5, walk_elbow=-16.0, idle_sway=1.2, breath_rate=1.8, land_depth=.8,
                    flight_right_z=16.0, flight_elbow=-18.0),
    stance=dict(chest=-3.0, head=-2.0, arms_out=8.0, run_lean=9.0, stride=1.0),
    cape_colors=((.08, .15, .36), (.95, .72, .20)),
    punch=((255, 200, 60, 170), (255, 215, 90), -165.0, -165.0),
    impact=((255, 205, 70), (255, 225, 110, 235)),
    card_tint=(232, 185, 46),
)
