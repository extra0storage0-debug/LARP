"""Omni-Man: heavy Viltrumite power, and the squad he summons. The squad's own costumes are in characters/costume_parts.py."""

from __future__ import annotations

from characters.costume_parts import *  # noqa: F403
from characters.definition import CharacterDefinition
from config.ability_cards import *  # noqa: F403

KIT = CharacterKit(
    "GREEN", "OMNI-MAN", True,
    "Nolan Grayson. Mature and heavily built: full black-and-grey beard, white and red suit.",
    parts=(*short_hair(HAIR_BLACK), *brows(HAIR_BLACK), *full_beard(BEARD_BLACK, BEARD_GREY),
           ("body", "s", (-.228, 2.63, .20), (.05, .15, .10), BEARD_GREY, 0.0),  # grey temples
           ("body", "s", (.228, 2.63, .20), (.05, .15, .10), BEARD_GREY, 0.0),
           ("body", "s", (0.0, 1.24, .335), (.62, .46, .06), RED, 0.0),          # red lower torso
           ("body", "s", (0.0, 1.72, .375), (.40, .36, .06), RED, 0.0),          # red O emblem
           ("body", "s", (0.0, 1.72, .395), (.27, .23, .06), WHITE, 0.0),
           *thighs(RED), *boots(WHITE), *gloves(RED)),
    body_scale=(1.12, 1.03, 1.10))

ABILITIES = (
    card("squad_summon", "Summon Viltrumites and Invincible", "1",
          "On until you press 1 again: Viltrumites and Invincible fight at your side, for part of every cycle. "
          "Range is how far they will go after an enemy. Who comes, and for how long, is set below.",
          reach=5000,
          extra=(Param(SQUAD_VILTRUMITES, "", 5.0, minimum=0.0, linear=True),
                 Param(SQUAD_MARK, TOGGLE, 1.0, minimum=0.0, linear=True),
                 Param(SQUAD_ACTIVE, "s", 3600.0, start=30.0),
                 Param(SQUAD_CYCLE, "s", 3600.0, start=60.0))),
    card("high_speed_attack", "Time-Stop Shockwave Punch", "2",
          "Stops the world, charges the nearest enemy at ultra-high speed and lands one huge punch, with a "
          "shockwave that hurts everything around it. He flies on past them, and time resumes.",
          damage=6000, speed=3000),
    time_stop(),
    card("speed_execution", "Time-Stop Triple Impact Execution", "4",
          "Stops the world and hits the nearest enemy three times at full flight speed, each with its own "
          "explosion. His squad assaults them for 3 seconds, then he sets them alight and throws them far away. "
          "Range sets the size of the explosions.",
          damage=20000, speed=3000),
    physical("Viltrumite Physical Combat"),
)

KEYLESS = (
        card("flight_charge", "High-Speed Flight Charge", "", "", damage=5000, speed=1000),
        card("shockwave_punch", "Viltrumite Shockwave Punch", "", "", damage=6000),
        card("ground_slam", "Ground Slam", "", "", damage=6000, speed=1000),
        card("dive_bomb", "Viltrumite Dive Bomb", "", "", kind=ULTIMATE, damage=9000, speed=1000),
    )

DEFINITION = CharacterDefinition(
    character_id="GREEN",
    order=4,
    default_team="enemy_team",
    kit=KIT,
    abilities=ABILITIES,
    keyless=KEYLESS,
    slots={"1": "squad_summon", "2": "high_speed_attack", "3": "time_stop",
              "4": "speed_execution"},
    passives=Passives(("Extreme Strength", "Extreme Durability", "High-Speed Flight", "Unlimited Stamina",
                       "Accelerated Healing", "Superhuman Reflexes", "Extreme Longevity",
                       "Space Survival"),
                      strength=1.9, max_health=1250, resistance=50, impact_resistance=90,
                      knockback_resistance=70, speed=1.15, collision_damage=90),
    powers=(
            "powers.omni_man:SquadSummon",
            "powers.omni_man:ShockwaveAttack",
            "powers.omni_man:SpeedExecution",
            "powers.omni_man:FlightCharge",
            "powers.omni_man:GroundSlam",
            "powers.omni_man:ShockwavePunch",
            "powers.omni_man:DiveBomb",
            "powers.common:Melee",
            "powers.common:Dash",
            "powers.common:Grab",
            "powers.universal:TimeStopNuclearExecution",
            "powers.universal:WorldTimeStop",
    ),
    palette=(rgb(233, 233, 233), rgb(246, 245, 240), rgb(200, 200, 200), rgb(201, 31, 45), rgb(146, 23, 36), rgb(146, 23, 36)),
    personality=(.28, 1.15, 2.1, -.05, -.8),
    seed=2100,
    movement=dict(stride=.86, step=.92, arm_swing=.8, run_elbow=-90.0, walk_elbow=-22.0, idle_sway=.7, breath_rate=1.2,
                   land_depth=1.4, flight_elbow=-32.0),
    stance=dict(chest=-4.0, head=-1.0, arms_out=12.0, run_lean=11.0, stride=1.0),
    cape_colors=((.60, .06, .10), (.45, .05, .08)),
    punch=((225, 50, 45, 170), (240, 240, 240), 30.0, -195.0),
    impact=(None, (190, 170, 140, 220), 10, 3.0),
    card_tint=(220, 220, 220),
)
