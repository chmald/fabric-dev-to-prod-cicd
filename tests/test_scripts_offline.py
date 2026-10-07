"""Offline tests for scripts/deploy_fabric_cicd.py (Path 3) and the Stage 1 validator.

No network, no fabric-cicd / azure-identity install needed.

    python -m pytest tests/test_scripts_offline.py   # or: python tests/test_scripts_offline.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import deploy_fabric_cicd as dfc  # noqa: E402


def _with_env(name, value, fn):
    old = os.environ.get(name)
    os.environ[name] = value
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


def test_workspace_name_derives_from_prefix():
    assert _with_env("FABRIC_WORKSPACE_PREFIX", "Fabrikam-Finance", lambda: dfc.workspace_name_for("test")) \
        == "Fabrikam-Finance-Test"
    assert dfc.workspace_name_for("prod", "Explicit-Name") == "Explicit-Name"


def test_items_in_scope_parsing():
    assert dfc.resolve_items_in_scope('["Lakehouse","SemanticModel"]') == ["Lakehouse", "SemanticModel"]
    assert dfc.resolve_items_in_scope(None, "Lakehouse, Warehouse") == ["Lakehouse", "Warehouse"]
    assert dfc.resolve_items_in_scope(None) == dfc.DEFAULT_ITEMS_IN_SCOPE
    for bad in ('{"a": 1}', "not json", "[1, 2]"):
        try:
            dfc.resolve_items_in_scope(bad)
        except SystemExit:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_target_env_is_required_and_bounded():
    assert dfc.parse_args(["--target_env", "test"]).mode == "library"
    for argv in ([], ["--target_env", "qa"]):
        try:
            dfc.parse_args(argv)
        except SystemExit:
            continue
        raise AssertionError(f"accepted {argv}")


def test_parameter_file_sits_where_fabric_cicd_reads_it():
    assert dfc.PARAMETER_FILE == dfc.ITEMS_DIR / "parameter.yml" and dfc.PARAMETER_FILE.exists()


def _run_validator(env_extra=None, fabric_dir=None):
    env = dict(os.environ, **(env_extra or {}))
    script = ROOT / "scripts" / "validate_fabric_items.py"
    cwd_root = fabric_dir.parent if fabric_dir else ROOT
    if fabric_dir:
        (cwd_root / "scripts").mkdir(exist_ok=True)
        shutil.copy(script, cwd_root / "scripts" / script.name)
        script = cwd_root / "scripts" / script.name
    return subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env,
                          encoding="utf-8", errors="replace")


def test_validator_passes_on_repo_items():
    r = _run_validator()
    assert r.returncode == 0, r.stdout + r.stderr


def test_validator_honours_semantic_model_name():
    r = _run_validator({"SEMANTIC_MODEL_NAME": "Not-A-Model"})
    assert r.returncode == 1 and "Not-A-Model" in r.stdout


def test_validator_requires_every_injected_m_param():
    tmp = ROOT / "tmp" / "validator-copy"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(ROOT / "fabric", tmp / "fabric")
    expr = tmp / "fabric" / "Contoso-Sales-Model.SemanticModel" / "definition" / "expressions.tmdl"
    expr.write_text("\n".join(ln for ln in expr.read_text(encoding="utf-8").splitlines()
                              if not ln.startswith("expression WarehouseId")), encoding="utf-8")
    try:
        r = _run_validator(fabric_dir=tmp / "fabric")
        assert r.returncode == 1 and "WarehouseId" in r.stdout, r.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
    print("ALL TESTS PASSED")
