# 04 — Architecture & best practices (single-path reference)

> **Scope.** Companion reference for the Contoso Sales Fabric CI/CD pattern as implemented in this repo: **ADO YAML + Fabric Git, one branch per workspace, with per-workspace value injection via Fabric REST** (Microsoft Learn [Option 1](https://learn.microsoft.com/en-us/fabric/cicd/manage-deployment)). Alternative MS-canonical options exist; they are mentioned at the bottom for awareness only. The shipped pipeline is [deploy-workspace-per-branch.yml](../.azuredevops/pipelines/deploy-workspace-per-branch.yml).

> **Source.** Synthesised from Microsoft Learn, the [official Fabric CI/CD tutorial](https://learn.microsoft.com/en-us/fabric/cicd/tutorial-fabric-cicd-azure-devops), and the Fabric Catalyst DevOps docs. URLs verified 2026-05-19.

---

## Executive summary

| | |
|---|---|
| **Reference architecture** | Two Fabric workspaces (`Contoso-Sales-Dev`, `Contoso-Sales-Prod`), each bound to one git branch (`dev`, `prod`) via Fabric Git integration. A single ADO pipeline triggers on push to either branch and runs Validate → Sync → Inject. |
| **Required resources** | Microsoft Fabric capacity (Trial or F-SKU); ADO project + repo + pipeline; Entra Service Principal with Workspace Admin role on both workspaces; Fabric ADO source-control Connection + per-workspace `myGitCredentials`; ADO variable groups for per-env IDs (Key Vault–backable). |
| **CI/CD flow** | Author in Dev workspace or VS Code → commit + push to `dev` → pipeline syncs Dev workspace + injects Dev values → merge `dev → prod` → same pipeline syncs Prod workspace + injects Prod values. |
| **Best practices** | Branch policy on `prod` requiring PR review; optional ADO Environment approval gate on `fabric-prod`; Key Vault–back any secret variable; tenant setting *Service principals can use Fabric APIs* on and scoped to the SP. |

---

## Architecture

### Environment isolation

Two workspaces, each on its own bound branch:

| Workspace | Bound branch | ADO variable group | Active VarLib value set |
|---|---|---|---|
| `Contoso-Sales-Dev` | `dev` | `contoso-fabric-env-dev` | `Dev` |
| `Contoso-Sales-Prod` | `prod` | `contoso-fabric-env-prod` | `Prod` |

Both workspaces sit on a Fabric capacity (Trial for the demo; F-SKU recommended for production). To add a third tier (e.g. `qa`), repeat the three columns above.

### Git-centric workflow

The ADO repo is the single source of truth for **structure**: Fabric items live under `fabric/`. Per-environment **values** (workspace IDs, lakehouse IDs, warehouse IDs, SQL endpoints, env label) live in ADO variable groups, not in git. Git holds scaffolding defaults for those values so a bare `updateFromGit` outside the pipeline still leaves the workspace in a working state, but the pipeline's Stage 3 always overwrites them with the env-correct values.

### Tenant-agnostic design

Nothing in the committed fabric items or pipeline YAML is tenant-specific. To stand the demo up in a new tenant, you change:

- The two ADO variable groups (per-env IDs).
- The `serviceConnection` variable in the pipeline YAML (or rename the ADO service connection to match).
- The Fabric portal Git binding per workspace (one-time UI step).

The codebase is reusable as-is.

---

## Pipeline step-by-step walkthrough

The active pipeline is [`.azuredevops/pipelines/deploy-workspace-per-branch.yml`](../.azuredevops/pipelines/deploy-workspace-per-branch.yml).

### Trigger & scope

```yaml
trigger:
  branches:
    include: [dev, prod]
  paths:
    include: [fabric/*, scripts/*, .azuredevops/pipelines/*]
```

The pipeline fires on **pushes** to `dev` or `prod` that touch Fabric items, scripts, or the pipeline definition itself. A separate `pr:` trigger runs Stage 1 only (validation) on pull requests targeting either branch — Stages 2 and 3 are gated with `condition: ... in(variables['Build.SourceBranch'], 'refs/heads/dev', 'refs/heads/prod')` so they never run on PRs.

> **MS Learn ref:** [YAML pipeline triggers](https://learn.microsoft.com/en-us/azure/devops/pipelines/repos/azure-repos-git?tabs=yaml#ci-triggers) · [Path filters](https://learn.microsoft.com/en-us/azure/devops/pipelines/repos/azure-repos-git?tabs=yaml#paths)

### Variable group selection (compile-time)

```yaml
variables:
  - ${{ if eq(variables['Build.SourceBranchName'], 'dev') }}:
    - group: contoso-fabric-env-dev
  - ${{ if eq(variables['Build.SourceBranchName'], 'prod') }}:
    - group: contoso-fabric-env-prod
```

`${{ }}` is a **template expression** evaluated at compile time, not runtime — this is intentional because ADO variable group authorization is resolved at compile time. The selected group supplies `WORKSPACE_ID`, `LAKEHOUSE_ID`, `WAREHOUSE_ID`, `WAREHOUSE_SQL_ENDPOINT`, `ENVIRONMENT_LABEL`, `VALUE_SET`, and (optionally) `GIT_CONNECTION_ID`.

> **MS Learn ref:** [Variable groups in pipelines](https://learn.microsoft.com/en-us/azure/devops/pipelines/library/variable-groups) · [Template expressions](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/template-expressions)

### Authentication (shared pattern across Stages 2 + 3)

Both stages use [`AzureCLI@2`](https://learn.microsoft.com/en-us/azure/devops/pipelines/tasks/reference/azure-cli-v2) with the service connection `fabric-cicd-sp`. The service connection authenticates via **workload identity federation** (no client secret stored). Inside each task:

```bash
az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv
```

This returns a Fabric API bearer token scoped to the SP. The token is acquired **inside** each task rather than passed across tasks — `AzureCLI@2` handles the login context, and tokens have a finite lifetime.

> **MS Learn ref:** [Workload identity federation for service connections](https://learn.microsoft.com/en-us/azure/devops/pipelines/library/connect-to-azure?tabs=yaml#create-an-azure-resource-manager-service-connection-that-uses-workload-identity-federation) · [AzureCLI@2 task](https://learn.microsoft.com/en-us/azure/devops/pipelines/tasks/reference/azure-cli-v2)

---

### Stage 1 · Validate

**Purpose:** Catch structural problems before Fabric ever sees the commit. No Fabric API calls — purely local file checks.

| Step | Task | What it does |
|---|---|---|
| 1.1 | `checkout: self` (fetchDepth: 2) | Shallow clone of the branch. Depth 2 allows diff against the prior commit. |
| 1.2 | `UsePythonVersion@0` | Pins Python 3.11 on the agent. |
| 1.3 | `python scripts/validate_fabric_items.py` | Walks `fabric/` and validates: |
| | | • Every item folder has a well-formed `.platform` / metadata manifest. |
| | | • `variables.json` + each `valueSets/*.json` parse and reference matching variable names. |
| | | • SemanticModel TMDL files exist; `expressions.tmdl` defines `WorkspaceId` + `LakehouseId` **exactly once each**. |
| | | • No obvious M syntax bugs (unmatched quotes, stray `#` references). |
| | | Exit code 1 stops the pipeline — no Fabric call is ever made for a broken commit. |
| 1.4 | `git diff` script | Detects which Fabric items changed between this commit and the prior one (or PR merge base). Outputs `changed_items.txt` for visibility in the pipeline log. |

> **MS Learn ref:** [Source code format per item type](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/source-code-format) — defines the expected folder structure / metadata files the validator checks against. [Variable Library overview](https://learn.microsoft.com/en-us/fabric/cicd/variable-library/variable-library-overview) — schema for `variables.json` and value sets.

---

### Stage 2 · SyncFabricFromBranch

**Purpose:** Tell Fabric "your branch advanced; please pull." The stage owns the LRO poll so the workspace is observably at branch HEAD before Stage 3 starts.

**Runs only on direct pushes** to `dev` or `prod` (skipped on PRs).

| Step | Task | What it does | Fabric REST endpoint |
|---|---|---|---|
| 2.1 | `AzureCLI@2` — *Ensure myGitCredentials* | PATCHes the SP's per-workspace Git credential binding to a Fabric ADO source-control Connection. **Conditional** — only runs if `GIT_CONNECTION_ID` is set in the variable group. Idempotent (re-running with the same `connectionId` is a no-op). Without this, the first `updateFromGit` from a new SP/workspace pair fails with `GitCredentialsNotConfigured`. | [`PATCH /v1/workspaces/{wsId}/git/myGitCredentials`](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/update-my-git-credentials) |
| 2.2 | `AzureCLI@2` — *Fabric updateFromGit + poll* | **Step A — Status check:** `GET .../git/status` returns `workspaceHead` (the commit the workspace is currently at) and `remoteCommitHash` (the branch's latest commit). If they match and there are no pending changes, the step exits early (already synced). | [`GET /v1/workspaces/{wsId}/git/status`](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/get-status) |
| | | **Step B — Sync:** `POST .../git/updateFromGit` with `conflictResolutionPolicy: PreferRemote` (branch is truth; workspace uncommitted edits are overwritten). Fabric returns a `202 Accepted` with an `x-ms-operation-id` header for the long-running operation. | [`POST /v1/workspaces/{wsId}/git/updateFromGit`](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/update-from-git) |
| | | **Step C — Poll LRO:** Every 8 seconds, `GET /v1/operations/{opId}` until `status` is no longer `NotStarted` or `Running`. On `Succeeded` → log and proceed. On anything else → fail the pipeline with full error JSON. | [`GET /v1/operations/{opId}`](https://learn.microsoft.com/en-us/rest/api/fabric/core/long-running-operations/get-operation-state) |

> **MS Learn ref:** [Git automation (REST)](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-automation) — end-to-end guide for automating Git operations via REST. [Git integration process](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-integration-process) — how Fabric's sync works under the hood. [Conflict resolution](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/conflict-resolution) — explains the `PreferRemote` policy.

**SP prerequisites for this stage to work:**
- SP must be **Workspace Admin** on the target workspace.
- Tenant setting *Service principals can use Fabric APIs* must be enabled.
- Fabric ADO source-control Connection + `myGitCredentials` must be configured (step 2.1 handles the bind; the Connection itself is a one-time creation — see [docs/07](07-service-principal-fabric-git-setup.md)).
- SP must be a **user** in the ADO organisation with at least **Read** on the repo.

---

### Stage 3 · InjectEnvValues

**Purpose:** Overwrite per-environment values in the just-synced workspace so the workspace's runtime state matches the ADO variable group, not whatever was committed in git. Solves the Direct Lake parameter-swap limitation — see [docs/01](01-direct-lake-variables.md).

**Runs only on direct pushes** to `dev` or `prod` (skipped on PRs). Depends on Stage 2 succeeding.

| Step | Task | What it does |
|---|---|---|
| 3.1 | `checkout: self` (fetchDepth: 1) | Pipeline needs `scripts/inject_env_values.py` and `scripts/requirements.txt` on disk. |
| 3.2 | `UsePythonVersion@0` | Pins Python 3.11. |
| 3.3 | `pip install -r scripts/requirements.txt` | Installs `requests` (the only external dependency). |
| 3.4 | `AzureCLI@2` — *Acquire Fabric token + run injector* | Acquires a fresh Fabric token, exports it as `FABRIC_TOKEN`, then runs `python scripts/inject_env_values.py` with the following env vars from the ADO variable group: |
| | | `FABRIC_WORKSPACE_ID` — which workspace to target |
| | | `INJECT_VALUE_SET` — which VarLib value set to overwrite (`Dev` or `Prod`) |
| | | `INJECT_ENV_LABEL` — the environment label to write (`Dev` or `Prod`) |
| | | `INJECT_WORKSPACE_ID`, `INJECT_LAKEHOUSE_ID`, `INJECT_WAREHOUSE_ID`, `INJECT_WAREHOUSE_SQL` — the per-env identifiers |

**What `inject_env_values.py` does internally (Stage 3.4 detail):**

| Sub-step | Action | Fabric REST endpoint |
|---|---|---|
| 3.4a | List items in workspace, find the **one** `VariableLibrary` named `Contoso_Vars` and the **one** `SemanticModel` named `Contoso-Sales-Model`. Fail loudly if zero or multiple matches. | [`GET /v1/workspaces/{wsId}/items?type=VariableLibrary`](https://learn.microsoft.com/en-us/rest/api/fabric/core/items/list-items) |
| 3.4b | **Variable Library write:** `POST .../items/{vlId}/getDefinition` → decode base64 parts → find `valueSets/<Dev\|Prod>.json` → update each `variableOverrides[i].value` to the ADO-supplied value → compare to original bytes → **skip** `updateDefinition` if identical; otherwise `POST .../items/{vlId}/updateDefinition`. | [`POST .../items/{id}/getDefinition`](https://learn.microsoft.com/en-us/rest/api/fabric/core/items/get-item-definition) · [`POST .../items/{id}/updateDefinition`](https://learn.microsoft.com/en-us/rest/api/fabric/core/items/update-item-definition) |
| 3.4c | **SemanticModel write:** `POST .../semanticModels/{smId}/getDefinition?format=TMDL` → decode `definition/expressions.tmdl` → regex-replace `expression WorkspaceId = "..."` and `expression LakehouseId = "..."` values (each must match exactly once — fail if zero or multiple) → compare to original → **skip** if identical; otherwise `POST .../semanticModels/{smId}/updateDefinition`. | [`POST .../semanticModels/{id}/getDefinition`](https://learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items/get-semantic-model-definition) · [`POST .../semanticModels/{id}/updateDefinition`](https://learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items/update-semantic-model-definition) |
| 3.4d | **Verify:** Re-fetch the SemanticModel definition and confirm the new M parameter values are observable. If they don't match, fail with a verification error. | Same `getDefinition` as 3.4c |

> **MS Learn ref:** [Items — getDefinition / updateDefinition](https://learn.microsoft.com/en-us/rest/api/fabric/core/items) · [Semantic Models — getDefinition / updateDefinition](https://learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items) · [Variable Library overview](https://learn.microsoft.com/en-us/fabric/cicd/variable-library/variable-library-overview) · Full setup runbook for the variable groups + env vars: [docs/06](06-dynamic-env-injection.md)

---

### ADO Environments + approval gates

Each `deployment:` job references an ADO Environment named `fabric-$(Build.SourceBranchName)` — resolves to `fabric-dev` on `dev` pushes and `fabric-prod` on `prod` pushes.

These environments must be **pre-created** in ADO before the first pipeline run (Pipelines → Environments → New environment → name: `fabric-dev` / `fabric-prod`, resource: None). Grant the pipeline access via each environment's Security → Pipeline permissions. See [docs/06 §4](06-dynamic-env-injection.md).

**Optional:** Add an *Approvals and checks* gate on `fabric-prod` to require explicit human approval before Stages 2 + 3 run against the Prod workspace.

> **MS Learn ref:** [Define approvals and checks](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/approvals) · [Environments](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/environments)

---

### End-to-end flow summary

```
push to dev (or prod)
        │
        ▼
┌───────────────────────────────────────────────────────────────────┐
│ Stage 1 · Validate                                                │
│  1.1  checkout (fetchDepth: 2)                                    │
│  1.2  UsePythonVersion 3.11                                       │
│  1.3  python validate_fabric_items.py                             │
│  1.4  git diff → changed_items.txt                                │
│       EXIT if validation fails                                    │
└───────────────────────────────────────────────────────────────────┘
        │ on success + direct push (not PR)
        ▼
┌───────────────────────────────────────────────────────────────────┐
│ Stage 2 · SyncFabricFromBranch                                    │
│  2.1  PATCH myGitCredentials (if GIT_CONNECTION_ID set)           │
│  2.2a GET  /git/status  → workspaceHead vs remoteCommitHash      │
│  2.2b POST /git/updateFromGit (PreferRemote)                     │
│  2.2c GET  /operations/{opId} → poll until Succeeded              │
│       EXIT if sync fails                                          │
└───────────────────────────────────────────────────────────────────┘
        │ on success
        ▼
┌───────────────────────────────────────────────────────────────────┐
│ Stage 3 · InjectEnvValues                                         │
│  3.1  checkout (fetchDepth: 1)                                    │
│  3.2  UsePythonVersion 3.11                                       │
│  3.3  pip install requests                                        │
│  3.4a Find Contoso_Vars (VarLib) + Contoso-Sales-Model (SemModel)      │
│  3.4b VarLib:  getDefinition → mutate value set → updateDefinition│
│  3.4c SemModel: getDefinition → rewrite M params → updateDefinition│
│  3.4d SemModel: re-fetch → verify values round-tripped            │
└───────────────────────────────────────────────────────────────────┘
        │
        ▼
Workspace reflects per-environment values from ADO variable group.
```

### Cross-reference index

| Pipeline concept | This repo | MS Learn |
|---|---|---|
| YAML triggers | Lines 37–55 of `deploy-workspace-per-branch.yml` | [CI triggers](https://learn.microsoft.com/en-us/azure/devops/pipelines/repos/azure-repos-git?tabs=yaml#ci-triggers) |
| Variable groups | `contoso-fabric-env-dev` / `-prod` in ADO Library | [Variable groups](https://learn.microsoft.com/en-us/azure/devops/pipelines/library/variable-groups) |
| Template expressions (`${{ }}`) | Variable group selection block | [Template expressions](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/template-expressions) |
| Service connection (WIF) | `fabric-cicd-sp` | [Workload identity federation](https://learn.microsoft.com/en-us/azure/devops/pipelines/library/connect-to-azure?tabs=yaml) |
| AzureCLI@2 task | Stages 2 + 3 | [AzureCLI@2 reference](https://learn.microsoft.com/en-us/azure/devops/pipelines/tasks/reference/azure-cli-v2) |
| ADO Environments | `fabric-dev` / `fabric-prod` | [Environments](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/environments) |
| Approval gates | Optional on `fabric-prod` | [Approvals and checks](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/approvals) |
| `myGitCredentials` PATCH | Step 2.1 | [Update My Git Credentials](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/update-my-git-credentials) |
| `git/status` | Step 2.2a | [Git — Get Status](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/get-status) |
| `git/updateFromGit` | Step 2.2b | [Git — Update From Git](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/update-from-git) |
| LRO polling | Step 2.2c | [Get Operation State](https://learn.microsoft.com/en-us/rest/api/fabric/core/long-running-operations/get-operation-state) |
| Items `getDefinition` / `updateDefinition` | Step 3.4b (VarLib) | [Items API](https://learn.microsoft.com/en-us/rest/api/fabric/core/items) |
| SemanticModel `getDefinition` / `updateDefinition` | Steps 3.4c–d | [Semantic Models API](https://learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items) |
| Git automation overview | Full pipeline | [Git automation](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-automation) |
| Conflict resolution (`PreferRemote`) | Step 2.2b body | [Conflict resolution](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/conflict-resolution) |
| Variable Library | Steps 3.4a–b | [Variable Library overview](https://learn.microsoft.com/en-us/fabric/cicd/variable-library/variable-library-overview) |
| TMDL format | Step 3.4c | [TMDL overview](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview) |
| SP tenant setting | Prereq for all Fabric calls | [Git integration admin settings](https://learn.microsoft.com/en-us/fabric/admin/git-integration-admin-settings) |
| SP + Fabric Git onboarding | Steps 2.1 + [docs/07](07-service-principal-fabric-git-setup.md) | [Git integration process](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-integration-process) |

---

## Best practices & guardrails

### Branching strategy

- Two long-lived branches (`dev`, `prod`). `dev` is the default and the author target. `prod` carries a branch policy requiring PR approval from a non-author.
- Merge direction is always `dev → prod`. Hot-fixes on `prod` should be cherry-picked back into `dev` immediately to prevent drift.
- Avoid `qa` / `test` branches unless a real change-control reason exists; the same pattern adds them cleanly when needed.

### Parameterisation

- **Never hard-code env-specific values** in committed Fabric items beyond scaffolding defaults.
- Fabric **Variable Library** (GA April 2026) holds workspace-wide env values (e.g. `environmentLabel`) for notebooks / pipelines to read.
- **M parameters in `expressions.tmdl`** carry the Direct Lake source URL pieces; Stage 3 overwrites them per workspace. See [docs/01](01-direct-lake-variables.md).

### Secrets management

- ADO **service connection** uses workload identity federation — no client secret stored anywhere.
- ADO variable groups should be **Key Vault–linked** for any value that's a secret. The pipeline reads them the same way either way.
- Pipeline never logs raw token values.

### Automation & approvals

- Make deployments boring: Validate → Sync → Inject runs identically on every push.
- Use ADO Environment approval gates on `fabric-prod` if you want an explicit human checkpoint without changing the pipeline shape.

### Error handling & rollback

- Pipeline stops and reports on any failure; nothing partial gets promoted.
- Rollback = revert the commit on `prod` and push — the same three stages re-run with the previous content.
- Fabric workspace **version history** (the git commit log on the bound branch) is the restore mechanism.

### Naming conventions

- Workspaces: `<App>-<Tier>` (`Contoso-Sales-Dev`, `Contoso-Sales-Prod`).
- ADO variable groups: `contoso-fabric-env-<tier>`.
- ADO environments: `fabric-<tier>`.
- Pipeline: one file, branch-conditional, never multiplied across stages.

---

## Pitfalls, constraints & gotchas

### Direct Lake parameter limitations

Direct Lake on OneLake semantic models cannot use Deployment Pipeline rules to swap workspace/lakehouse IDs (UI is greyed out). The supported answer is **M parameters in `expressions.tmdl`** rewritten per workspace by Stage 3. Full mechanism: [docs/01](01-direct-lake-variables.md) and [docs/06](06-dynamic-env-injection.md).

### Service Principal limitations

- Tenant setting **Service principals can use Fabric APIs** must be ON and scoped to a security group containing the SP. Most common stumbling block.
- For Git endpoints the SP also needs a Fabric **Azure DevOps source-control Connection** and a per-workspace `myGitCredentials` binding. One-time runbook: [docs/07](07-service-principal-fabric-git-setup.md). Symptoms when missed: `InsufficientPrivileges` (missing Admin / tenant setting) or `GitCredentialsNotConfigured` (missing `myGitCredentials`).
- The SP must also be a real **user in the ADO organisation** with Read on the repo — otherwise the Fabric → ADO call inside `updateFromGit` 401s. See [docs/07 §4](07-service-principal-fabric-git-setup.md).

### Git integration constraints

- Each workspace can connect to **one** repository branch at a time.
- Multiple developers needing isolated work: per-developer branches with workspace switching, or use Fabric's *branch out* feature to spawn a per-dev workspace.
- Commit in logical batches — Fabric's sync time scales with the diff size.

### ADO new-org parallelism

New ADO orgs have **zero** free hosted-agent parallelism. Request it via [aka.ms/azpipelines-parallelism-request](https://aka.ms/azpipelines-parallelism-request) — 2–3 business day approval. Alternative: self-hosted agent.

### Active value-set selection is manual

There is no public REST endpoint today to set a Variable Library's **active** value set. After the first deploy, set it once per workspace in the Fabric portal (`Dev` for Dev, `Prod` for Prod). The pipeline keeps the value-set CONTENTS current; it does not change which set is active.

---

## When you might pick something else

This repo deliberately ships one path. Two alternatives might fit if requirements change:

- **Fabric Deployment Pipelines (MS Option 3).** Lower behaviour change if you're already on Fabric DP and have no SP-Warehouse promotion need. Today blocked for Contoso by `PrincipalTypeNotSupported` on Warehouse + greyed-out DP rules for Direct Lake on OneLake.
- **`microsoft/fabric-cicd` Python SDK / Bulk-Import-Item-Definitions API (MS Option 2).** Code-first. Useful for multi-tenant fan-out (deploy the same item to many customer workspaces) or for item types Git integration doesn't yet cover. Adds a Python codebase to own.

Both can re-use the variable-group + injection pattern from [docs/06](06-dynamic-env-injection.md) unchanged.

---

## Canonical references

### Start here
- **[Tutorial: Fabric CI/CD with Azure DevOps](https://learn.microsoft.com/en-us/fabric/cicd/tutorial-fabric-cicd-azure-devops)** — Microsoft's official end-to-end tutorial; mirrors the architecture in this doc.
- [Fabric CI/CD overview](https://learn.microsoft.com/en-us/fabric/cicd/cicd-overview)
- [Fabric CI/CD best practices](https://learn.microsoft.com/en-us/fabric/cicd/best-practices-cicd)
- [Choose the best Fabric CI/CD workflow option for you](https://learn.microsoft.com/en-us/fabric/cicd/manage-deployment)

### The implemented path (Git integration + automation)
- [Git integration intro](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/intro-to-git-integration)
- [Git integration process](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-integration-process)
- [Git automation (REST)](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-automation)
- [Source code format per item type](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/source-code-format)
- [Conflict resolution](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/conflict-resolution)
- [Manage branches](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/manage-branches)
- [`Git - Update From Git` REST](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/update-from-git)
- [`myGitCredentials - Update` REST](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/update-my-git-credentials)

### Variables, secrets, and env-specific values
- [Variable Library overview (GA)](https://learn.microsoft.com/en-us/fabric/cicd/variable-library/variable-library-overview)
- [Direct Lake overview](https://learn.microsoft.com/en-us/power-bi/enterprise/directlake-overview)
- [Power BI / TMDL projects](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview)

### Item-specific source control
- [Warehouse source control](https://learn.microsoft.com/en-us/fabric/data-warehouse/source-control)

### Tenant admin
- [Git integration admin settings](https://learn.microsoft.com/en-us/fabric/admin/git-integration-admin-settings)
- [Fabric Admin Portal — tenant settings reference](https://learn.microsoft.com/en-us/fabric/admin/about-tenant-settings)
