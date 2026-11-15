"""Rebuild the optional compiled module. Only needed after changing native/sentry_native.rs; playing never needs it."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()


def main() -> int:
    toolchains = sorted((HOME / ".rustup" / "toolchains").glob("stable-x86_64-pc-windows-gnu*"))
    if not toolchains:
        print("Rust is not installed. The game still runs, on its Python maths.")
        return 1
    # Rust's own linker tools first, and no other compiler that happens to be on PATH.
    tools = toolchains[-1] / "lib" / "rustlib" / "x86_64-pc-windows-gnu" / "bin" / "self-contained"
    keep = [part for part in os.environ.get("PATH", "").split(os.pathsep) if "mingw" not in part.lower()]
    env = dict(os.environ, PATH=os.pathsep.join([str(tools), str(HOME / ".cargo" / "bin"), *keep]))
    source = ROOT / "native" / "sentry_native.rs"
    return subprocess.call(["rustc", "--edition", "2021", "--crate-type", "cdylib", "-C", "opt-level=3",
                            "-C", "lto=fat", "-C", "codegen-units=1", "-C", "panic=abort", "-C", "strip=symbols",
                            "-C", "link-self-contained=yes", "-o", str(source.with_suffix(".dll")), str(source)],
                           env=env)


if __name__ == "__main__":
    raise SystemExit(main())
