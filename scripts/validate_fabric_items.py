#!/usr/bin/env python3
"""
validate_fabric_items.py — pre-deploy validator for Fabric items.

Called by .azuredevops/pipelines/deploy-workspace-per-branch.yml in the
Validate stage. Catches the most common Git-integration breakages BEFORE
Fabric ever sees the commit:

    * .platform manifest missing or malformed
    * Variable Library variables/value-sets JSON malformed
    * SemanticModel TMDL definition missing required files
    * SemanticModel expressions.tmdl references parameters that don't exist
    * M syntax bug (duplicate closing quote on identifier)

The runtime per-workspace values (workspaceId, lakehouseId, warehouseId, etc.)
are injected post-sync by scripts/inject_env_values.py from ADO variable
groups, so cross-item consistency between expressions.tmdl committed values
and the Variable Library Dev/Prod value sets is NOT enforced here — committed
values are scaffolding; the pipeline owns the workspace's effective values.

Exits 0 on success, 1 on validation failure.

Runs standalone too:
    python scripts/validate_fabric_items.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FABRIC = REPO / "fabric"

# Branch → expected value-set name (used by the post-sync injection step)
BRANCH_VALUESET = {
    "dev":  "Dev",
    "prod": "Prod",
}


def _err(errors: list[str], path: Path, msg: str) -> None:
    errors.append(f"{path.relative_to(REPO)}: {msg}")


def validate_platform_manifests(errors: list[str]) -> int:
    count = 0
    for platform in FABRIC.rglob(".platform"):
        count += 1
        try:
            meta = json.loads(platform.read_text(encoding="utf-8"))
        except Exception as e:
            _err(errors, platform, f"invalid JSON — {e}")
            continue
        md = meta.get("metadata", {})
        if "type" not in md:
            _err(errors, platform, "missing metadata.type")
        if "displayName" not in md:
            _err(errors, platform, "missing metadata.displayName")
    return count


def validate_variable_library(errors: list[str]) -> None:
    var_dirs = [p.parent for p in FABRIC.rglob(".platform")
                if json.loads(p.read_text(encoding="utf-8")).get("metadata", {}).get("type") == "VariableLibrary"]
    for vd in var_dirs:
        defs = vd / "variables.json"
        if not defs.exists():
            _err(errors, vd, "VariableLibrary missing variables.json")
            continue
        try:
            doc = json.loads(defs.read_text(encoding="utf-8"))
        except Exception as e:
            _err(errors, defs, f"invalid JSON — {e}")
            continue
        if "variables" not in doc:
            _err(errors, defs, "variables.json missing 'variables' array")

        vs_dir = vd / "valueSets"
        if vs_dir.exists():
            for vsfile in vs_dir.glob("*.json"):
                try:
                    vs = json.loads(vsfile.read_text(encoding="utf-8"))
                except Exception as e:
                    _err(errors, vsfile, f"invalid JSON — {e}")
                    continue
                if "variableOverrides" not in vs:
                    _err(errors, vsfile, "value set missing 'variableOverrides' array")


def validate_semantic_models(errors: list[str]) -> list[Path]:
    """Return list of SemanticModel directories that validated structurally."""
    models = []
    for platform in FABRIC.rglob(".platform"):
        meta = json.loads(platform.read_text(encoding="utf-8"))
        if meta.get("metadata", {}).get("type") != "SemanticModel":
            continue
        model_dir = platform.parent
        models.append(model_dir)
        required = [
            "definition.pbism",
            "definition/database.tmdl",
            "definition/model.tmdl",
            "definition/expressions.tmdl",
        ]
        for rel in required:
            if not (model_dir / rel).exists():
                _err(errors, model_dir, f"missing required file {rel}")

        # Cross-check: every expressionSource referenced from tables/*.tmdl
        # should be defined in expressions.tmdl.
        expr_file = model_dir / "definition" / "expressions.tmdl"
        if expr_file.exists():
            exprs = re.findall(r"^expression\s+(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_]*))",
                               expr_file.read_text(encoding="utf-8"), re.MULTILINE)
            defined = {a or b for a, b in exprs}
            tables_dir = model_dir / "definition" / "tables"
            if tables_dir.exists():
                for tdl in tables_dir.glob("*.tmdl"):
                    for m in re.finditer(r"expressionSource:\s*'([^']+)'", tdl.read_text(encoding="utf-8")):
                        ref = m.group(1)
                        if ref not in defined:
                            _err(errors, tdl,
                                 f"references expressionSource '{ref}' not defined in expressions.tmdl")

            # Reject expressions.tmdl that has the historical syntax bug:
            # double-quote at end of M string concatenation.
            text = expr_file.read_text(encoding="utf-8")
            if re.search(r'#"[A-Za-z_][A-Za-z0-9_]*""', text):
                _err(errors, expr_file,
                     'M syntax error — `#"Identifier""` has duplicate closing quote.')

    return models


# M parameters scripts/inject_env_values.py rewrites; each must exist exactly once.
INJECTED_M_PARAMS = ("WorkspaceId", "LakehouseId", "WarehouseId")


def validate_m_param_definitions(errors: list[str]) -> None:
    """Confirm the M parameters the post-sync injection step overwrites exist in
    expressions.tmdl exactly once. Doesn't check the values themselves — those
    get rewritten by scripts/inject_env_values.py. The model folder comes from
    SEMANTIC_MODEL_NAME (same variable the injector reads)."""
    model_name = os.environ.get("SEMANTIC_MODEL_NAME", "Contoso-Sales-Model")
    expr_file = FABRIC / f"{model_name}.SemanticModel" / "definition" / "expressions.tmdl"
    if not expr_file.exists():
        _err(errors, expr_file, f"expected expressions.tmdl for SEMANTIC_MODEL_NAME='{model_name}'")
        return
    text = expr_file.read_text(encoding="utf-8")
    for name in INJECTED_M_PARAMS:
        pattern = re.compile(rf'(?m)^\s*expression\s+{name}\s*=\s*"[^"]*"')
        n = len(pattern.findall(text))
        if n == 0:
            _err(errors, expr_file, f"missing expected M parameter `expression {name} = \"…\"`")
        elif n > 1:
            _err(errors, expr_file, f"M parameter `{name}` defined {n} times — injection refuses to guess")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):  # Windows consoles default to cp1252 (no ✓ / ✗)
            stream.reconfigure(encoding="utf-8", errors="replace")
    if not FABRIC.exists():
        print(f"✗ fabric/ directory not found at {FABRIC}", file=sys.stderr)
        return 1

    errors: list[str] = []
    branch = os.environ.get("BUILD_SOURCEBRANCHNAME") or os.environ.get("GIT_BRANCH")

    item_count = validate_platform_manifests(errors)
    validate_variable_library(errors)
    models = validate_semantic_models(errors)
    validate_m_param_definitions(errors)

    print(f"  Items inspected         : {item_count}")
    print(f"  SemanticModels validated: {len(models)}")
    print(f"  Branch                  : {branch or '(unknown)'}")
    print()

    if errors:
        print("--- Validation failures ---")
        for e in errors:
            print(f"  ✗ {e}")
        print()
        print(f"FAILED: {len(errors)} issue(s)")
        return 1

    print(f"✓ Validated {item_count} Fabric items, no schema errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
