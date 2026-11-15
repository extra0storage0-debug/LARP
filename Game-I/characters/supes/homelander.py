"""Homelander: gold eagle armour, the flag cape and laser vision."""

from __future__ import annotations

from characters.costume_parts import *  # noqa: F403
from characters.definition import CharacterDefinition
from config.ability_cards import *  # noqa: F403

KIT = CharacterKit(
    "BLACK", "HOMELANDER", True,
    "Royal blue suit, gold eagle shoulders, red gloves and boots, and an American-flag cape.",
    parts=(*short_hair(HAIR_BLOND), *brows(HAIR_BLOND), *boots(RED), *gloves(RED),
           ("body", "s", (-.46, 1.98, .02), (.42, .17, .38), GOLD, 14.0),        # eagle shoulders
           ("body", "s", (.46, 1.98, .02), (.42, .17, .38), GOLD, -14.0),
           ("body", "s", (-.20, 1.76, .36), (.42, .09, .05), GOLD, 22.0),        # eagle wings
           ("body", "s", (.20, 1.76, .36), (.42, .09, .05), GOLD, -22.0),
           ("body", "s", (0.0, 1.70, .385), (.13, .22, .05), GOLD, 0.0),
           ("body", "s", (0.0, 2.13, .03), (.40, .12, .34), ROYAL, 0.0),         # blue collar
           ("body", "s", (0.0, 2.08, .05), (.42, .035, .36), GOLD, 0.0)),
    flag_cape=True, body_scale=(.98, 1.0, .98), biology="compound_v")

ABILITIES = (
    card("laser_vision", "Laser Vision", "1",
          "Eye lasers, on until you press 1 again, burning and cutting whatever they touch.",
          damage=3000, damage_unit="dmg/s"),
    high_speed_attack(),
    time_stop(),
    card("neck_laser_execution", "Aerial Laser Execution + Clone Assault", "4",
          "Lifts your enemy by the neck and burns their face with his lasers for 4 seconds. Four clones of him "
          "attack them for 3 seconds, he juggles them for 2, and he throws them far down into the ground.",
          damage=5000, speed=3000),
    physical(),
)

KEYLESS = (
        card("aerial_charge", "High-Speed Aerial Charge", "", "", damage=5000, speed=1000),
        card("enhanced_senses", "Enhanced Senses / X-ray", "", ""),
        card("laser_overdrive", "Maximum Laser Overdrive", "", "", kind=ULTIMATE, damage=8000),
    )

DEFINITION = CharacterDefinition(
    character_id="BLACK",
    order=2,
    default_team="enemy_team",
    kit=KIT,
    abilities=ABILITIES,
    keyless=KEYLESS,
    slots={"1": "laser_vision", "2": "high_speed_attack", "3": "time_stop",
              "4": "neck_laser_execution"},
    passives=Passives(("Super Strength", "Super Durability", "Super Speed", "Superhuman Reflexes",
                       "Enhanced Hearing and Smell", "Flight", "Accelerated Healing",
                       "Unlimited Stamina"),
                      strength=1.4, max_health=900, resistance=35, impact_resistance=70,
                      knockback_resistance=50, speed=1.15, hearing_radius=700),
    powers=(
            "powers.homelander:LaserVision",
            "powers.homelander:AerialCharge",
            "powers.homelander:EnhancedSenses",
            "powers.homelander:LaserOverdrive",
            "powers.homelander:NeckLaserExecutionAbility",
            "powers.common:Melee",
            "powers.common:Dash",
            "powers.common:Grab",
            "powers.universal:HighSpeedAttack",
            "powers.universal:TimeStopNuclearExecution",
            "powers.universal:WorldTimeStop",
    ),
    palette=(rgb(24, 61, 117), rgb(40, 91, 155), rgb(16, 41, 78), rgb(16, 41, 78), rgb(214, 172, 70), rgb(24, 61, 117)),
    personality=(.10, 1.20, 3.0, .10, 1.4),
    seed=2137,
    movement=dict(stride=.82, step=1.2, arm_swing=.28, run_elbow=-62.0, walk_elbow=-5.0, idle_sway=.2, breath_rate=1.1,
                   land_depth=.45, flight_right_z=-4.0),
    stance=dict(chest=-6.0, head=-6.0, arms_out=7.0, run_lean=7.0, stride=.9),
    punch=((40, 70, 190, 170), (255, 70, 50), -150.0, -40.0),
    impact=((255, 45, 35), (255, 70, 50, 235)),
    card_tint=(24, 61, 117),
)
