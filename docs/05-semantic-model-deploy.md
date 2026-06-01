# 05 — Deploying / Changing the Contoso-Sales-Model SemanticModel

> **What this covers.** How to make changes to the Direct Lake on OneLake
> semantic model and roll them through `dev` → `prod` using the active pipeline.
> For the per-environment value-injection mechanism (ADO variable groups +
> Fabric REST `updateDefinition`), see `docs/06-dynamic-env-injection.md`.

## Where the per-environment values come from

| Concern | Source | Why |
|---|---|---|
| **Model structure** (tables, measures, relationships, M expression shape, parameter NAMES) | `fabric/Contoso-Sales-Model.SemanticModel/` in git | Versioned, PR-reviewable, replayable |
| **Per-environment IDs** (workspaceId, lakehouseId, warehouseId, SQL endpoint, env label) | ADO variable groups `contoso-fabric-env-dev` / `contoso-fabric-env-prod` | Centralised, Key Vault-backable, swap per env without touching git |
| **In-git M parameter VALUES + Variable Library value-set VALUES** | scaffolding only | Overwritten per workspace by the pipeline's Stage 3 |

The dev defaults committed in expressions.tmdl exist so that running
`updateFromGit` outside the pipeline still leaves the Dev workspace in a
working state. The pipeline's injection step is what guarantees prod (and any
future workspace) gets correct values.

## Standard change → promote flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. Developer makes changes in Fabric Dev workspace                      │
│    (e.g., adds a measure to Contoso-Sales-Model)                           │
├─────────────────────────────────────────────────────────────────────────┤
│ 2. Fabric commits to `dev` branch via Source Control pane               │
│    (or developer commits via VS Code + git push origin dev)             │
├─────────────────────────────────────────────────────────────────────────┤
│ 3. ADO pipeline triggers on `dev` push                                  │
│    Stage 1 — Validate                                                   │
│        * .platform manifests well-formed                                │
│        * Variable Library JSON parses                                   │
│        * SemanticModel TMDL files exist + referenced expressions exist  │
│        * WorkspaceId + LakehouseId M params present (exactly one each)  │
│        * No M syntax bugs                                               │
│    Stage 2 — SyncFabricFromBranch                                       │
│        * POST .../workspaces/<dev>/git/updateFromGit                    │
│        * Dev workspace reaches branch HEAD                              │
│    Stage 3 — InjectEnvValues                                            │
│        * Loads contoso-fabric-env-dev variable group                       │
│        * Overwrites VarLib Dev value set + SemModel M params via REST   │
│        * Skip per-item if no decoded-byte diff                          │
├─────────────────────────────────────────────────────────────────────────┤
│ 4. Promotion to Prod                                                    │
│    a) git checkout prod                                                 │
│    b) git merge dev (or cherry-pick the specific commit)                │
│    c) git commit + git push origin prod                                 │
│       (no per-branch parameter-value rewriting needed — Stage 3 owns it)│
├─────────────────────────────────────────────────────────────────────────┤
│ 5. ADO pipeline triggers on `prod` push                                 │
│    Same three stages run — loads contoso-fabric-env-prod this time         │
│        * Prod workspace gets the same model structure                   │
│        * Prod workspace M params + VarLib value set get prod values     │
├─────────────────────────────────────────────────────────────────────────┤
│ 6. Verify in Prod workspace: SemanticModel refreshes against Prod data  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Common operations

### Add a column to table1 in the SemanticModel

1. Edit `fabric/Contoso-Sales-Model.SemanticModel/definition/tables/table1.tmdl` — add the new `column` block.
2. If the column reads from a warehouse table, make sure the underlying Warehouse table has the column too (`fabric/Contoso-Sales-WH.Warehouse/dbo/Tables/table1.sql`).
3. Commit + push to `dev`. Pipeline syncs Dev workspace + injects Dev values.
4. Verify in Dev; promote to Prod per the standard flow above.

### Add a new variable to the Variable Library

1. Edit `fabric/Contoso_Vars.VariableLibrary/variables.json` — add a new entry to `variables` (defines name + type; the value here is a scaffold default).
2. Edit `fabric/Contoso_Vars.VariableLibrary/valueSets/Dev.json` and `Prod.json` — add the same name to `variableOverrides` (scaffold values are fine; the pipeline overwrites them if you also add the variable to the ADO variable groups).
3. Edit the matching ADO variable group(s) in `Pipelines → Library` to add the new variable with the real env-specific values.
4. Extend `scripts/inject_env_values.py` `overrides` dict to include the new variable so Stage 3 picks it up.
5. Commit, push to `dev`, promote to `prod`.

