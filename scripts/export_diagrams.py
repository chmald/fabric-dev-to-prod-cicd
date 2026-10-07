#!/usr/bin/env python3
"""Export .drawio diagrams to PNG with the draw.io desktop CLI.

Each `<name>.drawio` gets a sibling `<name>.png` (multi-page files get
`<name>-<page>.png` per page). Commit the PNG next to its .drawio source: the PNG
is what Markdown embeds and what renders everywhere (GitHub, Azure DevOps, VS
Code preview, email, slides); the .drawio stays the editable source of truth.

    python export_diagrams.py docs/assets             # export every .drawio in a folder
    python export_diagrams.py docs/assets/arch.drawio  # one file
    python export_diagrams.py docs/assets --check      # fail if any PNG is missing or stale

The draw.io desktop app is required (https://github.com/jgraph/drawio-desktop/releases,
or `winget install JGraph.Draw`). Set DRAWIO_EXE if it isn't found automatically.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CANDIDATES = [
    r"C:\Program Files\draw.io\draw.io.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\draw.io\draw.io.exe"),
    "/Applications/draw.io.app/Contents/MacOS/draw.io",
    "/opt/drawio/drawio",
    "/usr/bin/drawio",
    "/snap/bin/drawio",
]


def find_drawio() -> str:
    env = os.environ.get("DRAWIO_EXE")
    if env and Path(env).exists():
        return env
    for name in ("drawio", "draw.io"):
        found = shutil.which(name)
        if found:
            return found
    for c in CANDIDATES:
        if Path(c).exists():
            return c
    raise SystemExit("draw.io desktop not found. Install it (winget install JGraph.Draw, or "
                     "https://github.com/jgraph/drawio-desktop/releases) or set DRAWIO_EXE.")


def page_count(src: Path) -> int:
    return max(1, len(re.findall(r"<diagram\b", src.read_text(encoding="utf-8", errors="ignore"))))


def targets(src: Path) -> list[tuple[int | None, Path]]:
    n = page_count(src)
    if n == 1:
        return [(None, src.with_suffix(".png"))]
    return [(i, src.with_name(f"{src.stem}-{i + 1}.png")) for i in range(n)]


def export(exe: str, src: Path, scale: float, border: int) -> list[Path]:
    written = []
    for page, png in targets(src):
        cmd = [exe, "--export", "--format", "png", "--scale", str(scale), "--border", str(border),
               "--output", str(png)]
        if page is not None:
            cmd += ["--page-index", str(page + 1)]  # draw.io CLI page index is 1-based
        cmd.append(str(src))
        # --no-sandbox is needed when running as root on Linux CI; harmless elsewhere.
        if sys.platform.startswith("linux"):
            cmd.insert(1, "--no-sandbox")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not png.exists():
            raise SystemExit(f"export failed for {src.name}: {(r.stderr or r.stdout).strip()[:400]}")
        written.append(png)
    return written


def collect(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.drawio")) if p.is_dir() else [p]
    return files


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help=".drawio files or folders")
    ap.add_argument("--scale", type=float, default=2.0, help="2 = crisp on high-DPI screens and slides (default)")
    ap.add_argument("--border", type=int, default=20)
    ap.add_argument("--check", action="store_true", help="Do not export; exit 1 if any PNG is missing or older than its .drawio")
    args = ap.parse_args()

    files = collect(args.paths)
    if not files:
        raise SystemExit("no .drawio files found")
    if args.check:
        stale = [png for src in files for _, png in targets(src)
                 if not png.exists() or png.stat().st_mtime < src.stat().st_mtime]
        for s in stale:
            print(f"stale or missing: {s}")
        print(f"{len(files)} diagram(s) checked, {len(stale)} PNG(s) need export")
        sys.exit(1 if stale else 0)
    exe = find_drawio()
    for src in files:
        for png in export(exe, src, args.scale, args.border):
            print(f"  {src.name} -> {png.name} ({png.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
