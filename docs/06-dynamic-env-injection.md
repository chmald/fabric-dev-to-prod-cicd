# 06 — Dynamic per-workspace value injection via Azure DevOps + Fabric REST API

> **Purpose.** Automate per-workspace value injection for Direct Lake on
> OneLake semantic models. Deployment Pipeline rules are greyed out for this
> model type, so promoting from Dev to Prod would otherwise leave the model
> pointing at Dev data. This document covers the automated alternative using
> ADO variable groups + the Fabric REST API for Git integration (not Fabric
> Deployment Pipelines).

## The problem in one line

A Direct Lake on OneLake semantic model's data source URL embeds a workspace ID
and a lakehouse ID. Those IDs differ between Dev and Prod. Deployment Pipeline
**rules are greyed out** for Direct Lake on OneLake, so you can't swap them
that way.

## The fix in one line

After Fabric pulls the branch into the bound workspace, the ADO pipeline calls
Fabric REST `getDefinition` + `updateDefinition` on both the **Variable
Library** and the **SemanticModel** to overwrite the workspace's per-environment
values with the matching ADO variable group's values.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Git (single source of truth for STRUCTURE)                                │
│   fabric/Contoso-Sales-Model.SemanticModel/definition/expressions.tmdl        │
│      → defines M parameters (WorkspaceId, LakehouseId); values are        │
│        scaffolding only — the pipeline overwrites them per workspace.     │
│   fabric/Contoso_Vars.VariableLibrary/                                       │
│      → defines variables + valueSets/Dev.json + valueSets/Prod.json;      │
│        the variable NAMES + value-set SHAPES are authoritative.           │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ push to dev or prod
                                  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ ADO Pipeline (deploy-workspace-per-branch.yml)                            │
