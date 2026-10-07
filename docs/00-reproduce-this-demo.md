[README](../README.md) › [docs index](./00-reproduce-this-demo.md) › 00 Reproduce this demo

# 00 - Reproduce this demo

<p>
<img src="./assets/icons/fabric.svg" width="40" alt="Microsoft Fabric"/>&nbsp;
<img src="./assets/icons/fabric-workspace.svg" width="40" alt="Fabric workspaces"/>&nbsp;
<img src="./assets/icons/azure-devops.svg" width="40" alt="Azure DevOps"/>&nbsp;
<img src="./assets/icons/app-registrations.svg" width="40" alt="App registrations"/>&nbsp;
<img src="./assets/icons/keys.svg" width="40" alt="Variable groups"/>&nbsp;
<img src="./assets/icons/variable-library.svg" width="40" alt="Variable library"/>
</p>

![Default](./assets/badges/default.svg) ![Path 2 live-tested](./assets/badges/path2-live.svg) ![MS Learn Option 1](./assets/badges/learn-option1.svg)

The single-page orchestrator for standing the demo up against a fresh Fabric tenant and Azure DevOps organisation. Each Part below is a checkpoint - finish A before B. Deep-dive runbooks ([10 - env injection](./10-dynamic-env-injection.md), [11 - service principal setup](./11-service-principal-fabric-git-setup.md)) are linked from the step that needs them rather than repeated here. Forward this page to whoever does the next stand-up.

## At a glance

| | Item | First time | Repeat in the same tenant |
|---|---|---|---|
| <img src="./assets/icons/fabric.svg" width="24" alt=""/> | Parts A-B: capacity, workspaces, ADO project | 45 min | 15 min |
| <img src="./assets/icons/app-registrations.svg" width="24" alt=""/> | Part C: identity + tenant settings | 1-2 h (setting propagation) | 15 min |
| <img src="./assets/icons/git-branch-sync.svg" width="24" alt=""/> | Parts D-E: Git binding, variable groups, pipeline | 1 h | 20 min |
| <img src="./assets/icons/azure-devops.svg" width="24" alt=""/> | Parts F-G: first run + promotion | 20 min | 10 min |
| <img src="./assets/icons/alerts.svg" width="24" alt=""/> | Hosted-agent parallelism grant (new ADO orgs) | 2-3 business days | - |

