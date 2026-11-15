"""Damageable towers with batched procedural facade geometry."""

from __future__ import annotations

from ursina import Entity, Mesh, color

from world.interactive_objects import DestructibleEntity
from world.lighting import CITY_SURFACE_SHADER
from movement.flight_physics import Vec3 as SimVec3


class Building(DestructibleEntity):
    def __init__(self, game, position, size, tint, seed: int):
        chart_x, chart_y, chart_z = position
        health = 160.0 + size[1] * 7.0
        mapped = game.planet.point_from_local(chart_x, chart_z, chart_y)
        super().__init__(game, (mapped.x, mapped.y, mapped.z), size, tint, health, "damageable-building")
        self.chart_x, self.chart_z = chart_x, chart_z
        game.planet.orient_entity(self, SimVec3(mapped.x, mapped.y, mapped.z))
        self.anchored = True
        rows = max(2, min(9, int(size[1] / 5.0)))
        columns = max(2, min(5, int(size[0] / 5.0)))
        vertices = []
        triangles = []
        colors = []
        night_vertices = []
        night_triangles = []
        night_colors = []

        def add_face(points, tint_value):
            first = len(vertices)
            vertices.extend(points)
            triangles.extend((first, first + 1, first + 2,
                              first, first + 2, first + 3))
            colors.extend((tint_value,) * 4)

        def add_night_face(points):
            first = len(night_vertices)
            night_vertices.extend(points)
            night_triangles.extend((first, first + 1, first + 2,
                                    first, first + 2, first + 3))
            night_colors.extend((color.rgb32(255, 190, 99),) * 4)

        def add_window(x, y, z, width, height, tint_value):
            add_face(((x-width*.5, y-height*.5, z),
                      (x+width*.5, y-height*.5, z),
                      (x+width*.5, y+height*.5, z),
                      (x-width*.5, y+height*.5, z)), tint_value)

        # Mesh-local geometry is normalized to the scaled cube. Combining the
        # shell and windows leaves one render entity per damageable tower.
        cube_faces = (
            ((-.5,-.5,.5),(.5,-.5,.5),(.5,.5,.5),(-.5,.5,.5)),
            ((.5,-.5,-.5),(-.5,-.5,-.5),(-.5,.5,-.5),(.5,.5,-.5)),
            ((.5,-.5,.5),(.5,-.5,-.5),(.5,.5,-.5),(.5,.5,.5)),
            ((-.5,-.5,-.5),(-.5,-.5,.5),(-.5,.5,.5),(-.5,.5,-.5)),
            ((-.5,.5,.5),(.5,.5,.5),(.5,.5,-.5),(-.5,.5,-.5)),
            ((-.5,-.5,-.5),(.5,-.5,-.5),(.5,-.5,.5),(-.5,-.5,.5)),
        )
        for face in cube_faces:
            add_face(face, tint)

        window_tint = color.rgb32(124, 170, 197)
        roof_tint = color.rgb32(43, 60, 83)
        for row in range(rows):
            y = -.42 + row * .84 / max(1, rows - 1)
            for column in range(columns):
                x = -.38 + column * .76 / max(1, columns - 1)
                width, height = .55 / size[0], .85 / size[1]
                for z in (-.501, .501):
                    points = ((x-width*.5, y-height*.5, z),
                              (x+width*.5, y-height*.5, z),
                              (x+width*.5, y+height*.5, z),
                              (x-width*.5, y+height*.5, z))
                    add_face(points, window_tint)
                    add_night_face(points)
                for x_side in (-.501, .501):
                    points = ((x_side, y-height*.5, x-width*.5),
                              (x_side, y-height*.5, x+width*.5),
                              (x_side, y+height*.5, x+width*.5),
                              (x_side, y+height*.5, x-width*.5))
                    add_face(points, window_tint)
                    add_night_face(points)
        for z in (-.505, .505):
            add_window(0, .32, z, .86, .20 / size[1], roof_tint)

        self.model = None
        self.color = color.white
        self.original_tint = color.white
        self.debris_tint = tint
        self.facade_detail = Entity(parent=self,
                                    model=Mesh(vertices=vertices, triangles=triangles,
                                               colors=colors, static=True),
                                    color=color.white, double_sided=True, collider=None,
                                    shader=CITY_SURFACE_SHADER)
        self.night_windows = Entity(parent=self,
                                    model=Mesh(vertices=night_vertices,
                                               triangles=night_triangles,
                                               colors=night_colors, static=True),
                                    color=color.rgba32(255, 190, 99, 0),
                                    double_sided=True, transparency=True, unlit=True,
                                    collider=None, name="emissive-city-windows")
