"""Reusability guards (demo-pattern-authoring hard-rule #14).

The workload block in demo-ids.template.json is the only domain-specific surface;
these tests fail when code defaults, item folders, or Path 3 parameterization drift
from it, or when customer names / real IDs leak into tracked files.

    python -m pytest tests/test_reusability_guards.py   # or: python tests/test_reusability_guards.py
"""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKLOAD = json.loads((ROOT / "demo-ids.template.json").read_text(encoding="utf-8"))["workload"]
ITEMS = WORKLOAD["items"]
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
TEXT_SUFFIXES = {".md", ".py", ".yml", ".yaml", ".json", ".txt", ".tmdl", ".sql", ".csv", ".gitignore", ""}


def tracked_text_files():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split("\n")
    for rel in filter(None, out):
        p = ROOT / rel
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES and "assets" not in p.parts:
            yield rel, p.read_text(encoding="utf-8", errors="ignore")


def _platform_names():
    names = {}
    for plat in (ROOT / "fabric").rglob(".platform"):
        md = json.loads(plat.read_text(encoding="utf-8"))["metadata"]
        names[md["type"]] = md["displayName"]
    return names


def test_template_is_marked_and_scoped():
    tpl = json.loads((ROOT / "demo-ids.template.json").read_text(encoding="utf-8"))
    assert tpl["_template"] is True and "_note" in tpl and "_note" in tpl["workload"]


def test_fabric_items_match_workload_block():
    names = _platform_names()
    assert names["Lakehouse"] == ITEMS["lakehouse"]
    assert names["Warehouse"] == ITEMS["warehouse"]
    assert names["SemanticModel"] == ITEMS["semanticModel"]
    assert names["VariableLibrary"] == ITEMS["variableLibrary"]


def test_script_defaults_match_workload_block():
    inject = (ROOT / "scripts" / "inject_env_values.py").read_text(encoding="utf-8")
    validate = (ROOT / "scripts" / "validate_fabric_items.py").read_text(encoding="utf-8")
    deploy = (ROOT / "scripts" / "deploy_fabric_cicd.py").read_text(encoding="utf-8")
    assert f'"VARIABLE_LIBRARY_NAME", "{ITEMS["variableLibrary"]}"' in inject
    assert f'"SEMANTIC_MODEL_NAME", "{ITEMS["semanticModel"]}"' in inject
    assert f'"SEMANTIC_MODEL_NAME", "{ITEMS["semanticModel"]}"' in validate
    assert f'"FABRIC_WORKSPACE_PREFIX", "{WORKLOAD["workspacePrefix"]}"' in deploy


def test_pipeline_uses_workload_naming():
    yml = (ROOT / ".azuredevops" / "pipelines" / "deploy-workspace-per-branch.yml").read_text(encoding="utf-8")
    for env in WORKLOAD["environments"]:
        assert f"group: {WORKLOAD['variableGroupPrefix']}{env}" in yml
    assert f"'{WORKLOAD['adoEnvironmentPrefix']}$(Build.SourceBranchName)'" in yml
    assert f"value: '{WORKLOAD['serviceConnection']}'" in yml


def test_parameter_yml_references_real_items():
    text = (ROOT / "fabric" / "parameter.yml").read_text(encoding="utf-8")
    for ref in re.findall(r"\$items\.(\w+)\.([\w-]+)\.", text):
        assert _platform_names().get(ref[0]) == ref[1], ref
    for name in re.findall(r'item_name: "([^"]+)"', text):
        assert name in _platform_names().values(), name


def test_no_real_guids_outside_fabric_items():
    def placeholder(g):
        return all(len(set(part.lower())) == 1 for part in g.split("-"))

    leaks = [(rel, g) for rel, text in tracked_text_files() if not rel.startswith("fabric/")
             for g in GUID.findall(text) if not placeholder(g)]
    assert not leaks, leaks


def test_no_org_specific_urls():
    leaks = [(rel, m) for rel, text in tracked_text_files()
             for m in re.findall(r"dev\.azure\.com/([^/<\s)\"'`]+)", text) if m not in {"&lt;your-org&gt;"}]
    assert not leaks, leaks


def test_local_leak_patterns():
    """Patterns live in the gitignored .leak-patterns.txt so the names themselves are never committed."""
    pf = ROOT / ".leak-patterns.txt"
    if not pf.exists():
        return
    pats = [ln.strip() for ln in pf.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    leaks = [(rel, p) for rel, text in tracked_text_files() if rel != ".leak-patterns.txt"
             for p in pats if re.search(p, text, re.I)]
    assert not leaks, leaks


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
    print("ALL TESTS PASSED")
