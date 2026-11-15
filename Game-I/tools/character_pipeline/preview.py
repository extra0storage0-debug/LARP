"""Look at baked bodies without the game: python preview.py out.png NAME [NAME...] [--close] [--back] [--pose punch|fly|run]"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("names", nargs="+")
    parser.add_argument("--close", action="store_true")
    parser.add_argument("--back", action="store_true")
    parser.add_argument("--side", action="store_true")
    parser.add_argument("--pose", default="")
    parser.add_argument("--high", action="store_true")
    parser.add_argument("--speed", type=float, default=0.0)
    args = parser.parse_args()
    from ursina import DirectionalLight, Entity, Ursina, application, camera, color, scene, window
    from panda3d.core import Filename, NodePath
    app = Ursina(title="preview", size=(1600, 900), borderless=False, development_mode=False, show_ursina_splash=False)
    import game.art_style  # noqa: F401
    from characters import skinned_visual as sv
    if args.high:
        sv.set_detail_quality("high")
    window.color = color.rgb(.62, .72, .84)
    scene.set_shader_input("u_fog_density", 0.0)
    ground = Entity(model="plane", scale=200, y=-.25, color=color.rgb(.32, .40, .22))
    light = DirectionalLight(shadow_map_resolution=(2048, 2048), shadows=True, color=color.rgb(1.6, 1.5, 1.35))
    light.look_at((-.6, -.7, -.9))
    light.shadow_map_resolution = (2048, 2048)
    visuals = []
    spacing = 2.4
    for index, name in enumerate(args.names):
        owner = Entity(position=((index - (len(args.names) - 1) / 2) * spacing, .25, 0))
        visual = sv.SkinnedVisual(owner, name)
        if args.back:
            owner.rotation_y = 180
        if args.side:
            owner.rotation_y = 90
        visuals.append(visual)
        if args.pose == "punch":
            visual.right_arm.rotation_x = -95.0
            visual.left_arm.rotation_x = 15.0
            visual.left_elbow.rotation_x = -100.0
            visual.right_leg.rotation_x = 22.0
            visual.left_leg.rotation_x = -28.0
        elif args.pose == "fly":
            visual.left_arm.rotation_x = visual.right_arm.rotation_x = -168.0
            visual.left_leg.rotation_x = 5.0
            visual.right_leg.rotation_x = -7.0
            visual.pose_root.setP(-80)
            visual.pose_root.setZ(0)
            owner.y = 2.0
        elif args.pose == "run":
            visual.left_leg.rotation_x = -48.0
            visual.right_leg.rotation_x = 48.0
            visual.left_arm.rotation_x = 40.0
            visual.right_arm.rotation_x = -40.0
            visual.left_elbow.rotation_x = visual.right_elbow.rotation_x = -78.0
            visual.set_breathing(1.0, 30.0, False)
        elif args.pose == "hips":
            for arm, elbow, side in ((visual.left_arm, visual.left_elbow, 1.0), (visual.right_arm, visual.right_elbow, -1.0)):
                arm.rotation_x, arm.rotation_z = 8.0, 40.0 * side
                elbow.rotation_x, elbow.rotation_z = -12.0, -100.0 * side
        for _ in range(240):  # let the cape settle under whatever the character is doing
            visual.step_cape(1.0 / 60.0, (0.0, 0.0, args.speed))
            visual.set_breathing(1.0 / 60.0, 0.0, False)
    if args.close:
        camera.position = ((len(args.names) - 1) * 0, 2.86, 1.25)
        camera.rotation_x = 0.0
        camera.fov = 32
    else:
        width = max(1, len(args.names)) * spacing
        camera.position = (0, 1.55, -(5.0 + width * .82) if not args.close else 1.0)
        camera.rotation = (0, 0, 0)
        camera.fov = 45
    if args.close:
        camera.rotation_y = 180
    else:
        # face the fronts: the body faces +z, so the camera sits on +z and looks back
        camera.z = -camera.z
        camera.rotation_y = 180
    for _ in range(4):
        app.step()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    application.base.win.saveScreenshot(Filename.fromOsSpecific(args.out))
    application.base.userExit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
