#!/usr/bin/env python3
"""Lint demo docs against the visual-richness documentation standard used in this repo.

Checks README.md and docs/*.md. Errors fail the run; warnings fail only with --strict.

Errors
  hero        a product-icon row (<img src=".../icons/...">) within 30 lines of the H1
  diagram     at least one exported diagram PNG embedded (assets/*.png), unless --no-diagram lists the file
  callouts    GitHub alerts (> [!NOTE] / [!TIP] / [!IMPORTANT] / [!WARNING] / [!CAUTION]): README >= 1, docs >= 2
  badges      README embeds at least one status badge (assets/badges/*.svg)
  svc-icons   tables whose first header cell is Service/Product/Component/Resource/Source/Tool have an <img> in >= 60% of rows
  links       every local link, image and <img src> resolves; every #anchor into a Markdown file matches a heading
  mermaid     no ```mermaid fences (runtime-generated output is exempt — it isn't linted)
  footer      last non-empty line is *Last updated: YYYY-MM-DD*
  size        file >= 3 KB (bare docs are the failure mode this lint exists for)
Warnings
  nav         breadcrumb link to README near the top and a "Next" link near the bottom (docs only)
  sections    H2 sections with no visual element (image, table, callout, <details>, code block)
  depth       file < 5 KB
  status      a table mentions GA/Preview in text but carries no badge image

    python lint_doc_visuals.py                      # from the demo root
    python lint_doc_visuals.py --root path/to/my-pattern --strict
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ALERT = re.compile(r"^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]", re.M)
IMG_TAG = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"', re.I)
MD_IMG = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)")
HTML_HREF = re.compile(r'<a\b[^>]*\bhref="([^"]+)"', re.I)
FOOTER = re.compile(r"^\*Last updated: \d{4}-\d{2}-\d{2}\*$", re.I)
SVC_HEADER = re.compile(r"^\|\s*(?:<[^>]+>\s*)?\**(service|product|component|resource|source|tool)s?\b", re.I)
STATUS_WORDS = re.compile(r"\b(GA|preview)\b", re.I)


def slugify(heading: str) -> str:
    h = re.sub(r"<[^>]+>", "", heading).strip().lower()
    h = re.sub(r"[`*~]", "", h)
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def anchors(md: Path) -> set[str]:
    seen: dict[str, int] = {}
    out: set[str] = set()
    in_code = False
    text = md.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        m = None if in_code else re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m:
            base = slugify(m.group(2))
            n = seen.get(base, 0)
            out.add(base if n == 0 else f"{base}-{n}")
            seen[base] = n + 1
    out |= set(re.findall(r'<a\s+(?:id|name)="([^"]+)"', text))
    return out


def strip_code(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def tables(text: str) -> list[list[str]]:
    blocks, cur = [], []
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            cur.append(line.strip())
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return [b for b in blocks if len(b) >= 3 and re.match(r"^\|\s*:?-{3}", b[1])]


def sections(raw: str) -> list[tuple[str, str]]:
    parts = re.split(r"^## +(.*)$", raw, flags=re.M)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def lint(md: Path, is_readme: bool, no_diagram: set[str]) -> tuple[list[str], list[str], dict]:
    raw = md.read_text(encoding="utf-8")
    text = strip_code(raw)
    lines = raw.splitlines()
    errs: list[str] = []
    warns: list[str] = []

    h1 = next((i for i, l in enumerate(lines) if l.startswith("# ")), 0)
    head = "\n".join(lines[h1:h1 + 30])
    all_imgs = MD_IMG.findall(text) + IMG_TAG.findall(text)
    icon_refs = [s for s in IMG_TAG.findall(text) if "/icons/" in s.replace("\\", "/")]
    pngs = [s for s in all_imgs if s.lower().endswith(".png")]
    badges = [s for s in all_imgs if "/badges/" in s.replace("\\", "/")]
    alerts = ALERT.findall(raw)
    tbls = tables(text)

    if not any("/icons/" in s.replace("\\", "/") for s in IMG_TAG.findall(head)):
        errs.append("hero: no product-icon row (<img src='.../icons/<key>.svg'>) within 30 lines of the H1")
    if not pngs and md.name not in no_diagram:
        errs.append("diagram: no exported diagram PNG embedded")
    need = 1 if is_readme else 2
    if len(alerts) < need:
        errs.append(f"callouts: {len(alerts)} GitHub alert(s), need >= {need}")
    if is_readme and not badges:
        errs.append("badges: README has no status badge (assets/badges/*.svg)")
    for t in tbls:
        if SVC_HEADER.match(t[0]):
            body = t[2:]
            with_icon = sum(1 for r in body if "<img" in r)
            if body and with_icon / len(body) < 0.6:
                errs.append(f"svc-icons: table '{t[0][:60]}' has icons in {with_icon}/{len(body)} rows")
        elif STATUS_WORDS.search("\n".join(t)) and not any("/badges/" in r for r in t):
            warns.append(f"status: table '{t[0][:50]}' mentions GA/preview without badges")
    if re.search(r"^```mermaid", raw, re.M):
        errs.append("mermaid: hand-authored Mermaid fence")
    last = next((l.strip() for l in reversed(lines) if l.strip()), "")
    if not FOOTER.match(last):
        errs.append("footer: last line is not *Last updated: YYYY-MM-DD*")
    kb = md.stat().st_size / 1024
    if kb < 3:
        errs.append(f"size: {kb:.1f} KB (< 3 KB)")
    elif kb < 5:
        warns.append(f"depth: {kb:.1f} KB (< 5 KB)")

    anchor_cache: dict[Path, set[str]] = {}
    for ref in all_imgs + MD_LINK.findall(text) + HTML_HREF.findall(text):
        if re.match(r"^(https?:|mailto:|data:)", ref):
            continue
        path_part, _, frag = ref.partition("#")
        target = (md.parent / path_part).resolve() if path_part else md
        if path_part and not target.exists():
            errs.append(f"links: missing target {ref}")
            continue
        if frag and target.suffix.lower() == ".md":
            if target not in anchor_cache:
                anchor_cache[target] = anchors(target)
            if frag.lower() not in anchor_cache[target]:
                errs.append(f"links: no heading for anchor {ref}")

    if not is_readme:
        if "README.md" not in "\n".join(lines[:12]):
            warns.append("nav: no breadcrumb link to README.md near the top")
        if not re.search(r"\bnext\b", "\n".join(lines[-15:]), re.I):
            warns.append("nav: no 'Next' link near the bottom")
    for title, body in sections(raw):
        if not (IMG_TAG.search(body) or MD_IMG.search(body) or ALERT.search(body) or "<details" in body
                or tables(body) or "```" in body):
            warns.append(f"sections: '## {title}' has no visual element")

    stats = {"kb": kb, "icons": len(icon_refs), "diagrams": len(pngs), "badges": len(badges),
             "callouts": len(alerts), "tables": len(tbls), "details": raw.count("<details")}
    return errs, warns, stats


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path.cwd(), help="demo root (default: cwd)")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument("--no-diagram", default="", help="comma-separated doc file names exempt from the diagram rule")
    ap.add_argument("--quiet", action="store_true", help="only print the summary table and errors")
    args = ap.parse_args()

    root = args.root.resolve()
    files = [f for f in [root / "README.md"] + sorted((root / "docs").glob("*.md")) if f.exists()]
    if not files:
        raise SystemExit(f"no README.md or docs/*.md under {root}")
    exempt = {s.strip() for s in args.no_diagram.split(",") if s.strip()}

    total_e = total_w = 0
    rows = []
    for f in files:
        errs, warns, st = lint(f, f.name == "README.md", exempt)
        if args.strict:
            errs, warns = errs + warns, []
        total_e += len(errs)
        total_w += len(warns)
        name = f.relative_to(root).as_posix()
        rows.append((name, st, len(errs), len(warns)))
        for e in errs:
            print(f"ERROR   {name}: {e}")
        if not args.quiet:
            for w in warns:
                print(f"warning {name}: {w}")

    print(f"\n{'file':<44}{'KB':>6}{'icons':>7}{'diag':>6}{'badge':>7}{'callout':>9}{'table':>7}{'det':>5}{'E':>4}{'W':>4}")
    for name, st, e, w in rows:
        print(f"{name:<44}{st['kb']:>6.1f}{st['icons']:>7}{st['diagrams']:>6}{st['badges']:>7}"
              f"{st['callouts']:>9}{st['tables']:>7}{st['details']:>5}{e:>4}{w:>4}")
    print(f"\n{len(rows)} file(s): {total_e} error(s), {total_w} warning(s)")
    sys.exit(1 if total_e else 0)


if __name__ == "__main__":
    main()
