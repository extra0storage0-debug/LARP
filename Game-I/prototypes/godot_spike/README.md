# Godot rendering test

This folder holds no game logic. It decides one question: can Godot draw the game's character models and a comparable
scene on this laptop inside the agreed frame budget?

Scene: five skinned characters at full detail, posed by code every frame; capes; a 1024 shadow map; lowest SSAO; 300
instanced trees; subdivided terrain; a 400-particle burst every 3 seconds.

Copy `NAME.glb` files from `tools/character_pipeline/export_glb.py` to `models/` (they are not stored in git), then:

    Godot_v4.7.2-stable_win64.exe --path . --import
    Godot_v4.7.2-stable_win64.exe --path . --rendering-method mobile --resolution 1600x900 -- seconds=60 out=C:/path/result.json

The result is in `Documentation/ENGINE_DECISION.md`.
