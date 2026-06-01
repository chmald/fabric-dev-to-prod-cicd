# 00 — Step-by-step reproduction guide

> **Audience.** Someone who wants to clone this repo and stand up the full demo against a fresh Fabric tenant + Azure DevOps organisation. Each part below is a discrete checkpoint — finish A before starting B, etc. The deep-dive runbooks ([06-dynamic-env-injection.md](06-dynamic-env-injection.md), [07-service-principal-fabric-git-setup.md](07-service-principal-fabric-git-setup.md)) are linked from the specific steps that consume them rather than duplicated here.

> **Time budget.** First-time stand-up: roughly half a day end-to-end, dominated by waits on tenant-setting propagation and Fabric capacity provisioning. Subsequent reproductions in the same tenant: under an hour.

---

## What you'll end up with

```
   ┌────────────────────────────────────────────────────────────────┐
   │ Azure DevOps                                                   │
   │   ├─ Repo: this codebase, branches `dev` + `prod`              │
   │   ├─ Pipeline: deploy-workspace-per-branch.yml (Validate →     │
   │   │   Sync → Inject), triggered on push to either branch       │
   │   ├─ Variable groups: contoso-fabric-env-dev / -prod              │
   │   ├─ Environments: fabric-dev / fabric-prod                    │
   │   └─ Service connection: fabric-cicd-sp (SP-backed)    │
   └──────────────────────────────┬─────────────────────────────────┘
                                  │ POST /git/updateFromGit
                                  │ POST /items/{id}/updateDefinition
                                  ▼
   ┌────────────────────────────────────────────────────────────────┐
   │ Microsoft Fabric                                               │
   │   ├─ Capacity: F-SKU or Trial                                  │
   │   ├─ Workspace Contoso-Sales-Dev  ↔ git branch `dev`          │
   │   │     │ Lakehouse · Warehouse · SemanticModel · VarLib       │
   │   │     │ VarLib active value set = Dev                        │
   │   └─ Workspace Contoso-Sales-Prod ↔ git branch `prod`         │
   │         │ same items                                           │
   │         │ VarLib active value set = Prod                       │
   └────────────────────────────────────────────────────────────────┘
```

The pipeline owns the workspace's runtime values; git holds structure plus scaffolding only.

---

## Prerequisites checklist (verify before starting Part A)

