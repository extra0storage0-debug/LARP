"""Open every screen of the game in a real window, from copies of the real saves, and look at what it says.

Pictures come from the game's own window buffer and from nothing else on the screen.

    python tools/ui_check.py --out <folder>
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
BANNED = re.compile(r"\b(super)?hero(es)?\b|\bsaviou?r\b|\bvillains?\b|epstein", re.I)
# "Sentry" is a character's name. On screen it may only ever be that.
OLD_NAME = re.compile(r"\b(Sentry|sentry)\b(?!'s)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="nltl_ui_"))
    for name, variable in (("character_roster.json", "SENTRY_ROSTER_FILE"), ("character_powers.json", "SENTRY_POWER_FILE"), ("sentry_profiles.json", "SENTRY_PROFILE_FILE")):
        shutil.copy(ROOT / "config" / name, folder / name)
        os.environ[variable] = str(folder / name)
    os.environ["SENTRY_DESTRUCTION_SAVE"] = str(folder / "damage.json")
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)

    import main as launcher
    from panda3d.core import Filename
    from ursina import Text, application, scene, window
    from characters.roster import ROSTER_IDS
    from config.branding import GAME_TITLE
    from config.sentry_profiles import CATEGORIES
    app, game = launcher.build_game("onscreen")
    application.asset_folder = ROOT
    results: list = []
    seen: set = set()

    def check(name: str, passed: bool, detail="") -> None:
        results.append({"name": name, "passed": bool(passed), "detail": str(detail)[:300]})
        print(("PASS " if passed else "FAIL ") + name + (f"  ({detail})" if detail and not passed else ""), flush=True)

    def frames(count: int = 6) -> None:
        for _ in range(count):
            app.step()

    def shot(name: str) -> None:
        frames()
        application.base.win.saveScreenshot(Filename.from_os_specific(str(out / f"{name}.png")))

    def words(screen: str) -> None:
        """Every piece of text now showing."""
        bad = []
        for entity in scene.entities:
            if isinstance(entity, Text) and entity.enabled and entity.text:
                parent, shown = entity, True
                while parent is not None and parent is not scene:
                    if not getattr(parent, "enabled", True):
                        shown = False
                        break
                    parent = getattr(parent, "parent", None)
                if shown:
                    text = entity.text
                    seen.add(text)
                    if BANNED.search(text):
                        bad.append(text)
                    if OLD_NAME.search(text):
                        bad.append(text)
        check(f"{screen}: no old words on screen", not bad, bad[:4])

    check("window title", window.title == GAME_TITLE, window.title)
    icon = Path(str(window.icon))
    check("window icon is the game's own", icon.name == "icon.ico" and icon.exists(), window.icon)
    fonts = {getattr(entity, "font", None) for entity in scene.entities if isinstance(entity, Text)}
    check("text uses the game's fonts", all(font is not None for font in fonts) and Text.default_font.startswith("Barlow"), Text.default_font)

    # -- the title screen
    game.show_title()
    frames()
    check("title: shown, game waiting", game.at_title and game.main_menu.enabled and not game.hud.status.enabled)
    before = game.elapsed
    frames(10)
    check("title: the world is not running behind it", game.elapsed == before)
    shot("01_main_menu")
    words("title")
    menu = game.main_menu
    menu.buttons[1].on_click()
    frames()
    check("title: CHARACTER SELECTION opens", game.team_panel.visible and not menu.enabled)
    shot("02_character_selection")
    words("character selection")
    game.input("escape")
    frames()
    check("title: closing it comes back", menu.enabled and game.at_title and not game.team_panel.visible)
    menu.buttons[2].on_click()
    frames()
    check("title: POWERS & ABILITIES opens", game.power_panel.visible and not menu.enabled)
    shot("03_powers_and_abilities")
    words("powers")
    for character_id in ROSTER_IDS:
        game.power_panel.select_character(character_id)
        frames(2)
        words(f"powers, {character_id}")
    game.input("escape")
    frames()
    check("title: closing powers comes back", menu.enabled and not game.power_panel.visible)
    menu.buttons[3].on_click()
    frames()
    check("title: GAME SETTINGS opens", game.settings_page.enabled and not menu.enabled)
    shot("04_game_settings")
    words("settings")
    for category, _label in CATEGORIES:
        game.settings_page.show_category(category)
        frames(2)
        words(f"settings, {category}")
    game.input("escape")
    frames()
    check("title: closing settings comes back", menu.enabled and not game.settings_page.enabled)
    game.input("f")
    game.input("w")
    frames(2)
    check("title: game keys do nothing", game.at_title and not game.team_panel.visible)
    held = [key for key in ("f", "w")]
    for key in held:
        game.input(f"{key} up")
    menu.play_button.on_click()
    frames()
    check("PLAY starts the game", not game.at_title and not menu.enabled and game.hud.status.enabled)
    for _ in range(30):
        game.update(1 / 60)
        app.step()
    check("the world runs after PLAY", game.elapsed > 0.0)
    shot("05_hud")
    words("HUD")

    # -- Tab
    game.input("tab")
    frames()
    shot("06_character_information")
    words("character information")
    game.input("tab up")

    # -- pause
    game.input("escape")
    frames()
    check("pause opens", game.paused)
    shot("07_pause")
    words("pause")
    pause = game.hud.pause_menu
    labels = [button.text for button in pause.main_buttons]
    check("pause has save, load and main menu", all(label in labels for label in ("SAVE GAME", "LOAD GAME", "MAIN MENU")), labels)
    pause.show_graphics()
    frames()
    shot("08_graphics")
    words("graphics")
    pause.show_main()

    # -- save and load, in the running game
    player = game.sentry
    pause._save_game()
    check("save says so", pause.message.text == "Game saved", pause.message.text)
    saved_at = (float(player.x), float(player.z))
    saved_file = json.loads(Path(os.environ["SENTRY_ROSTER_FILE"]).read_text(encoding="utf-8"))
    check("save wrote the file", saved_file["player"] == game.teams.state.player and game.teams.state.player in saved_file["session"])
    check("save kept every character", all(character in saved_file["assignment"] for character in ROSTER_IDS))
    player.position = (float(player.x) + 40.0, float(player.y), float(player.z) + 40.0)
    pause._load_game()
    frames()
    check("load says so", pause.message.text == "Game loaded", pause.message.text)
    check("load restores where they were", abs(float(game.sentry.x) - saved_at[0]) < 1.0 and abs(float(game.sentry.z) - saved_at[1]) < 1.0,
          f"{float(game.sentry.x):.1f},{float(game.sentry.z):.1f} wanted {saved_at}")
    shot("09_after_load")

    pause.main_buttons[-1].on_click()
    frames()
    check("MAIN MENU goes back to the title", game.at_title and menu.enabled and not game.paused)
    check("and it now says CONTINUE", menu.play_button.text == "CONTINUE", menu.play_button.text)
    shot("10_main_menu_continue")
    menu.play_button.on_click()
    frames()

    # -- every character, through the selection screen itself
    panel = game.team_panel
    game.toggle_team_panel()
    for character_id in ROSTER_IDS:
        game.teams.state.assignment[character_id] = "my_team"
        panel.swap(character_id)
        frames(2)
        check(f"selection takes control of {character_id}", game.sentry.kit.character_id == character_id and game.sentry.controlled, panel.status.text)
        words(f"selection with {character_id}")
    shot("11_selection_after_switches")
    game.toggle_team_panel()

    failed = [item for item in results if not item["passed"]]
    (out / "ui_results.json").write_text(json.dumps({"passed": len(results) - len(failed), "failed": len(failed), "checks": results, "text_seen": sorted(seen)}, indent=1), encoding="utf-8")
    print(json.dumps({"passed": len(results) - len(failed), "failed": len(failed)}), flush=True)
    os._exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
