"""Docs meet the visual-richness standard (demo-pattern-authoring hard-rule #19).

    python -m pytest tests/test_doc_visuals.py      # or: python tests/test_doc_visuals.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_docs_meet_visual_standard():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "lint_doc_visuals.py"), "--root", str(ROOT), "--strict",
                        "--quiet"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stdout[-4000:]


def test_every_diagram_has_a_fresh_png():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "export_diagrams.py"), str(ROOT / "docs" / "assets"),
                        "--check"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stdout[-2000:]


if __name__ == "__main__":
    test_docs_meet_visual_standard()
    test_every_diagram_has_a_fresh_png()
    print("ALL TESTS PASSED")
