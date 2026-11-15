"""Median of each scenario's runs from tools/agreed_benchmark.py, as a Markdown table, with the agreed pass mark.

    python tools/summarize_benchmark.py <folder of result JSON files>
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median
import sys

KEYS = ("average_fps", "frame_ms_p95", "frame_ms_p99", "one_percent_low_fps", "worst_frame_ms", "frames_over_100ms",
        "update_ms_mean", "step_ms_mean", "process_cpu_percent_of_one_thread", "working_set_peak_mb")
ORDER = ("idle", "boost_flight", "ai_fight", "beam", "nuclear", "squad")


def main() -> int:
    groups: dict = {}
    for path in Path(sys.argv[1]).glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        groups.setdefault((data["size"], data["scenario"]), []).append(data)
    print("| Size | Scenario | Runs | FPS | p95 ms | p99 ms | 1% low FPS | Worst ms | >100 ms frames | Update ms | Step ms | CPU % of 1 thread | Peak RAM MB | Pass |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for size in sorted({key[0] for key in groups}, key=lambda s: -int(s.split("x")[0])):
        for scenario in ORDER:
            runs = groups.get((size, scenario))
            if not runs:
                continue
            m = {key: median(run[key] for run in runs) for key in KEYS}
            passed = m["frame_ms_p95"] <= 33.3 and m["frame_ms_p99"] <= 50.0 and m["frames_over_100ms"] == 0
            print(f"| {size} | {scenario} | {len(runs)} | {m['average_fps']:.1f} | {m['frame_ms_p95']:.1f} | {m['frame_ms_p99']:.1f} | {m['one_percent_low_fps']:.1f} | "
                  f"{m['worst_frame_ms']:.0f} | {m['frames_over_100ms']:.0f} | {m['update_ms_mean']:.1f} | {m['step_ms_mean']:.1f} | "
                  f"{m['process_cpu_percent_of_one_thread']:.0f} | {m['working_set_peak_mb']:.0f} | {'yes' if passed else 'no'} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
