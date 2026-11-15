"""Superman: the Man of Steel suit, heat vision and the classic one-fist flight."""

from __future__ import annotations

from characters.costume_parts import *  # noqa: F403
from characters.definition import CharacterDefinition
from config.ability_cards import *  # noqa: F403

KIT = CharacterKit(
    "WHITE", "SUPERMAN", True,
    "Man of Steel. Dark blue Kryptonian suit, steel-silver emblem and a deep red cape.",
    parts=(*short_hair(HAIR_BLACK), *brows(HAIR_BLACK),
           ("body", "s", (0.0, 2.70, .445), (.075, .12, .05), HAIR_BLACK, 20.0),  # forelock
           ("body", "s", (0.0, 1.72, .375), (.42, .36, .06), SILVER, 0.0),        # chest shield
           ("body", "s", (0.0, 1.72, .395), (.34, .28, .05), rgb(26, 44, 92), 0.0)),
    body_scale=(1.03, 1.0, 1.0), chest_s=SILVER)

ABILITIES = (
    card("heat_vision", "Heat Vision", "1",
          "Twin red beams, on until you press 1 again. Burns, cuts and melts whatever they touch.",
          damage=3000, damage_unit="dmg/s"),
    high_speed_attack(),
    time_stop(),
    card("ground_execution", "Time-Stop Brutal Heat Vision Execution", "4",
          "Stops the world, seizes your enemy by the neck, carries them up and punches them an enormous distance. "
          "He catches them before they land, burns their face with Heat Vision, and hurls them into the ground.",
          damage=10000, speed=3000),
    physical(),
)

KEYLESS = (
        card("kryptonian_vision", "Kryptonian Vision", "", ""),
        card("freeze_breath", "Freeze Breath", "", "", damage=1000, damage_unit="dmg/s", speed=400,
              speed_unit="%"),
        card("super_breath", "Super Breath", "", "", damage=2000, damage_unit="dmg/s"),
        card("solar_overcharge", "Solar Overcharge", "", "", kind=ULTIMATE, damage=8000),
    )

DEFINITION = CharacterDefinition(
    character_id="WHITE",
    order=1,
    default_team="enemy_team",
    kit=KIT,
    abilities=ABILITIES,
    keyless=KEYLESS,
    slots={"1": "heat_vision", "2": "high_speed_attack", "3": "time_stop",
              "4": "ground_execution"},
    passives=Passives(("Enhanced Strength", "Enhanced Durability", "Superhuman Speed",
                       "Flight", "Superhuman Hearing", "Enhanced Healing", "Unlimited Stamina",
                       "Space Survival"),
                      strength=1.6, max_health=1200, resistance=45, impact_resistance=80,
                      knockback_resistance=60, hearing_radius=600),
    powers=(
            "powers.superman:HeatVision",
            "powers.superman:FreezeBreath",
            "powers.superman:SuperBreath",
            "powers.superman:KryptonianVision",
            "powers.superman:SolarOvercharge",
            "powers.superman:GroundExecution",
            "powers.common:Melee",
            "powers.common:Dash",
            "powers.common:Grab",
            "powers.universal:HighSpeedAttack",
            "powers.universal:TimeStopNuclearExecution",
            "powers.universal:WorldTimeStop",
    ),
    palette=(rgb(20, 42, 104), rgb(36, 66, 140), rgb(9, 22, 66), rgb(14, 30, 84), rgb(26, 44, 96), rgb(120, 16, 24)),
    personality=(.20, .85, 2.5, .15, -1.2),
    seed=2063,
    movement=dict(stride=1.0, step=1.05, arm_swing=.6, idle_sway=.5, breath_rate=1.3, land_depth=.7,
                   flight_right_z=-3.0, flight_elbow=6.0),
    stance=dict(chest=-5.0, head=-3.0, arms_out=10.0, run_lean=10.0, stride=1.0),
    cape_colors=((.52, .05, .07), (.40, .04, .06)),
    punch=((70, 120, 255, 170), (120, 170, 255), -170.0, 30.0),
    impact=((150, 190, 255), (190, 220, 255, 230)),
    card_tint=(38, 62, 130),
)
