#!/usr/bin/env python3
"""Generate local SVG status badges for demo docs (no shields.io / network calls).

Badges render offline and in GitHub, Azure DevOps repos, VS Code preview and email.
The standard set covers GA/preview status, default/opt-in modes, validation level and
the pattern version; add project-specific ones with --badge.

    python make_badges.py docs/assets/badges                       # standard set
    python make_badges.py docs/assets/badges --version 1.2.0
    python make_badges.py docs/assets/badges --badge "regions-aigw:regions:East US 2 | Sweden Central:#0078D4"

Use in Markdown:  ![GA](./assets/badges/ga.svg) ![Public preview](./assets/badges/public-preview.svg)
"""
from __future__ import annotations

import argparse
from pathlib import Path
from xml.sax.saxutils import escape

STANDARD = [
    ("ga", "status", "GA", "#107C10"),
    ("preview", "status", "Preview", "#CA5010"),
    ("public-preview", "status", "Public preview", "#CA5010"),
    ("release-gated", "status", "Release-gated", "#A4262C"),
    ("deprecated", "status", "Deprecated", "#A4262C"),
    ("default", "mode", "Default", "#0078D4"),
    ("opt-in", "mode", "Opt-in", "#5C2D91"),
    ("optional", "mode", "Optional", "#605E5C"),
    ("diy", "support", "DIY / not shipped", "#8A8886"),
    ("live-tested", "validation", "Live-tested", "#107C10"),
    ("static-only", "validation", "Static only", "#8A8886"),
    ("azd-up", "deploy", "azd up", "#0078D4"),
    ("manual-path", "deploy", "Manual path", "#605E5C"),
]


def text_width(s: str) -> int:
    # Segoe UI / Verdana 11px average advance; wide glyphs get a little more room.
    return int(sum(7.4 if c in "MWmw@%" else 4.0 if c in "il.,:;|!'" else 6.4 for c in s) + 12)


def badge_svg(label: str, value: str, color: str) -> str:
    lw, vw = text_width(label), text_width(value)
    w = lw + vw
    l, v = escape(label), escape(value)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{l}: {v}">'
            f'<title>{l}: {v}</title><rect rx="3" width="{w}" height="20" fill="#555"/>'
            f'<rect rx="3" x="{lw}" width="{vw}" height="20" fill="{color}"/>'
            f'<rect x="{lw}" width="4" height="20" fill="{color}"/>'
            f'<g fill="#fff" text-anchor="middle" font-family="Segoe UI,Verdana,sans-serif" font-size="11">'
            f'<text x="{lw // 2}" y="14">{l}</text><text x="{lw + vw // 2}" y="14">{v}</text></g></svg>\n')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path, help="output folder, e.g. docs/assets/badges")
    ap.add_argument("--version", help="also write version.svg (pattern | vX.Y.Z)")
    ap.add_argument("--badge", action="append", default=[], metavar="NAME:LABEL:VALUE:COLOR",
                    help="extra badge; VALUE may contain spaces and '|'")
    ap.add_argument("--no-standard", action="store_true", help="only write --badge / --version badges")
    args = ap.parse_args()

    specs = [] if args.no_standard else list(STANDARD)
    if args.version:
        specs.append(("version", "pattern", f"v{args.version.lstrip('v')}", "#0078D4"))
    for raw in args.badge:
        name, label, rest = raw.split(":", 2)
        value, _, color = rest.rpartition(":")
        if not value or not color.startswith("#"):
            raise SystemExit(f"--badge {raw!r}: expected NAME:LABEL:VALUE:#RRGGBB")
        specs.append((name, label, value, color))

    args.out.mkdir(parents=True, exist_ok=True)
    for name, label, value, color in specs:
        (args.out / f"{name}.svg").write_text(badge_svg(label, value, color), encoding="utf-8")
    print(f"wrote {len(specs)} badge(s) to {args.out}")


if __name__ == "__main__":
    main()
