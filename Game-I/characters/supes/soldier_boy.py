"""Soldier Boy: no flight, the fastest runner and the highest jump, the shield and radiation."""

from __future__ import annotations

from characters.costume_parts import *  # noqa: F403
from characters.definition import CharacterDefinition
from config.ability_cards import *  # noqa: F403

SHIELD_Y, SHIELD_Z = -.82, .24
KIT = CharacterKit(
    "RED", "SOLDIER BOY", False,
    "Ground-bound veteran. Full dark-brown beard, olive armour, scarf, and a shield he fights with.",
    parts=(*short_hair(HAIR_DARK_BROWN), *brows(HAIR_DARK_BROWN),
           *full_beard(BEARD_BROWN, BEARD_LIGHT_BROWN, 3),
           *boots(LEATHER), *gloves(LEATHER),
           *tuple((leg, "s", (0.0, -.56, .13), (.22, .17, .10), CHARCOAL, 0.0)     # knee pads
                  for leg in ("left_leg", "right_leg")),
           *tuple((arm, "s", (0.0, -.78, .02), (.17, .34, .19), CHARCOAL, 0.0)     # forearm guards
                  for arm in ("left_arm", "right_arm")),
           ("body", "s", (0.0, 1.62, .315), (.68, .50, .10), CHARCOAL, 0.0),      # chest armour
           ("body", "c", (0.0, 1.46, .372), (.50, .022, .012), DARK_GREEN, 0.0),  # plate seams
           ("body", "c", (0.0, 1.60, .385), (.54, .022, .012), DARK_GREEN, 0.0),
           ("body", "s", (-.47, 1.96, .02), (.38, .20, .38), DARK_GREEN, 12.0),   # shoulder armour
           ("body", "s", (.47, 1.96, .02), (.38, .20, .38), DARK_GREEN, -12.0),
           ("body", "s", (0.0, 2.10, .04), (.42, .13, .38), DARK_GREEN, 0.0),     # neck wrap
           ("body", "s", (0.0, 2.03, .09), (.46, .10, .36), OLIVE, 6.0),
           *star("body", (0.0, 1.76, .372), .18, ANTIQUE_GOLD),                  # chest insignia
           ("body", "s", (0.0, 1.02, .325), (.66, .13, .10), LEATHER, 0.0),       # broad belt
           ("body", "c", (0.0, 1.02, .385), (.10, .08, .02), SILVER, 0.0)),
    # Shield: broad top, narrow foot, built separately so a throw can take it off his arm.
    shield_parts=(("left_arm", "c", (0.0, SHIELD_Y + .12, SHIELD_Z), (.62, .46, .05), STEEL, 0.0),
           ("left_arm", "c", (0.0, SHIELD_Y - .17, SHIELD_Z), (.40, .40, .05), STEEL, 45.0),
           ("left_arm", "c", (0.0, SHIELD_Y + .12, SHIELD_Z + .03), (.54, .38, .02), SILVER, 0.0),
           ("left_arm", "s", (-.16, SHIELD_Y + .10, SHIELD_Z + .05), (.30, .08, .03), ANTIQUE_GOLD, 24.0),
           ("left_arm", "s", (.16, SHIELD_Y + .10, SHIELD_Z + .05), (.30, .08, .03), ANTIQUE_GOLD, -24.0),
           *star("left_arm", (0.0, SHIELD_Y + .02, SHIELD_Z + .06), .20, ANTIQUE_GOLD)),
    biology="compound_v",
    helmet_parts=(("body", "s", (0.0, 2.72, .16), (.53, .29, .64), rgb(58, 66, 44), 0.0),
                  ("body", "s", (0.0, 2.63, .18), (.55, .06, .67), rgb(38, 44, 30), 0.0),
                  *star("body", (0.0, 2.74, .47), .12, ANTIQUE_GOLD)),
    cape=False, body_scale=(1.08, 1.0, 1.06), super_jump=True)

