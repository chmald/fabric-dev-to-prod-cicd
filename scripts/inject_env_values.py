#!/usr/bin/env python3
"""
inject_env_values.py — push per-environment values from ADO into a Fabric workspace
after `updateFromGit` has synced the branch.

Pattern
-------
Direct Lake on OneLake semantic models can't use Deployment Pipeline rules to
swap workspace/lakehouse IDs (the rules UI is greyed out for this model type).
The M-parameter approach defines WorkspaceId + LakehouseId in expressions.tmdl
and embeds them in the AzureStorage.DataLake() source URL, but the parameter
values need to be rewritten per environment after every sync.

This script is the automation. After the ADO pipeline calls Fabric REST
`updateFromGit` to pull a branch into a workspace, this step calls Fabric REST
`getDefinition` + `updateDefinition` to overwrite:

    1. Contoso_Vars.VariableLibrary       — valueSets/<set>.json overrides
    2. Contoso-Sales-Model.SemanticModel  — expressions.tmdl M parameter values

with values supplied by the matching ADO variable group (`contoso-fabric-env-dev`
or `contoso-fabric-env-prod`). Per-workspace identity values live in ADO (and can
be Key Vault-backed); git holds the structural scaffolding only.

Inputs (environment variables)
------------------------------
    FABRIC_TOKEN              Bearer token for Fabric REST API. The pipeline
                              acquires this via `az account get-access-token
                              --resource https://api.fabric.microsoft.com` and
                              passes it explicitly (not DefaultAzureCredential,
                              per rubber-duck guidance about cross-task auth).
    FABRIC_WORKSPACE_ID       Target workspace GUID.
    INJECT_VALUE_SET          Variable Library value-set NAME to update ("Dev"|"Prod").
    INJECT_ENV_LABEL          environmentLabel value (e.g. "Dev"|"Prod").
    INJECT_WORKSPACE_ID       workspaceId override (also written to SemanticModel M param).
    INJECT_LAKEHOUSE_ID       lakehouseId override (also written to SemanticModel M param).
    INJECT_WAREHOUSE_ID       warehouseId override.
    INJECT_WAREHOUSE_SQL      warehouseSqlEndpoint override.

    Optional:
    VARIABLE_LIBRARY_NAME     displayName to find (default "Contoso_Vars").
    SEMANTIC_MODEL_NAME       displayName to find (default "Contoso-Sales-Model").
    DRY_RUN                   "1" to skip every write (preview decoded changes).

Exit codes
----------
    0  success (or no-op if nothing to change)
    1  validation failure (missing env / wrong item count / unexpected payload)
    2  Fabric API failure (auth / transient / LRO did not succeed)

Local dry run
-------------
    $env:FABRIC_TOKEN = "<token>"
    $env:FABRIC_WORKSPACE_ID = "<wsId>"
    $env:INJECT_VALUE_SET = "Dev"
    $env:INJECT_ENV_LABEL = "Dev"
    $env:INJECT_WORKSPACE_ID = "<wsId>"
    $env:INJECT_LAKEHOUSE_ID = "<lhId>"
    $env:INJECT_WAREHOUSE_ID = "<whId>"
    $env:INJECT_WAREHOUSE_SQL = "<endpoint>"
    $env:DRY_RUN = "1"
    python scripts/inject_env_values.py
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import time
from typing import Any

import requests

FABRIC_API = "https://api.fabric.microsoft.com/v1"

REQUIRED_ENV = [
    "FABRIC_TOKEN",
    "FABRIC_WORKSPACE_ID",
    "INJECT_VALUE_SET",
    "INJECT_ENV_LABEL",
    "INJECT_WORKSPACE_ID",
    "INJECT_LAKEHOUSE_ID",
    "INJECT_WAREHOUSE_ID",
    "INJECT_WAREHOUSE_SQL",
]


def _redact(s: str | None) -> str:
    if not s or len(s) < 12:
        return "<empty>"
    return f"{s[:6]}…{s[-4:]}"


# ---------------------------------------------------------------------------
# REST helpers
# ---------------------------------------------------------------------------

def _auth_headers(token: str, content_type: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


def _poll_lro(location: str, retry_after: int, token: str, timeout_s: int = 300) -> dict[str, Any]:
    """Poll a Fabric long-running operation. Returns the final result JSON."""
    end = time.time() + timeout_s
    delay = max(retry_after, 2)
    while time.time() < end:
        time.sleep(delay)
        r = requests.get(location, headers=_auth_headers(token), timeout=30)
        # The LRO endpoint returns 202 while running, 200 when terminal.
        if r.status_code == 202:
            retry = r.headers.get("Retry-After")
            delay = max(int(retry) if retry and retry.isdigit() else delay, 2)
            logging.info("  LRO running, retry in %ss", delay)
            continue
        r.raise_for_status()
        # 200 with the operation status payload.
        body = r.json() if r.text else {}
        status = body.get("status")
        if status in ("Succeeded", "Failed", "Cancelled"):
            if status != "Succeeded":
                logging.error("LRO terminal status: %s — body: %s", status, json.dumps(body))
                raise RuntimeError(f"Fabric LRO did not succeed: {status}")
            # The result body may be the operation summary; fetch the result endpoint.
            result_url = location + "/result"
            rr = requests.get(result_url, headers=_auth_headers(token), timeout=30)
            if rr.status_code == 200 and rr.text:
                return rr.json()
            return body
        # Some Fabric endpoints return the actual definition payload directly here.
        if "definition" in body:
            return body
        # Defensive fallback for endpoints that return 200 + status field only.
        logging.info("  LRO intermediate body without status; treating as terminal.")
        return body
    raise TimeoutError(f"Fabric LRO did not complete in {timeout_s}s")


def fabric_post(url: str, token: str, body: dict | None = None, expect_lro: bool = True) -> dict[str, Any]:
    """POST helper that transparently handles Fabric's LRO pattern.

    Returns the final result payload (the synchronous body if Fabric returns 200,
    or the LRO result if Fabric returns 202)."""
    logging.info("POST %s", url)
    r = requests.post(url, headers=_auth_headers(token, content_type=True),
                      json=body or {}, timeout=60)
    if r.status_code in (200, 201):
        return r.json() if r.text else {}
    if r.status_code == 202 and expect_lro:
        location = r.headers.get("Location") or r.headers.get("location")
        retry_after = int(r.headers.get("Retry-After", "5"))
        if not location:
            raise RuntimeError("Fabric returned 202 but no Location header for LRO polling.")
        logging.info("  → LRO at %s (retry %ss)", location, retry_after)
        return _poll_lro(location, retry_after, token)
    r.raise_for_status()
    return {}


def fabric_get(url: str, token: str) -> dict[str, Any]:
    logging.info("GET %s", url)
    r = requests.get(url, headers=_auth_headers(token), timeout=60)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Item lookup
# ---------------------------------------------------------------------------

def find_item_id(workspace_id: str, item_type: str, display_name: str, token: str) -> str:
    """Return the GUID of the workspace item with the given type + displayName.
    Fails if not exactly one match (rubber-duck #10)."""
    url = f"{FABRIC_API}/workspaces/{workspace_id}/items?type={item_type}"
    data = fabric_get(url, token)
    matches = [it for it in data.get("value", []) if it.get("displayName") == display_name]
    if len(matches) == 0:
        raise RuntimeError(f"No {item_type} item named '{display_name}' in workspace {_redact(workspace_id)}")
    if len(matches) > 1:
        raise RuntimeError(
            f"Ambiguous match: {len(matches)} {item_type} items named '{display_name}' in workspace "
            f"{_redact(workspace_id)} — rename duplicates before deploy."
        )
    item_id = matches[0]["id"]
    logging.info("  resolved %-15s '%s' → %s", item_type, display_name, _redact(item_id))
    return item_id


# ---------------------------------------------------------------------------
# Definition handling (multi-part base64)
# ---------------------------------------------------------------------------

def _find_part(parts: list[dict], path_match: str) -> dict | None:
    """Find a part by exact path or case-insensitive endswith.
    Variable Library docs show inconsistent valueSet vs valueSets paths,
    so match flexibly (rubber-duck #5)."""
    for p in parts:
        if p.get("path") == path_match:
            return p
    for p in parts:
        if (p.get("path") or "").lower().endswith(path_match.lower()):
            return p
    return None


def _decode_part(part: dict) -> str:
    if part.get("payloadType") != "InlineBase64":
        raise RuntimeError(f"Unexpected payloadType {part.get('payloadType')} on part {part.get('path')}")
    return base64.b64decode(part["payload"]).decode("utf-8")


def _encode_part(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# ---------------------------------------------------------------------------
# Variable Library update
# ---------------------------------------------------------------------------

def update_variable_library(
    workspace_id: str,
    item_id: str,
    value_set_name: str,
    overrides: dict[str, str],
    token: str,
    dry_run: bool = False,
) -> bool:
    """Update the named value set's variableOverrides with the supplied values.
    Returns True if a write was performed, False if nothing changed."""
    logging.info("VariableLibrary %s — updating value set '%s'", _redact(item_id), value_set_name)

    # Use generic item definition API (Variable Library doesn't expose a typed endpoint today).
    defn = fabric_post(
        f"{FABRIC_API}/workspaces/{workspace_id}/items/{item_id}/getDefinition",
        token=token,
        body=None,
    )
    parts = (defn.get("definition") or {}).get("parts") or []
    if not parts:
        raise RuntimeError("getDefinition returned no parts for VariableLibrary")

    target_path = f"valueSets/{value_set_name}.json"
    part = _find_part(parts, target_path)
    if not part:
        raise RuntimeError(
            f"VariableLibrary has no part '{target_path}' — available parts: "
            f"{[p.get('path') for p in parts]}"
        )
    original_text = _decode_part(part)
    doc = json.loads(original_text)

    if "variableOverrides" not in doc:
        raise RuntimeError(f"VariableLibrary part {target_path} missing 'variableOverrides' array")

    # Build override dict by name; preserve any pre-existing overrides we don't manage.
    by_name = {ov.get("name"): ov for ov in doc["variableOverrides"]}
    changed_keys: list[str] = []
    for k, v in overrides.items():
        existing = by_name.get(k)
        if existing is None:
            doc["variableOverrides"].append({"name": k, "value": v})
            changed_keys.append(k)
        elif existing.get("value") != v:
            existing["value"] = v
            changed_keys.append(k)

    if not changed_keys:
        logging.info("  ✓ no changes (idempotent skip)")
        return False

    new_text = json.dumps(doc, indent=2) + "\n"
    logging.info("  changes detected in keys: %s", changed_keys)

    if dry_run:
        logging.warning("  DRY_RUN — skipping updateDefinition")
        return False

    # Update only the changed part, keeping every other part intact (rubber-duck #5).
    part["payload"] = _encode_part(new_text)
    update_body = {"definition": {"parts": parts}}
    fabric_post(
        f"{FABRIC_API}/workspaces/{workspace_id}/items/{item_id}/updateDefinition",
        token=token,
        body=update_body,
    )
    logging.info("  ✓ updateDefinition committed")
    return True


# ---------------------------------------------------------------------------
# SemanticModel M parameter update
# ---------------------------------------------------------------------------

# Match `expression <name> = "..."` allowing tabs/spaces; require exactly ONE match
# per parameter (rubber-duck #8).
def _replace_m_param(tmdl: str, name: str, new_value: str) -> tuple[str, str | None]:
    """Replace the value of `expression {name} = "..."`. Returns (new_tmdl, old_value).
    Raises if not exactly one match found."""
    pattern = re.compile(rf'(?m)^(\s*expression\s+{re.escape(name)}\s*=\s*")([^"]*)(")')
    matches = list(pattern.finditer(tmdl))
    if len(matches) == 0:
        raise RuntimeError(f"No M parameter '{name}' found in expressions.tmdl")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple definitions of M parameter '{name}' found — refusing to guess")
    old_value = matches[0].group(2)
    if old_value == new_value:
        return tmdl, None  # No change needed.
    new_tmdl = pattern.sub(rf'\g<1>{new_value}\g<3>', tmdl, count=1)
    return new_tmdl, old_value


def update_semantic_model(
    workspace_id: str,
    item_id: str,
    params: dict[str, str],
    token: str,
    dry_run: bool = False,
) -> bool:
    """Update M parameter values in expressions.tmdl. Returns True if a write was performed."""
    logging.info("SemanticModel %s — updating M parameters %s",
                 _redact(item_id), list(params.keys()))

    # Prefer SemanticModel-specific endpoint (rubber-duck #4).
    defn = fabric_post(
        f"{FABRIC_API}/workspaces/{workspace_id}/semanticModels/{item_id}/getDefinition?format=TMDL",
        token=token,
        body=None,
    )
    parts = (defn.get("definition") or {}).get("parts") or []
    if not parts:
        raise RuntimeError("getDefinition returned no parts for SemanticModel")

    expr_part = _find_part(parts, "definition/expressions.tmdl")
    if not expr_part:
        raise RuntimeError(
            f"SemanticModel has no part 'definition/expressions.tmdl' — available: "
            f"{[p.get('path') for p in parts]}"
        )
    original_text = _decode_part(expr_part)
    new_text = original_text
    rewrites: list[tuple[str, str | None, str]] = []
    for name, new_value in params.items():
        new_text, old_value = _replace_m_param(new_text, name, new_value)
        rewrites.append((name, old_value, new_value))

    if new_text == original_text:
        logging.info("  ✓ no changes (idempotent skip)")
        for name, old, new in rewrites:
            logging.info("    %-15s %s == %s", name, _redact(old), _redact(new))
        return False

    for name, old, new in rewrites:
        if old is not None:
            logging.info("    %-15s %s → %s", name, _redact(old), _redact(new))

    if dry_run:
        logging.warning("  DRY_RUN — skipping updateDefinition")
        return False

    expr_part["payload"] = _encode_part(new_text)
    update_body = {"definition": {"parts": parts}}
    fabric_post(
        f"{FABRIC_API}/workspaces/{workspace_id}/semanticModels/{item_id}/updateDefinition",
        token=token,
        body=update_body,
    )
    logging.info("  ✓ updateDefinition committed")
    return True


# ---------------------------------------------------------------------------
# Post-update verification
# ---------------------------------------------------------------------------

def verify_semantic_model_params(
    workspace_id: str,
    item_id: str,
    expected: dict[str, str],
    token: str,
) -> None:
    """Re-fetch the SemanticModel and confirm the M parameter values match
    (rubber-duck #7 + #8)."""
    logging.info("Verifying SemanticModel M parameters post-update")
    defn = fabric_post(
        f"{FABRIC_API}/workspaces/{workspace_id}/semanticModels/{item_id}/getDefinition?format=TMDL",
        token=token,
        body=None,
    )
    parts = (defn.get("definition") or {}).get("parts") or []
    expr_part = _find_part(parts, "definition/expressions.tmdl")
    if not expr_part:
        raise RuntimeError("Verification: SemanticModel has no expressions.tmdl part")
    text = _decode_part(expr_part)
    failures: list[str] = []
    for name, expected_value in expected.items():
        m = re.search(rf'(?m)^\s*expression\s+{re.escape(name)}\s*=\s*"([^"]*)"', text)
        if not m:
            failures.append(f"{name}: no match in verified definition")
        elif m.group(1) != expected_value:
            failures.append(f"{name}: expected {_redact(expected_value)}, found {_redact(m.group(1))}")
    if failures:
        raise RuntimeError("Post-update verification failed:\n  " + "\n  ".join(failures))
    logging.info("  ✓ verification passed for all M parameters")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        logging.error("Missing required env vars: %s", ", ".join(missing))
        return 1

    token = os.environ["FABRIC_TOKEN"]
    workspace_id = os.environ["FABRIC_WORKSPACE_ID"]
    value_set = os.environ["INJECT_VALUE_SET"]
    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    var_lib_name = os.environ.get("VARIABLE_LIBRARY_NAME", "Contoso_Vars")
    semantic_model_name = os.environ.get("SEMANTIC_MODEL_NAME", "Contoso-Sales-Model")

    overrides = {
        "environmentLabel":     os.environ["INJECT_ENV_LABEL"],
        "workspaceId":          os.environ["INJECT_WORKSPACE_ID"],
        "lakehouseId":          os.environ["INJECT_LAKEHOUSE_ID"],
        "warehouseId":          os.environ["INJECT_WAREHOUSE_ID"],
        "warehouseSqlEndpoint": os.environ["INJECT_WAREHOUSE_SQL"],
    }
    sm_params = {
        "WorkspaceId": os.environ["INJECT_WORKSPACE_ID"],
        "LakehouseId": os.environ["INJECT_LAKEHOUSE_ID"],
        "WarehouseId": os.environ["INJECT_WAREHOUSE_ID"],
    }

    logging.info("Workspace               : %s", _redact(workspace_id))
    logging.info("Variable Library name   : %s", var_lib_name)
    logging.info("Semantic Model name     : %s", semantic_model_name)
    logging.info("Target value set        : %s", value_set)
    logging.info("Dry run                 : %s", dry_run)

    try:
        var_lib_id = find_item_id(workspace_id, "VariableLibrary", var_lib_name, token)
        sm_id      = find_item_id(workspace_id, "SemanticModel",   semantic_model_name, token)

        update_variable_library(workspace_id, var_lib_id, value_set, overrides, token, dry_run)
        sm_changed = update_semantic_model(workspace_id, sm_id, sm_params, token, dry_run)

        # Verify SemanticModel only when we actually wrote (skip in dry-run mode).
        if sm_changed and not dry_run:
            verify_semantic_model_params(workspace_id, sm_id, sm_params, token)

    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else "(no body)"
        logging.error("Fabric API HTTPError %s: %s", getattr(e.response, "status_code", "?"), body)
        return 2
    except RuntimeError as e:
        logging.error("Injection failed: %s", e)
        return 1
    except Exception as e:  # noqa: BLE001 — top-level safety net
        logging.exception("Unexpected error: %s", e)
        return 2

    logging.info("✓ env injection complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