### Add a new table to the SemanticModel from the Warehouse

1. Create the table in `fabric/Contoso-Sales-WH.Warehouse/dbo/Tables/<name>.sql`.
2. Create `fabric/Contoso-Sales-Model.SemanticModel/definition/tables/<name>.tmdl` mirroring `table1.tmdl`. Set `expressionSource: 'DirectLake - Contoso-Sales-WH'`.
3. Add `ref table <name>` to `model.tmdl`.
4. Commit + push.

### Local dry-run of the pre-deploy validator

```pwsh
cd C:\path\to\fabric-cicd-ado-integration
$env:BUILD_SOURCEBRANCHNAME = "dev"
python scripts\validate_fabric_items.py
```

Exit code 0 = passes; 1 = fails (lists each issue).

### Local dry-run of the env injector (no writes)

```pwsh
# Acquire a Fabric token as a workspace member
$env:FABRIC_TOKEN = (az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv)

# Point at the target workspace
$env:FABRIC_WORKSPACE_ID  = "11111111-1111-1111-1111-111111111111"   # Dev workspace
$env:INJECT_VALUE_SET     = "Dev"
$env:INJECT_ENV_LABEL     = "Dev"
$env:INJECT_WORKSPACE_ID  = "11111111-1111-1111-1111-111111111111"
$env:INJECT_LAKEHOUSE_ID  = "33333333-3333-3333-3333-333333333333"
$env:INJECT_WAREHOUSE_ID  = "55555555-5555-5555-5555-555555555555"
$env:INJECT_WAREHOUSE_SQL = "<dev-warehouse-sql>.datawarehouse.fabric.microsoft.com"
$env:DRY_RUN = "1"

python scripts\inject_env_values.py
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Pipeline Stage 1 fails: "missing expected M parameter WorkspaceId" | expressions.tmdl was hand-edited and the parameter line was removed | Restore the `expression WorkspaceId = "..." meta [...]` line |
| Pipeline Stage 1 fails: "M parameter WorkspaceId defined 2 times" | duplicate parameter definitions in expressions.tmdl | Remove the duplicate; only one definition per name allowed |
| Pipeline Stage 2 fails: Fabric `updateFromGit` Conflict | Workspace has unsynced edits that differ from the branch | Resolve in Fabric portal (Source Control pane) → Accept remote |
| Pipeline Stage 3 fails: `403 Forbidden` | SP isn't Workspace Admin | Fabric portal → workspace → Manage access → add `fabric-cicd-sp` as **Admin** |
| Pipeline Stage 3 fails: "No SemanticModel item named 'Contoso-Sales-Model'" | Stage 2 didn't actually materialise the model in the workspace | Verify the workspace's git binding points at the expected branch; re-run Stage 2 |
| Pipeline Stage 3 fails: "Post-update verification failed" | Fabric `updateDefinition` returned success but the new values aren't observable | Re-run the pipeline; if it persists, manually correct in the portal and file an issue with Fabric support |
| SemanticModel in Prod workspace shows Dev data after a green pipeline | Variable Library's **active value set** in the Prod workspace is still `Dev` | Fabric portal → Contoso_Vars Variable Library → Settings → Active value set → `Prod`. This is a one-time per-workspace setting. |
| Variable Library values look stale even though Stage 3 was green | You added a new variable to the ADO variable group but didn't update the `overrides` dict in `scripts/inject_env_values.py` | Add the new key to the overrides dict + the required env var list |

---

## Reference links

- [Direct Lake on OneLake (in Web)](https://learn.microsoft.com/en-us/power-bi/enterprise/directlake-overview)
- [TMDL — Tabular Model Definition Language](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview)
- [Variable Library overview (GA)](https://learn.microsoft.com/en-us/fabric/cicd/variable-library/variable-library-overview)
- [Fabric Git integration — workspace ↔ branch binding](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-integration-process)
- [Fabric REST API — git/updateFromGit](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/update-from-git)
- [docs/06-dynamic-env-injection.md](06-dynamic-env-injection.md) — the env injection runbook