ABILITIES = (
    card("radiation_blast", "Nuclear Radiation Blast", "1",
          "On until you press 1 again: every 3 seconds a huge green radioactive sphere goes off around him. "
          "He can walk and run as normal, and it never moves him. Range sets its size.",
          reach=2000, damage=20000, damage_start=1000),
    card("flying_punch", "Time-Stop High-Speed Flying Punch", "2",
          "Stops the world, launches him at the target at extreme speed, even one in the air, and one huge punch "
          "sends them flying. Time resumes, and he comes back to the ground: this is not flight.",
          damage=6000, speed=3000),
    card("aerial_grab_blast", "Time-Stop Aerial Grab and Blast", "3",
          "Stops the world, leaps up and grabs the nearest enemy, and a punch in the face sets off a huge "
          "spherical explosion that throws them far away. Range sets its size. Then time resumes.",
          damage=20000, speed=1500),
    card("radioactive_execution", "Time-Stop Radioactive Nuclear Execution", "4",
          "Stops the world, slams your enemy into the ground twice and punches them away. A nuclear sphere, his "
          "chest beam with them on fire in his hand, a last nuclear sphere, and he throws them into the ground. "
          "Range sets the size of the spheres.",
          damage=20000, speed=3000),
)

KEYLESS = (
        card("shield_combat", "Shield Combat", "", "", reach=300, damage=2500, speed=1000),
        card("shield_defence", "Shield Defence", "", "", reach=12),
        card("shield_throw", "Shield Throw", "", "", damage=5000, speed=1000),
        card("chest_blast", "Radioactive Chest Blast", "", "", damage=6000),
        card("nullification", "Power Nullification", "", ""),
        card("radioactive_discharge", "Maximum Radioactive Discharge", "", "", kind=ULTIMATE, damage=9000),
        card("chest_beam", "Radioactive Chest Beam", "", "", damage=3000, damage_unit="dmg/s", speed=3000),
    )

DEFINITION = CharacterDefinition(
    character_id="RED",
    order=5,
    default_team="enemy_team",
    kit=KIT,
    abilities=ABILITIES,
    keyless=KEYLESS,
    slots={"1": "radiation_blast", "2": "flying_punch", "3": "aerial_grab_blast",
            "4": "radioactive_execution"},
    passives=Passives(("Superhuman Strength", "Extreme Durability", "Superhuman Speed", "Unlimited Stamina",
                     "Enhanced Regeneration", "Radiation Resistance", "Extreme Longevity",
                     "Cannot Fly"),
                    strength=1.35, max_health=1100, resistance=45, impact_resistance=70,
                    knockback_resistance=55, radiation_resistance=90, collision_damage=40),
    powers=(
            "powers.soldier_boy:ShieldCombat",
            "powers.soldier_boy:ShieldThrow",
            "powers.soldier_boy:ShieldDefence",
            "powers.soldier_boy:ChestBlast",
            "powers.soldier_boy:Nullification",
            "powers.soldier_boy:RadioactiveDischarge",
            "powers.common:Dash",
            "powers.common:ThrowingGrab",
            "powers.chest_beam:RadioactiveChestBeam",
            "powers.soldier_boy_attacks:RadiationBlast",
            "powers.soldier_boy_attacks:FlyingPunchAttack",
            "powers.soldier_boy_attacks:AerialGrabBlastAttack",
            "powers.soldier_boy_attacks:RadioactiveExecutionAttack",
            "powers.universal:WorldTimeStop",
    ),
    palette=(rgb(69, 81, 59), rgb(86, 96, 66), rgb(48, 59, 44), rgb(48, 59, 44), rgb(169, 135, 67), rgb(69, 81, 59)),
    personality=(.12, 1.30, 2.3, -.15, 1.0),
    seed=2174,
    movement=dict(stride=1.15, step=1.1, arm_swing=.95, run_elbow=-96.0, walk_elbow=-6.0, idle_sway=.4, breath_rate=1.7, land_depth=1.1),
    stance=dict(chest=3.0, head=4.0, arms_out=14.0, run_lean=22.0, stride=1.25),
    punch=((150, 175, 105, 170), (205, 255, 185), -170.0, 30.0),
    impact=((120, 255, 110), (130, 255, 120, 225), 7, 3.0),
    card_tint=(102, 112, 76),
)
