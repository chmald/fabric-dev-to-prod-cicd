"""
deploy_fabric_cicd.py — Path 3 (Microsoft Learn CI/CD Option 2): code-first Fabric
promotion with the `fabric-cicd` Python library, or with the Fabric REST API directly.

Optional alternative to the shipped branch-per-workspace pipeline (Path 2). Aligns
with the Microsoft tutorial
  https://learn.microsoft.com/en-us/fabric/cicd/tutorial-fabric-cicd-azure-devops

Two modes:

    --mode library  (default) fabric-cicd: FabricWorkspace + publish_all_items +
                    unpublish_all_orphan_items. Environment-specific values come from
                    fabric/parameter.yml (fabric-cicd reads it from the root of
                    repository_directory), selected by --target_env.
    --mode rest     Plain Fabric REST: list items, then git/updateFromGit + LRO poll on
                    a Git-connected workspace. A teaching example of the same calls the
                    Path 2 pipeline makes.

Workspaces are resolved by display name (tutorial §6.2), so no GUID is configured:

    FABRIC_WORKSPACE_PREFIX   default "Contoso-Sales" -> Contoso-Sales-Dev | -Test | -Prod
    --workspace_name          overrides the derived name for one run

Authentication (tutorial §6.5): AZURE_TENANT_ID + AZURE_CLIENT_ID + AZURE_CLIENT_SECRET
when all three are set (ADO variable group linked to Key Vault), otherwise
DefaultAzureCredential (az login, workload identity, managed identity).

    python scripts/deploy_fabric_cicd.py --target_env test --items_in_scope '["Lakehouse","SemanticModel"]'
    python scripts/deploy_fabric_cicd.py --target_env prod --mode rest --dry-run

Status: static-only in this repo (not executed against a live tenant). Pin
fabric-cicd in scripts/requirements-fabric-cicd.txt and re-test on every upgrade.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ITEMS_DIR = REPO_ROOT / "fabric"
PARAMETER_FILE = ITEMS_DIR / "parameter.yml"  # fabric-cicd looks here (root of repository_directory)

FABRIC_API = "https://api.fabric.microsoft.com/v1"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"

ENVIRONMENTS = ("dev", "test", "prod")

# Item types this repo ships. fabric-cicd supports more; extend with --items_in_scope.
DEFAULT_ITEMS_IN_SCOPE = ["VariableLibrary", "Lakehouse", "Warehouse", "SemanticModel"]


def workspace_name_for(target_env: str, override: str | None = None) -> str:
    if override:
        return override
    prefix = os.environ.get("FABRIC_WORKSPACE_PREFIX", "Contoso-Sales")
    return f"{prefix}-{target_env.capitalize()}"


def resolve_items_in_scope(items_in_scope: str | None, items: str | None = None) -> list[str]:
    if items_in_scope:
        try:
            parsed = json.loads(items_in_scope)
        except json.JSONDecodeError as e:
            raise SystemExit(f"--items_in_scope is not valid JSON: {e}")
        if not isinstance(parsed, list) or not all(isinstance(i, str) for i in parsed):
            raise SystemExit("--items_in_scope must be a JSON array of item type names.")
        return parsed
    if items:
        return [t.strip() for t in items.split(",") if t.strip()]
    return list(DEFAULT_ITEMS_IN_SCOPE)


def get_credential():
    from azure.identity import ClientSecretCredential, DefaultAzureCredential

    tid, cid, sec = (os.environ.get(k) for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"))
    if tid and cid and sec:
        logging.info("Authenticating with a client secret for AZURE_CLIENT_ID=%s", cid)
        return ClientSecretCredential(tid, cid, sec)
    logging.info("Authenticating with DefaultAzureCredential")
    return DefaultAzureCredential()


def find_workspace_id_by_name(workspace_name: str, token: str) -> str:
    import requests

    headers = {"Authorization": f"Bearer {token}"}
    url = f"{FABRIC_API}/workspaces"
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        body = r.json()
        for ws in body.get("value", []):
            if ws.get("displayName") == workspace_name:
                return ws["id"]
        url = body.get("continuationUri")
    raise ValueError(f"Workspace '{workspace_name}' not visible to this identity. Check the workspace role "
                     "and the 'Service principals can call Fabric public APIs' tenant setting.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Code-first Fabric deploy (Path 3 / Learn Option 2).")
    p.add_argument("--target_env", choices=ENVIRONMENTS, required=True,
                   help="Target environment; selects the parameter.yml block and the default workspace name.")
    p.add_argument("--workspace_name", help="Workspace display name (overrides FABRIC_WORKSPACE_PREFIX-<Env>).")
    p.add_argument("--items_in_scope", help='JSON array of item types, e.g. \'["Lakehouse","SemanticModel"]\'.')
    p.add_argument("--items", help="Comma-separated alternative to --items_in_scope.")
    p.add_argument("--mode", choices=["library", "rest"], default="library")
    p.add_argument("--dry-run", action="store_true", help="Authenticate and resolve, but don't publish or sync.")
    return p.parse_args(argv)


def deploy_with_library(args: argparse.Namespace) -> int:
    try:
        from fabric_cicd import FabricWorkspace, publish_all_items, unpublish_all_orphan_items
    except ImportError:
        logging.error("fabric-cicd is not installed: pip install -r scripts/requirements-fabric-cicd.txt")
        return 2
    credential = get_credential()
    name = workspace_name_for(args.target_env, args.workspace_name)
    workspace_id = find_workspace_id_by_name(name, credential.get_token(FABRIC_SCOPE).token)
    items_in_scope = resolve_items_in_scope(args.items_in_scope, args.items)
    logging.info("env=%s workspace='%s' items=%s parameter.yml=%s", args.target_env, name, items_in_scope,
                 "present" if PARAMETER_FILE.exists() else "absent")
    workspace = FabricWorkspace(
        workspace_id=workspace_id,
        repository_directory=str(ITEMS_DIR),
        item_type_in_scope=items_in_scope,
        environment=args.target_env,
        token_credential=credential,
    )
    if args.dry_run:
        logging.warning("DRY RUN: nothing published.")
        return 0
    publish_all_items(workspace)
    unpublish_all_orphan_items(workspace)
    logging.info("Published to '%s'.", name)
    return 0


def deploy_with_rest(args: argparse.Namespace) -> int:
    import requests

    token = get_credential().get_token(FABRIC_SCOPE).token
    name = workspace_name_for(args.target_env, args.workspace_name)
    workspace_id = find_workspace_id_by_name(name, token)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    items = requests.get(f"{FABRIC_API}/workspaces/{workspace_id}/items", headers=headers, timeout=30)
    items.raise_for_status()
    for it in items.json().get("value", []):
        logging.info("  %-16s %s", it["type"], it["displayName"])
    if args.dry_run:
        logging.warning("DRY RUN: stopping before updateFromGit.")
        return 0
    status = requests.get(f"{FABRIC_API}/workspaces/{workspace_id}/git/status", headers=headers, timeout=60)
    status.raise_for_status()
    st = status.json()
    if st.get("workspaceHead") == st.get("remoteCommitHash") and not st.get("changes"):
        logging.info("Already in sync.")
        return 0
    body = {"remoteCommitHash": st["remoteCommitHash"], "workspaceHead": st.get("workspaceHead"),
            "conflictResolution": {"conflictResolutionType": "Workspace", "conflictResolutionPolicy": "PreferRemote"},
            "options": {"allowOverrideItems": True}}
    r = requests.post(f"{FABRIC_API}/workspaces/{workspace_id}/git/updateFromGit", headers=headers, json=body,
                      timeout=60)
    r.raise_for_status()
    op_id = r.headers.get("x-ms-operation-id")
    if not op_id:
        return 0
    deadline = time.time() + 300
    while time.time() < deadline:
        op = requests.get(f"{FABRIC_API}/operations/{op_id}", headers=headers, timeout=20).json()
        if op.get("status") not in ("NotStarted", "Running"):
            if op.get("status") != "Succeeded":
                logging.error("updateFromGit failed: %s", op)
                return 1
            logging.info("Workspace '%s' synchronized.", name)
            return 0
        time.sleep(8)
    logging.error("updateFromGit did not finish in 300 s (operation %s)", op_id)
    return 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    args = parse_args(argv)
    return deploy_with_library(args) if args.mode == "library" else deploy_with_rest(args)


if __name__ == "__main__":
    sys.exit(main())
