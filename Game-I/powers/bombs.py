"""Sentry's and Soldier Boy's key 4: the massive blast."""

from __future__ import annotations

from powers.aiming import center_of
from powers.base import Ability
from powers.vitals import EXPLOSION

MAX_CRATER = 30.0


class MassiveBlast(Ability):
    """Key 4: one huge sphere around the character, once per press."""

    ability_id = "massive_blast"
    survives_nullification = True

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.blasts = 0

    def press(self) -> None:
        if not self.usable():
            return
        self.blasts += 1
        owner = self.owner
        radius = self.area(.1, 220.0)
        self.combat.blast(owner, center_of(owner), radius, self.p("damage"), self.force(80.0, 180.0),
                          kind=EXPLOSION, crater=(min(MAX_CRATER, radius * .4), 8.0, "massive-blast"),
                          cracks=True, burst_scale=3.0, even_damage=True)
        self.say("MASSIVE BLAST")

    def reset(self) -> None:
        super().reset()
        self.blasts = 0