│                                                                            │
│  Stage 1 · Validate                                                        │
│      scripts/validate_fabric_items.py — schema + TMDL + manifest checks   │
│                                                                            │
│  Stage 2 · SyncFabricFromBranch                                            │
│      POST .../workspaces/{wsId}/git/updateFromGit → poll LRO              │
│      (workspace now reflects the branch's committed structure;            │
│       workspace's M param values are TEMPORARILY git-committed values)    │
│                                                                            │
│  Stage 3 · InjectEnvValues  ← THIS DOC                                    │
│      Loads ADO variable group contoso-fabric-env-<dev|prod>                  │
│      scripts/inject_env_values.py                                         │
│        ├─ find Contoso_Vars VariableLibrary by displayName                   │
│        ├─ find Contoso-Sales-Model SemanticModel by displayName              │
│        ├─ VarLib   : getDefinition → mutate valueSets/<set>.json          │
│        │              → updateDefinition (skip if no diff)                │
│        └─ SemModel : getDefinition (format=TMDL)                          │
│                      → rewrite expression {Workspace,Lakehouse}Id values  │
│                      → updateDefinition (skip if no diff)                 │
│                      → verify by re-fetching                              │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Fabric workspace (effective per-environment state)                        │
│   Variable Library value set holds environment values from ADO            │
│   Semantic Model M parameters resolve to environment-correct OneLake URL  │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## One-time setup (per ADO project)

The pipeline needs **five** things wired up in ADO + Fabric before the first
push will succeed end-to-end. Skip none of these — each one corresponds to a
specific failure mode in the table at the bottom of this doc.

### 1. Create two ADO variable groups in **Pipelines → Library**

#### `contoso-fabric-env-dev`

| Variable name              | Value (example)                                          | Notes |
|---|---|---|
| `WORKSPACE_ID`             | `11111111-1111-1111-1111-111111111111`                  | Dev workspace GUID |
| `LAKEHOUSE_ID`             | `33333333-3333-3333-3333-333333333333`                  | Dev lakehouse item GUID |
| `WAREHOUSE_ID`             | `55555555-5555-5555-5555-555555555555`                  | Dev warehouse item GUID |
| `WAREHOUSE_SQL_ENDPOINT`   | `<dev-warehouse-sql>.datawarehouse.fabric.microsoft.com` | TDS endpoint |
| `ENVIRONMENT_LABEL`        | `Dev`                                                   | Surfaces in reports / notebooks |
| `VALUE_SET`                | `Dev`                                                   | MUST match the Variable Library value-set NAME |

#### `contoso-fabric-env-prod`

Same variable names; Prod values.

> **For production hygiene**, Key Vault-back any of the above by toggling each
> variable to "Link secrets from an Azure key vault" in the variable group UI.
> The pipeline reads them the same way either way.

### 2. Authorise the variable groups for the pipeline

In ADO Library → each variable group → **Pipeline permissions** → grant the
`fabric-cicd-ado-integration` pipeline access. (Without this the pipeline run will
prompt for approval on first use; explicit grant avoids the surprise.)

### 3. Service connection check

`fabric-cicd-sp` (already configured) must be a **Workspace Admin** on
both `Contoso-Sales-Dev` and `Contoso-Sales-Prod`. The SP needs admin to call
`updateDefinition` on items.

This SP also needs a Fabric **Azure DevOps source-control Connection** and a
per-workspace `myGitCredentials` binding, otherwise Stage 2 (`updateFromGit`)
will never reach Stage 3. Full one-time setup is in
[07-service-principal-fabric-git-setup.md](07-service-principal-fabric-git-setup.md).
Symptoms when missed: `InsufficientPrivileges` on `git/status` (missing Admin /
tenant setting) or `GitCredentialsNotConfigured` (missing `myGitCredentials`).

### 4. Create the ADO Environments (`fabric-dev` + `fabric-prod`)

Each `deployment` job in the pipeline references an ADO Environment by name
(`fabric-$(Build.SourceBranchName)` resolves to `fabric-dev` for pushes to `dev`
and `fabric-prod` for pushes to `prod`). These environments must **exist before
the first push** — ADO can auto-create them on first run, but only if the build
identity has the Administrator role on Environments, which most service-
connection-driven pipelines don't.

If the environments don't exist, every run after Stage 1 fails with:

```
Job sync_workspace: Environment fabric-prod could not be found.
The environment does not exist or has not been authorized for use.
```

**Setup (one-time, 30 seconds per environment):**

In the ADO portal → `fabric-cicd-ado-integration` project → **Pipelines → Environments
→ New environment**:

1. **Name**: `fabric-dev` → **Resource**: None → **Create**
2. **Name**: `fabric-prod` → **Resource**: None → **Create**

For each environment, open it → **⋮ (more)** → **Security → Pipeline permissions
→ +** → grant access to the `fabric-cicd-ado-integration` pipeline. (Or pick "Open
access" from the same menu if any pipeline in the project should be allowed to
use the environment — simpler for a demo.)

**Optional — approval gates on `fabric-prod`:** open the environment → **Approvals
and checks → + → Approvals** → add yourself or a group as approver. Every push
to `prod` will then wait for explicit approval before Stage 2 (Sync) and Stage 3
(Inject) run. Useful for production cadence.

### 5. Activate the right value set in each Fabric workspace (one-time, manual)

There isn't a clean public REST endpoint to set a Variable Library's **active**
value set, so this is a one-time manual step:

- `Contoso-Sales-Dev` workspace → `Contoso_Vars` Variable Library → Settings →
  Active value set → `Dev`
- `Contoso-Sales-Prod` workspace → same → `Prod`

After this is set, every pipeline run keeps the value-set CONTENTS current. The
ACTIVATION sticks per workspace until someone manually changes it.

---

## What the pipeline does on each push

1. **Stage 1 — Validate** (local Python, no Fabric calls)
2. **Stage 2 — SyncFabricFromBranch** (`POST /git/updateFromGit`)
3. **Stage 3 — InjectEnvValues** (this doc)
   - Loads the matching variable group (`contoso-fabric-env-dev` for pushes to
     `dev`, `contoso-fabric-env-prod` for pushes to `prod`).
   - Acquires a Fabric token via the SP service connection.
   - Runs `scripts/inject_env_values.py`:
     a. `GET /workspaces/{wsId}/items?type=VariableLibrary` → expect exactly one
        item named `Contoso_Vars`; fail otherwise.
     b. `GET /workspaces/{wsId}/items?type=SemanticModel` → expect exactly one
        item named `Contoso-Sales-Model`; fail otherwise.
     c. For the Variable Library: `POST .../items/{id}/getDefinition` → decode
        the `valueSets/<Dev|Prod>.json` part → update each
        `variableOverrides[i].value` to the ADO variable group's value →
        compare to the original; if identical, **skip the update call**;
        otherwise `POST .../items/{id}/updateDefinition`.
     d. For the SemanticModel: `POST .../semanticModels/{id}/getDefinition?format=TMDL`
        → decode `definition/expressions.tmdl` → regex-replace `expression
        WorkspaceId = "..."` and `expression LakehouseId = "..."` values
        (each must match exactly once — script fails if zero or multiple
        matches) → compare to the original; skip if identical; otherwise
        `POST .../semanticModels/{id}/updateDefinition` → re-fetch and verify
        the values actually round-tripped.

---

## Local dry run

You can preview the injection without writing anything:

```pwsh
cd C:\path\to\fabric-cicd-ado-integration

# Acquire a Fabric token (must be a workspace member)
$env:FABRIC_TOKEN = (az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv)

# Point at a workspace
$env:FABRIC_WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"   # Dev
$env:INJECT_VALUE_SET    = "Dev"
$env:INJECT_ENV_LABEL    = "Dev"
$env:INJECT_WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
$env:INJECT_LAKEHOUSE_ID = "33333333-3333-3333-3333-333333333333"
$env:INJECT_WAREHOUSE_ID = "55555555-5555-5555-5555-555555555555"
$env:INJECT_WAREHOUSE_SQL = "<dev-warehouse-sql>.datawarehouse.fabric.microsoft.com"
$env:DRY_RUN = "1"

python scripts/inject_env_values.py
```

`DRY_RUN=1` runs every read but skips every write. Logs will tell you what
would change.

---

## Verification queries

### Did the pipeline actually update the SemanticModel?

```pwsh
$token = (az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv)
$wsId  = "<workspace-id>"
$smId  = "<semantic-model-id>"   # look up via GET /workspaces/{wsId}/items?type=SemanticModel

$resp = Invoke-RestMethod -Method POST `
    -Uri "https://api.fabric.microsoft.com/v1/workspaces/$wsId/semanticModels/$smId/getDefinition?format=TMDL" `
    -Headers @{ Authorization = "Bearer $token" }

$expr = $resp.definition.parts | Where-Object { $_.path -like '*expressions.tmdl' }
[System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($expr.payload))
```

The output should show your environment's `WorkspaceId` and `LakehouseId` values.

### Did the pipeline actually update the Variable Library value set?

```pwsh
$vlId = "<variable-library-id>"
$resp = Invoke-RestMethod -Method POST `
    -Uri "https://api.fabric.microsoft.com/v1/workspaces/$wsId/items/$vlId/getDefinition" `
    -Headers @{ Authorization = "Bearer $token" }

$ds = $resp.definition.parts | Where-Object { $_.path -like '*valueSets/Dev.json' }
[System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ds.payload))
```

---

## Why this design

| Decision | Why |
|---|---|
| **ADO variable groups own per-env values** (not git) | Centralised config; Key Vault-backable; same git on both branches is possible |
| **Pipeline injects via `updateDefinition` REST** | The blog's manual TMDL edit becomes automated; no Deployment Pipelines required; works for all item types that expose `getDefinition`/`updateDefinition` |
| **Idempotency via decoded-content comparison** | Fabric does NOT promise `updateDefinition` is a no-op on identical input — we compare before calling to avoid unnecessary writes and version churn |
| **SemanticModel-specific endpoint with `?format=TMDL`** | Cleaner contract than the generic item API; TMDL format is explicit so we know what's encoded |
| **Static variable group selection in YAML** | Runtime expressions in `- group:` may not resolve (variable groups need authorisation at compile time); template `${{ if }}` is safer |
| **Explicit Fabric token via env var** | `DefaultAzureCredential` can be flaky across `AzureCLI@2` task boundaries — pass the token explicitly inside the same task |
| **Post-update verification on SemanticModel** | Regex rewrites in TMDL are fragile; we re-fetch and confirm the new values are observable before declaring success |
| **Validator no longer cross-checks expressions.tmdl vs value sets** | The pipeline INJECTION now owns the effective values; in-git values are scaffolding, so a cross-check would falsely flag valid drift |
| **Active value-set selection is manual one-time** | No public REST endpoint today; documented loudly in setup |

---

## Failure modes & remediation

| Symptom | Cause | Fix |
|---|---|---|
| Stage 2 fails: `InsufficientPrivileges` on `GET /workspaces/{id}/git/status` (relatedResource.resourceType = `Workspace`) | SP not Workspace Admin, or "Service principals can use Fabric APIs" tenant setting not scoped to the SP | See [07-service-principal-fabric-git-setup.md](07-service-principal-fabric-git-setup.md) steps 2–3. |
| Stage 2 fails: `GitCredentialsNotConfigured` on `git/status` | SP has no `myGitCredentials` binding for the workspace | See [07-service-principal-fabric-git-setup.md](07-service-principal-fabric-git-setup.md) steps 5–6 — create a Fabric ADO source-control Connection, then PATCH `myGitCredentials` per workspace. |
| `Environment fabric-dev/fabric-prod could not be found. The environment does not exist or has not been authorized for use.` | ADO Environment hasn't been pre-created (and the build identity lacks Administrator role on Environments to auto-create it) | See setup §4 — create both environments in **Pipelines → Environments** and grant the pipeline access. |
| `No VariableLibrary item named 'Contoso_Vars'` | Workspace doesn't have the item yet | Push to `dev` once so `updateFromGit` materialises it, then re-run |
| `Ambiguous match: N SemanticModel items named 'Contoso-Sales-Model'` | Duplicate items in the workspace | Rename duplicates in the portal; only one canonical model should exist |
| `M parameter 'WorkspaceId' defined N times` | expressions.tmdl was hand-edited to add duplicate definitions | Restore expressions.tmdl to the single-definition shape |
| `Post-update verification failed` | Fabric accepted the write but stored a different value | Open the model in the portal, manually correct, then re-run — likely a transient API ordering issue |
| Stage 3 fails: `403 Forbidden` calling `updateDefinition` | SP isn't Workspace Admin | Add `fabric-cicd-sp` as **Admin** on the target workspace |
| Stage 3 fails: `401 Unauthorized` | Token expired between Sync (Stage 2) and Inject (Stage 3) | Already mitigated — token is re-acquired inside Stage 3's `AzureCLI@2` task |
| Pipeline doesn't load the variable group | Variable group not authorised for the pipeline | ADO Library → group → Pipeline permissions → grant `fabric-cicd-ado-integration` |
| Workspace shows old values even after green pipeline | Active value set on Variable Library isn't the one the pipeline updated | Fabric portal → Variable Library → Settings → set Active value set to `Dev` (in Dev workspace) or `Prod` (in Prod workspace) |

---

## Reference

- [Fabric REST API — Items (getDefinition / updateDefinition)](https://learn.microsoft.com/en-us/rest/api/fabric/core/items)
- [Fabric REST API — Semantic Models (getDefinition / updateDefinition)](https://learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items)
- [Variable Library overview (GA)](https://learn.microsoft.com/en-us/fabric/cicd/variable-library/variable-library-overview)
- [Fabric Git integration — updateFromGit](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/update-from-git)
- [ADO YAML — variable groups + template expressions](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/variables)
