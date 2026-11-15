"""Run every test module in its own process, a few at a time.

One long-lived process grows past 4 GB across this suite, because each headless game stays alive. This keeps each
module's memory to itself, and one crash or hang to itself. Writes a JSON summary and prints every failure.

    python tools/run_tests.py [--jobs 4] [--timeout 1500] [--out results.json] [pattern ...]
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent


def run_module(path: Path, timeout: float) -> dict:
    start = time.perf_counter()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", path.name], cwd=ROOT, env=environment,
                              capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        output = done.stdout + done.stderr
        code = done.returncode
    except subprocess.TimeoutExpired as error:
        text = error.stdout or b""
        output = text.decode("utf-8", "replace") if isinstance(text, bytes) else text
        code = "timeout"
    ran = re.search(r"Ran (\d+) tests?", output)
    bad = re.findall(r"^(?:FAIL|ERROR): (.+)$", output, flags=re.M)
    tail = output[-6000:] if code != 0 else ""
    return {"module": path.stem, "ran": int(ran.group(1)) if ran else 0, "code": code, "bad": bad, "seconds": round(time.perf_counter() - start, 1), "tail": tail}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=1500.0)
    parser.add_argument("--out", default="")
    parser.add_argument("patterns", nargs="*")
    args = parser.parse_args()
    paths = sorted((ROOT / "tests").glob("test_*.py"))
    if args.patterns:
        paths = [path for path in paths if any(pattern in path.stem for pattern in args.patterns)]
    with ThreadPoolExecutor(args.jobs) as pool:
        results = []
        for result in pool.map(lambda path: run_module(path, args.timeout), paths):
            results.append(result)
            print(f"{result['module']}: ran {result['ran']}, {'OK' if result['code'] == 0 else 'FAILED ' + str(result['code'])}, {len(result['bad'])} bad, {result['seconds']} s", flush=True)
    total = sum(result["ran"] for result in results)
    failed = [result for result in results if result["code"] != 0]
    print(f"TOTAL ran {total} tests in {len(results)} modules; {len(failed)} modules failed; {sum(len(r['bad']) for r in results)} failures or errors", flush=True)
    for result in failed:
        print(f"\n=== {result['module']} ===")
        for name in result["bad"]:
            print("  ", name)
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
