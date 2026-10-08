"""Configuration guard.

Fails when an environment variable read by scripts/*.py, a pipeline variable, or a
workload key in demo-ids.template.json is missing from docs/13-configuration-reference.md.

    python -m pytest tests/test_configuration.py    # or: python tests/test_configuration.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "13-configuration-reference.md").read_text(encoding="utf-8")
TOOLING = {"lint_doc_visuals.py", "make_badges.py"}
PREDEFINED = {"Build", "System", "Agent", "Pipeline"}


def documented(name: str) -> bool:
    return f"`{name}`" in DOC


def script_env_vars():
    found = set()
    for py in (ROOT / "scripts").glob("*.py"):
        if py.name in TOOLING:
            continue
        found |= set(re.findall(r'"([A-Z][A-Z0-9]*_[A-Z0-9_]+)"', py.read_text(encoding="utf-8")))
    return found


def pipeline_vars():
    found = set()
    for yml in (ROOT / ".azuredevops" / "pipelines").rglob("*.yml"):
        text = yml.read_text(encoding="utf-8")
        for v in re.findall(r"\$\(([A-Za-z_][A-Za-z0-9_.]*)\)", text):
            if v.split(".")[0] not in PREDEFINED:
                found.add(v)
        found |= set(re.findall(r"variables\['([A-Za-z_][A-Za-z0-9_]*)'\]", text))
        found |= set(re.findall(r"group: ([\w-]+)", text))
    return found


def test_script_env_vars_documented():
    missing = sorted(v for v in script_env_vars() if not documented(v))
    assert not missing, f"add to docs/13-configuration-reference.md: {missing}"


def test_pipeline_variables_documented():
    missing = sorted(v for v in pipeline_vars() if not documented(v))
    assert not missing, f"add to docs/13-configuration-reference.md: {missing}"


def test_workload_keys_documented():
    workload = json.loads((ROOT / "demo-ids.template.json").read_text(encoding="utf-8"))["workload"]
    keys = [k for k in workload if not k.startswith("_")] + list(workload["items"])
    missing = sorted(k for k in keys if not documented(k))
    assert not missing, f"add to docs/13-configuration-reference.md: {missing}"


def test_secrets_are_called_out():
    assert "Never configuration" in DOC


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
    print("ALL TESTS PASSED")