> [!IMPORTANT]
> A brand-new Azure DevOps organisation has **no** free Microsoft-hosted parallel jobs. Request the grant on day one ([aka.ms/azpipelines-parallelism-request](https://aka.ms/azpipelines-parallelism-request)) or plan a self-hosted agent. Without it the pipeline is registered but never runs.

## What you'll end up with

[![Reference architecture](./assets/fabric-cicd-ado-integration-architecture.png)](./assets/fabric-cicd-ado-integration-architecture.png)

<sub>Editable source: [`assets/fabric-cicd-ado-integration-architecture.drawio`](./assets/fabric-cicd-ado-integration-architecture.drawio) - regenerate with `python scripts/export_diagrams.py docs/assets`.</sub>

Terminal-friendly sketch of the same end state:

```
   Azure DevOps
     Repo: dev + prod branches, items under fabric/
     Pipeline: deploy-workspace-per-branch.yml  (Validate -> Sync -> Inject)
     Variable groups: contoso-fabric-env-dev / -prod
     Environments: fabric-dev / fabric-prod
     Service connection: fabric-cicd-sp (workload identity federation)
                     |  POST /git/updateFromGit
                     |  POST /items/{id}/updateDefinition
                     v
   Microsoft Fabric (capacity: F2+ or trial)
     Contoso-Sales-Dev  <-> dev    Lakehouse | Warehouse | SemanticModel | VarLib (value set Dev)
     Contoso-Sales-Prod <-> prod   same items                            (value set Prod)
```

The pipeline owns each workspace's runtime values; Git holds structure plus scaffolding only.

## Parts at a glance

| Part | | Action | Checkpoint |
|---|---|---|---|
| **A** | <img src="./assets/icons/fabric.svg" width="28" alt=""/> | Capacity + two workspaces | ☐ Both workspaces on a capacity |
| **B** | <img src="./assets/icons/azure-devops.svg" width="28" alt=""/> | ADO project, repo import, `prod` branch | ☐ `dev` and `prod` exist |
| **C** | <img src="./assets/icons/app-registrations.svg" width="28" alt=""/> | Service principal, tenant settings, roles, connection | ☐ `git/status` works as the SP |
| **D** | <img src="./assets/icons/git-branch-sync.svg" width="28" alt=""/> | Bind each workspace to its branch | ☐ Four items in each workspace |
| **E** | <img src="./assets/icons/keys.svg" width="28" alt=""/> | Variable groups, environments, pipeline, active value sets | ☐ Pipeline saved |
| **F** | <img src="./assets/icons/code.svg" width="28" alt=""/> | First run on `dev` | ☐ Three stages green, Dev IDs in the model |
| **G** | <img src="./assets/icons/commit.svg" width="28" alt=""/> | Promote to `prod` | ☐ Prod IDs in the Prod model |

## Prerequisites checklist

Full detail, roles and cost are in [02 - Prerequisites](./02-prerequisites.md). Confirm before Part A:

| | Need | Why |
|---|---|---|
| <img src="./assets/icons/entra-id.svg" width="24" alt=""/> | Microsoft Entra tenant where you can register apps | The service principal |
| <img src="./assets/icons/users.svg" width="24" alt=""/> | A Fabric administrator | Tenant settings in Part C |
| <img src="./assets/icons/azure-devops.svg" width="24" alt=""/> | ADO organisation in the same tenant | Repo, pipeline, service connection |
| <img src="./assets/icons/dev-console.svg" width="24" alt=""/> | `git`, Python 3.11+, Azure CLI | Local checks and REST verification |

## Part A - Provision Microsoft Fabric

**A1. Capacity.** Use a paid **F-SKU** (F2 is enough for this demo; Azure portal -> Create a resource -> Microsoft Fabric) or a **Fabric trial**, which Microsoft provisions as an F4 or F64 capacity for 60 days ([Fabric trial](https://learn.microsoft.com/en-us/fabric/fundamentals/fabric-trial)). Trials are for demos only.

**A2. Workspaces.** Fabric portal -> Workspaces -> New workspace -> `Contoso-Sales-Dev`, license mode Fabric capacity; repeat for `Contoso-Sales-Prod`. Copy each workspace ID from the URL (`/groups/<guid>`) into your `demo-ids.local.json`.

> [!TIP]
> Need a QA tier? Add a third workspace, a `qa` branch, a `contoso-fabric-env-qa` group and `qa` in the pipeline's branch lists. Nothing else changes.

## Part B - Provision Azure DevOps

```pwsh
# B1-B3: create the project in the portal, then push this repo into it
git clone <source-of-this-repo> fabric-cicd-ado-integration
cd fabric-cicd-ado-integration
git remote set-url origin https://dev.azure.com/<your-org>/<your-project>/_git/fabric-cicd-ado-integration
git push -u origin --all

# B4: Fabric can only bind a workspace to a branch that exists
git checkout -b prod dev
git push -u origin prod
git checkout dev
```

**B2.** Project settings -> Parallel jobs: if Microsoft-hosted shows 0, see the callout at the top. **B5.** Make `dev` the default branch and add a branch policy on `prod` (required reviewer).

## Part C - Identity and permissions

This is the bulk of the setup. The one-time runbook with copy-paste PowerShell is [11 - Service principal + Fabric Git setup](./11-service-principal-fabric-git-setup.md); the summary:

| Step | | Do | Fails later as |
|---|---|---|---|
| **C1** | <img src="./assets/icons/app-registrations.svg" width="24" alt=""/> | App registration (single tenant) + federated credential for the service connection | - |
| **C2** | <img src="./assets/icons/users.svg" width="24" alt=""/> | Add the SP to the ADO org (Basic) and the project's Contributors | `GitCloneFailure` / 401 |
| **C3** | <img src="./assets/icons/policy.svg" width="24" alt=""/> | Tenant settings: *Service principals can call Fabric public APIs*; *Users can synchronize workspace items with their Git repositories* | `InsufficientPrivileges` |
| **C4** | <img src="./assets/icons/fabric-workspace.svg" width="24" alt=""/> | SP **Admin** on both workspaces | `InsufficientPrivileges` / 403 |
| **C5** | <img src="./assets/icons/entra-workload-id.svg" width="24" alt=""/> | ADO service connection `fabric-cicd-sp` (Azure Resource Manager, workload identity federation) | auth failure in Stage 2 |
| **C6** | <img src="./assets/icons/git-branch-sync.svg" width="24" alt=""/> | Fabric Azure DevOps source-control connection; SP has the User role; note its ID | `GitCredentialsNotConfigured` |

> [!WARNING]
> Stop here if `GET /v1/workspaces/{id}/git/status` doesn't return JSON for both workspaces when run as the SP ([11 § Verification](./11-service-principal-fabric-git-setup.md#verification)). No later Part succeeds without it.

## Part D - Wire the workspaces to Git

**D1.** Fabric portal -> `Contoso-Sales-Dev` -> Workspace settings -> Git integration -> Azure DevOps -> your org / project / repo, branch `dev`, folder `fabric/` -> Connect and sync. Repeat for Prod with branch `prod`. The first binding is done by **your** user; the SP drives every sync after that.

**D2.** Each workspace should show `Contoso_Sales_LH`, `Contoso-Sales-WH`, `Contoso-Sales-Model` and `Contoso_Vars` (five variables, value sets `Dev` and `Prod`).

**D3.** Capture each workspace's Lakehouse ID, Warehouse ID and Warehouse SQL endpoint (Warehouse -> SQL connection string) into `demo-ids.local.json`.

> [!NOTE]
> `demo-ids.local.json` is a human reference. The pipeline never reads it; Part E copies the same values into ADO variable groups.

## Part E - Wire the pipeline

| Step | | Do | Detail |
|---|---|---|---|
| **E1** | <img src="./assets/icons/keys.svg" width="24" alt=""/> | Variable groups `contoso-fabric-env-dev` / `-prod` with `WORKSPACE_ID`, `LAKEHOUSE_ID`, `WAREHOUSE_ID`, `WAREHOUSE_SQL_ENDPOINT`, `ENVIRONMENT_LABEL`, `VALUE_SET` (+ optional `GIT_CONNECTION_ID`) | [10 § 1](./10-dynamic-env-injection.md#1-create-two-ado-variable-groups) |
| **E2** | <img src="./assets/icons/policy.svg" width="24" alt=""/> | Authorise both groups for the pipeline | [10 § 2](./10-dynamic-env-injection.md#2-authorise-the-variable-groups) |
| **E3** | <img src="./assets/icons/policy.svg" width="24" alt=""/> | ADO environments `fabric-dev` / `fabric-prod` (resource: None) + pipeline permission; optional approval on prod | [10 § 4](./10-dynamic-env-injection.md#4-create-the-ado-environments) |
| **E4** | <img src="./assets/icons/azure-devops.svg" width="24" alt=""/> | New pipeline -> existing YAML -> `.azuredevops/pipelines/deploy-workspace-per-branch.yml`; set `serviceConnection`; **Save**, don't run | [03 Phase 3](./03-deployment.md#phase-3---register-the-pipeline) |
| **E5** | <img src="./assets/icons/variable-library.svg" width="24" alt=""/> | Active value set: `Dev` in Dev, `Prod` in Prod (portal, or REST) | [10 § 5](./10-dynamic-env-injection.md#5-set-the-active-value-set-in-each-workspace) |

`VALUE_SET` must equal the variable library value-set name exactly.

## Part F - First run

```pwsh
git checkout dev
"# $(Get-Date -Format o)" | Out-File -Append .azuredevops/pipelines/first-run.trigger   # any file under a trigger path
git add . ; git commit -m "ci: first end-to-end run"
git push origin dev
git rm .azuredevops/pipelines/first-run.trigger ; git commit -m "ci: remove trigger file"   # push this later
```

Expect Stage 1 to print `Validated 4 Fabric items`, Stage 2 `synchronized to commit <sha>` (or `Already in sync`), Stage 3 the resolved item IDs and either `no-op` or `Updated definition`. Then verify the Dev model with the snippet in [04 - Testing](./04-testing.md#t4---the-model-points-at-the-right-environment).

## Part G - Promote to Prod

```pwsh
git checkout prod
git merge dev --ff-only     # or cherry-pick specific commits
git push origin prod
```

The same three stages run with `contoso-fabric-env-prod` against `Contoso-Sales-Prod`. A merge **is** the promotion - no deployment-pipeline rules, no rule templates.

## Parts H-J - Day 2, local runs, teardown

| Part | | Do | Where |
|---|---|---|---|
| **H** | <img src="./assets/icons/semantic-model.svg" width="24" alt=""/> | Add a column, table or variable | [09 - Semantic model changes](./09-semantic-model-deploy.md) |
| **I** | <img src="./assets/icons/dev-console.svg" width="24" alt=""/> | Run the validator and a `DRY_RUN=1` injection locally | [04 - Testing](./04-testing.md) |
| **J** | <img src="./assets/icons/alerts.svg" width="24" alt=""/> | Delete pipeline, groups, environments, service connection, workspaces, Fabric connection, app registration, capacity | below |

> [!CAUTION]
> Teardown order matters: delete the pipeline and service connection **before** the app registration, and the Fabric workspaces before the capacity. A paid F-SKU keeps billing until you pause or delete it; a trial expires on its own.

## Reproduction checklist

> [!TIP]
> Paste this checklist into the hand-over ticket for whoever does the next stand-up. If every box is ticked, the demo is reproduced.

- [ ] **A** capacity + `Contoso-Sales-Dev` / `Contoso-Sales-Prod` on it
- [ ] **B** repo imported, `prod` branch exists, parallelism granted
- [ ] **C** SP in Entra + ADO org; tenant settings on; SP Admin on both workspaces; service connection; Fabric ADO connection
- [ ] **D** both workspaces bound; four items each; IDs captured
- [ ] **E** variable groups, environments, pipeline registered, active value sets set
- [ ] **F** first `dev` push: three stages green; Dev IDs in the Dev model
- [ ] **G** first `prod` promotion: three stages green; Prod IDs in the Prod model

---

Next: [01 - Architecture](./01-architecture.md) →

*Last updated: 2026-10-07*