- [ ] An **Entra ID tenant** where you can create app registrations.
- [ ] An **Azure subscription** in that tenant — used only to host the Fabric capacity and (optionally) Key Vault for secrets.
- [ ] **Fabric admin** rights (or a co-conspirator with them) — needed in Part C for tenant settings.
- [ ] An **Azure DevOps organisation** in the same Entra tenant. Newly created orgs have **zero** free hosted-agent parallelism — request it now ([aka.ms/azpipelines-parallelism-request](https://aka.ms/azpipelines-parallelism-request)) because approval takes 2–3 business days.
- [ ] **Local tools**: `git`, **Python 3.11+**, Azure CLI (`az`), VS Code (optional but recommended).

---

## Part A — Provision Microsoft Fabric

### A1. Get a Fabric capacity

You need a backing capacity for the workspaces. Either:

- **Trial capacity** — free 60-day trial inside any tenant with a Power BI Pro user. Fabric portal → top-right account menu → **Start trial**. Trial capacity SKU shows up as `FTL64`. Fast for a demo; not appropriate for prod.
- **F-SKU paid capacity** — Azure portal → *Create resource* → *Microsoft Fabric* → pick your subscription, region, SKU (F2 is enough for this demo). Note the **capacity ID** (the resource GUID).

### A2. Create the two Fabric workspaces

For each environment (Dev and Prod):

1. Fabric portal → **Workspaces → + New workspace**
2. **Name**: `Contoso-Sales-Dev` (then repeat with `Contoso-Sales-Prod`)
3. **License mode → Fabric capacity** → pick the capacity from A1.
4. Open the new workspace once and copy its **workspace ID** from the URL (`/groups/<guid>`). You'll need both IDs in Part E.

*Why two workspaces, not three?* This repo demonstrates the two-environment variant (`dev`/`prod`). To add a `qa` tier, create a third workspace, add a `qa` branch, add `contoso-fabric-env-qa` variable group, and extend the pipeline's branch list. The pattern is identical.

---

## Part B — Provision Azure DevOps

### B1. Create the ADO project (skip if you already have one)

1. https://dev.azure.com → your org → **New project** → name it `fabric-cicd-ado-integration` (or anything; just update [README.md](../README.md) accordingly).
2. **Version control**: Git. **Work item process**: anything.

### B2. Verify hosted-agent parallelism

Project Settings → *Parallel jobs*. If "Microsoft-hosted" shows `0`, the pipeline will never run. Submit the request linked in the prerequisites and wait, or fall back to a self-hosted agent on a VM.

### B3. Import this repo into the new project

Two options:

- **From a local clone** (recommended if you're customising):
  ```pwsh
  git clone <your-source-of-this-repo> fabric-cicd-ado-integration
  cd fabric-cicd-ado-integration
  git remote set-url origin https://dev.azure.com/<your-org>/<your-project>/_git/fabric-cicd-ado-integration
  git push -u origin --all
  ```
- **Import via ADO UI**: Repos → *Import a repository* → paste the source URL.

### B4. Create the `prod` branch

Fabric Git can only bind a workspace to a branch that *exists*. Create `prod` off `dev` once, up front:

```pwsh
git checkout dev
git checkout -b prod
git push -u origin prod
git checkout dev
```

### B5. Set `dev` as the default branch

Repos → *Branches* → pin **dev** as default and add a branch policy on **prod** requiring PR review (optional but recommended for hygiene).

---

## Part C — Identity & permissions (the bulk of the setup)

### C1. Create the Entra app registration (the service principal)

1. Azure portal → **Microsoft Entra ID → App registrations → + New registration**
2. Name: `fabric-cicd-sp` (any name; just keep it consistent across docs / variables).
3. Supported account types: **Single tenant**.
4. Redirect URI: leave blank.
5. After creation, record the **Application (client) ID**, **Object ID**, and **Tenant ID**.

Add a credential the ADO service connection in C5 can use — preferred is a **federated credential** (no secret to rotate); a client secret also works.

### C2. Make the SP a user in Azure DevOps

The SP must exist on the ADO side too, otherwise the Fabric → ADO clone inside `updateFromGit` will 401 even after Fabric trusts the SP.

1. Azure DevOps → **Organization Settings → Users → Add users**
2. Search the SP by application name.
3. Access level: **Basic**.
4. Project: your demo project. Group: **Contributors** (or Project Administrators — Contributors is enough).
5. Verify under Project Settings → *Repositories* → *Security* that the SP has at least **Read**.

### C3. Enable the right Fabric tenant settings

Fabric Admin Portal → **Tenant settings**. Each of the following must be **Enabled** and scoped to either the whole org or a security group that contains the SP:

| Setting | Section |
|---|---|
| Service principals can use Fabric APIs | Developer settings |
| Users can synchronize workspace items with their Git repositories | Git integration |
| Users can export items to Git repositories in their organization | Git integration |

Tenant changes can take several minutes to propagate.

### C4. Grant the SP **Workspace Admin** on both workspaces

For each workspace from A2: open it → **Manage access → +** → search the SP → role: **Admin**. *Member is not enough for Git endpoints — they require Admin.*

### C5. Create the ADO service connection

Azure DevOps → **Project settings → Service connections → New service connection → Azure Resource Manager → Workload identity federation (recommended) → Service Principal (manual)**.

- Name: `fabric-cicd-sp` *(must match the value in [.azuredevops/pipelines/deploy-workspace-per-branch.yml](../.azuredevops/pipelines/deploy-workspace-per-branch.yml) `serviceConnection` variable — change one side or the other if you renamed it)*.
- Fill in subscription / tenant / SP details and complete the federation handshake.
- Grant access to all pipelines (or just this one).

### C6. Create the Fabric Azure DevOps source-control Connection + bind `myGitCredentials`

This is the single piece most often missed; without it Stage 2 of the pipeline fails with `GitCredentialsNotConfigured`. Full procedure with copy-pasteable PowerShell is in **[07-service-principal-fabric-git-setup.md](07-service-principal-fabric-git-setup.md) steps 5 + 6**. Do it once per SP (creating the Connection), then once per workspace (PATCHing `myGitCredentials`).

When you finish, the `git/status` verification snippet at the bottom of doc 07 should return a JSON body for both workspaces. If it doesn't, **stop here** — no later part of this guide will succeed.

---

## Part D — Wire the workspaces to git

The SP can now act, but the workspaces themselves aren't yet bound to any branch.

### D1. Connect each workspace to its branch via the Fabric portal

For the Dev workspace:

1. Fabric portal → `Contoso-Sales-Dev` → **Workspace settings → Git integration → Connect**.
2. Provider: **Azure DevOps**. Pick org / project / repo.
3. Branch: `dev`. Folder (Git folder): `fabric/`. Click **Connect and sync**.
4. Fabric will pull all items under `fabric/` (Lakehouse, Warehouse, SemanticModel, VariableLibrary) into the workspace. Wait for status: *Synced*.

Repeat for the Prod workspace, pointing at branch `prod`, folder `fabric/`.

> The initial sync is done by **your** Entra user, not the SP. That's intentional — it establishes the workspace ↔ repo binding. From then on the SP (via `myGitCredentials` from C6) drives `updateFromGit`.

### D2. Confirm the items materialised

In each workspace you should now see:

- `Contoso_Sales_LH` (Lakehouse)
- `Contoso-Sales-WH` (Warehouse)
- `Contoso-Sales-Model` (SemanticModel)
- `Contoso_Vars` (Variable Library)

Open `Contoso_Vars` → confirm it has 5 variables (`environmentLabel`, `workspaceId`, `lakehouseId`, `warehouseId`, `warehouseSqlEndpoint`) and two value sets (`Dev`, `Prod`).

### D3. Capture the per-environment item IDs

The pipeline's Stage 3 needs the **runtime** workspace / lakehouse / warehouse IDs (which differ from whatever's checked into git — git is scaffolding).

For each workspace, in the Fabric portal, open the workspace and copy:

- Workspace ID (from the URL)
- `Contoso_Sales_LH` Lakehouse item ID (open the item → URL contains `/lakehouses/<guid>`)
- `Contoso-Sales-WH` Warehouse item ID (same pattern)
- Warehouse SQL endpoint (Warehouse → top-right *SQL connection string* button → TDS endpoint)

[demo-ids.json](../demo-ids.json) shows what this looks like once captured for the original demo tenant. **It is a reference snapshot; the pipeline does NOT read it at runtime.**

---

## Part E — Wire the pipeline

### E1. Create the two ADO variable groups

Library entries hold the per-environment IDs from D3. Full step-by-step (with the exact variable names the script expects) is in **[06-dynamic-env-injection.md](06-dynamic-env-injection.md) §1**. Required keys per group:

```
WORKSPACE_ID, LAKEHOUSE_ID, WAREHOUSE_ID, WAREHOUSE_SQL_ENDPOINT, ENVIRONMENT_LABEL, VALUE_SET
```

`VALUE_SET` must equal the Variable Library value-set name exactly (`Dev` in `contoso-fabric-env-dev`, `Prod` in `contoso-fabric-env-prod`).

Optional but recommended: flip each variable to *Link secrets from an Azure Key Vault* once you have a Key Vault.

### E2. Authorise each variable group for the pipeline

Library → group → **Pipeline permissions** → grant the pipeline (named after the .yml file once you register it in E4). See [06 §2](06-dynamic-env-injection.md).

### E3. Create the two ADO Environments + grant pipeline access

Pipelines → **Environments → New environment** → `fabric-dev` (resource: None) → repeat for `fabric-prod`. For each: **⋮ → Security → Pipeline permissions → +** → grant the pipeline. Optional approval gate on `fabric-prod`. Full instructions in [06 §4](06-dynamic-env-injection.md).

### E4. Register the pipeline in ADO

Pipelines → **New pipeline** → Azure Repos Git → pick this repo → **Existing Azure Pipelines YAML file** → `/​.azuredevops/pipelines/deploy-workspace-per-branch.yml`. **Save** (don't *Run* yet). The pipeline is now wired but won't trigger until a push.

### E5. Set the active value set in each workspace (one-time, manual)

There's no public REST endpoint for this yet, so it's a portal click — without it, the Variable Library's "current" values won't match what the pipeline keeps in sync.

- `Contoso-Sales-Dev` workspace → `Contoso_Vars` → **Settings → Active value set → `Dev`**
- `Contoso-Sales-Prod` workspace → same → `Prod`

---

## Part F — First run

### F1. Trigger the pipeline with a no-op commit

```pwsh
git checkout dev
"# touch $(Get-Date -Format o)" | Out-File -Append .azuredevops/pipelines/deploy-workspace-per-branch.yml.trigger
git add .
git commit -m "ci: first end-to-end run"
git push origin dev
```

(The `.trigger` file is throwaway — anywhere in the trigger paths works. Delete it after.)

### F2. Watch all three stages succeed

ADO → Pipelines → your pipeline → latest run:

1. **Validate** — `validate_fabric_items.py` runs offline. Should print *✓ Validated N Fabric items*.
2. **SyncFabricFromBranch** — calls `git/status`, then `updateFromGit`, polls the LRO. Should print *✓ Workspace `<id>` synchronized to commit `<sha>`*.
3. **InjectEnvValues** — installs `requests`, acquires the Fabric token, runs `inject_env_values.py`. Should print resolved VarLib + SemanticModel IDs and either *no-op (decoded content already matches)* or *Updated definition*.

If Stage 2 fails with `InsufficientPrivileges` → back to C3 / C4. With `GitCredentialsNotConfigured` → back to C6. Failure-mode tables in [06](06-dynamic-env-injection.md) and [07](07-service-principal-fabric-git-setup.md) key off the exact error string.

### F3. Verify Dev workspace state

```pwsh
$token = (az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv)
$wsId  = "<Contoso-Sales-Dev workspace id>"
$smId  = (Invoke-RestMethod "https://api.fabric.microsoft.com/v1/workspaces/$wsId/items?type=SemanticModel" `
            -Headers @{ Authorization = "Bearer $token" }).value `
            | Where-Object displayName -eq 'Contoso-Sales-Model' | Select-Object -ExpandProperty id

$def = Invoke-RestMethod -Method POST `
    -Uri "https://api.fabric.microsoft.com/v1/workspaces/$wsId/semanticModels/$smId/getDefinition?format=TMDL" `
    -Headers @{ Authorization = "Bearer $token" }

$expr = $def.definition.parts | Where-Object path -like '*expressions.tmdl'
[System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($expr.payload))
```

The output's `expression WorkspaceId` and `expression LakehouseId` lines should hold the **Dev** values you put in `contoso-fabric-env-dev` — not whatever is checked into git.

---

## Part G — Promote to Prod

```pwsh
git checkout prod
git merge dev --ff-only         # or cherry-pick the specific commit(s)
git push origin prod
```

This re-runs the same three stages, but Stage 2 + Stage 3 now load `contoso-fabric-env-prod` and target `Contoso-Sales-Prod`. Repeat F3's verification against the Prod workspace ID — the M parameter values should be the **Prod** lakehouse / workspace IDs.

This is the whole "promotion" mechanism. No deployment-pipeline rules, no rule-template export — a branch merge IS the promotion, and per-env identity values get rewritten by Stage 3 from the matching variable group.

---

## Part H — Day-2: changing the model / adding variables

Cross-link, not duplication. See **[05-semantic-model-deploy.md](05-semantic-model-deploy.md)** for:

- adding a column to a SemanticModel table
- adding a new Variable Library variable end-to-end (three coordinated edits: `variables.json`, `valueSets/*.json`, ADO variable group, and the `overrides` dict in `inject_env_values.py`)
- adding a new table to the SemanticModel from the Warehouse

---

## Part I — Local development (no Fabric writes)

You can dry-run both Python scripts without authenticating against a workspace, and dry-run the injector against a real workspace **without writing**:

```pwsh
# Pre-deploy validator — fully offline
python scripts/validate_fabric_items.py

# Injector dry-run against a real workspace (reads only; DRY_RUN=1 skips every write)
$env:FABRIC_TOKEN         = (az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv)
$env:FABRIC_WORKSPACE_ID  = "<dev workspace id>"
$env:INJECT_VALUE_SET     = "Dev"
$env:INJECT_ENV_LABEL     = "Dev"
$env:INJECT_WORKSPACE_ID  = "<dev workspace id>"
$env:INJECT_LAKEHOUSE_ID  = "<dev lakehouse id>"
$env:INJECT_WAREHOUSE_ID  = "<dev warehouse id>"
$env:INJECT_WAREHOUSE_SQL = "<dev sql endpoint>"
$env:DRY_RUN              = "1"
python scripts/inject_env_values.py
```

Full set of injector env vars + their meanings is documented in the script's docstring ([scripts/inject_env_values.py](../scripts/inject_env_values.py)) and in [06 §local-dry-run](06-dynamic-env-injection.md).

Unit tests for the injector helpers run with no external dependencies:

```pwsh
pip install pytest
python -m pytest tests
```

---

## Part J — Teardown

To delete everything cleanly:

1. **ADO pipeline** → Pipelines → ⋮ → Delete.
2. **ADO variable groups + environments** → Library / Environments → ⋮ → Delete.
3. **ADO service connection** → Project Settings → Service connections → ⋮ → Delete.
4. **Fabric workspaces** → each workspace → *Workspace settings* → Delete.
5. **Fabric ADO source-control Connection** → Manage connections and gateways → Connections → ⋮ → Delete.
6. **Entra app registration** → App registrations → app → Delete.
7. **Fabric capacity** (if F-SKU) → Azure portal → Microsoft Fabric → Delete the capacity resource. Trial capacity expires automatically after 60 days.

Repo itself is fine to leave — it has no live secrets.

---

## Reproduction checklist (single page)

Copy this checklist into the issue / handover note for whoever is doing the next stand-up:

- [ ] **A1** Fabric capacity in place
- [ ] **A2** `Contoso-Sales-Dev` + `Contoso-Sales-Prod` workspaces created, capacity-bound
- [ ] **B1** ADO project exists
- [ ] **B2** Hosted-agent parallelism approved
- [ ] **B3** Repo imported
- [ ] **B4** `prod` branch created
- [ ] **C1** Entra app registered (SP)
- [ ] **C2** SP added to ADO org + project
- [ ] **C3** All three Fabric tenant settings enabled for the SP's security group
- [ ] **C4** SP is Workspace **Admin** on both workspaces
- [ ] **C5** ADO service connection created (federated identity)
- [ ] **C6** Fabric ADO source-control Connection + `myGitCredentials` bound per workspace ([doc 07](07-service-principal-fabric-git-setup.md))
- [ ] **D1** Both workspaces connected to their branches in the Fabric portal
- [ ] **D2** All four items present in both workspaces
- [ ] **D3** Per-env IDs captured
- [ ] **E1** ADO variable groups `contoso-fabric-env-dev` / `-prod` populated ([doc 06 §1](06-dynamic-env-injection.md))
- [ ] **E2** Variable groups authorised for the pipeline
- [ ] **E3** `fabric-dev` + `fabric-prod` ADO Environments created, pipeline authorised
- [ ] **E4** Pipeline registered against `.azuredevops/pipelines/deploy-workspace-per-branch.yml`
- [ ] **E5** Active value set selected per workspace
- [ ] **F2** First `dev` push triggers all three stages green
- [ ] **F3** SemanticModel M params reflect Dev values
- [ ] **G** First `prod` promotion triggers all three stages green, Prod values land

If every box is ticked, the demo is reproduced.
