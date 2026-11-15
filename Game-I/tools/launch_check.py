"""Launch main.py exactly as a player does, from copies of the real saves, and watch it for a while. Real saves are not touched.

    python tools/launch_check.py [seconds]
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 45.0
    folder = Path(tempfile.mkdtemp(prefix="sentry_launch_"))
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", SENTRY_DESTRUCTION_SAVE=str(folder / "damage.json"))
    for name, variable in (("character_roster.json", "SENTRY_ROSTER_FILE"), ("character_powers.json", "SENTRY_POWER_FILE"), ("sentry_profiles.json", "SENTRY_PROFILE_FILE")):
        shutil.copy(ROOT / "config" / name, folder / name)
        environment[variable] = str(folder / name)
    log = open(folder / "output.txt", "w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "main.py"], cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
    begin = time.perf_counter()
    while time.perf_counter() - begin < seconds and process.poll() is None:
        time.sleep(1.0)
    alive = process.poll() is None
    code = process.poll()
    if alive:
        process.terminate()  # only the game this tool started
        process.wait(20)
    log.close()
    text = (folder / "output.txt").read_text(encoding="utf-8", errors="replace")
    problems = [line for line in text.splitlines() if "Traceback" in line or "startup failed" in line or "Error:" in line]
    print("ran", round(time.perf_counter() - begin, 1), "s; alive at the end:", alive, "; exit code:", code, "; problems:", len(problems))
    if not alive:
        print(text[-1500:])
    for line in problems[:10]:
        print("  ", line[:200])
    return 0 if alive and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
