[README](../README.md) › [docs index](./00-reproduce-this-demo.md) › 01 Architecture

# 01 - Architecture

<p>
<img src="./assets/icons/fabric.svg" width="40" alt="Microsoft Fabric"/>&nbsp;
<img src="./assets/icons/git-branch-sync.svg" width="40" alt="Fabric Git integration"/>&nbsp;
<img src="./assets/icons/azure-devops.svg" width="40" alt="Azure DevOps"/>&nbsp;
<img src="./assets/icons/semantic-model.svg" width="40" alt="Semantic model"/>&nbsp;
<img src="./assets/icons/variable-library.svg" width="40" alt="Variable library"/>&nbsp;
<img src="./assets/icons/entra-workload-id.svg" width="40" alt="Microsoft Entra Workload ID"/>
</p>

![GA](./assets/badges/ga.svg) ![Default](./assets/badges/default.svg) ![MS Learn Option 1](./assets/badges/learn-option1.svg) ![Path 2 live-tested](./assets/badges/path2-live.svg)

The reference architecture for promoting Fabric items with Azure DevOps: two workspaces, each bound to its own Git branch, and one ADO YAML pipeline that validates, syncs and injects per-environment values. This page explains every layer, the request path, the trust boundaries, the locked decisions and why they were made, and how to point the pattern at a different workload. It maps to Microsoft Learn's **Option 1 - definition-based deployments using Git integration** in [CI/CD workflow options in Fabric](https://learn.microsoft.com/en-us/fabric/cicd/manage-deployment).

## At a glance

| | Question | Answer |
|---|---|---|
| <img src="./assets/icons/fabric-workspace.svg" width="24" alt=""/> | What is an environment? | A Fabric workspace bound to one branch: `Contoso-Sales-Dev` <-> `dev`, `Contoso-Sales-Prod` <-> `prod`. |
| <img src="./assets/icons/commit.svg" width="24" alt=""/> | What is a promotion? | `git merge dev -> prod`. The pipeline then pulls `prod` into the Prod workspace. |
| <img src="./assets/icons/keys.svg" width="24" alt=""/> | Where do per-environment IDs live? | ADO variable groups (Key Vault-linkable). Git holds scaffolding values only. |
| <img src="./assets/icons/semantic-model.svg" width="24" alt=""/> | How does the Direct Lake model follow each environment? | Stage 3 rewrites its M parameters through Fabric REST after every sync. |
| <img src="./assets/icons/entra-workload-id.svg" width="24" alt=""/> | Who calls Fabric? | A service principal through an ADO service connection with workload identity federation. |

## Reference architecture

[![Reference architecture](./assets/fabric-cicd-ado-integration-architecture.png)](./assets/fabric-cicd-ado-integration-architecture.png)

<sub>Editable source: [`assets/fabric-cicd-ado-integration-architecture.drawio`](./assets/fabric-cicd-ado-integration-architecture.drawio) - regenerate with `python scripts/export_diagrams.py docs/assets`.</sub>

| Tier | Component | Role |
|---|---|---|
| Author | <img src="./assets/icons/code.svg" width="20" alt=""/> VS Code / Fabric portal | Edit items; commit to `dev` from the Source control pane or `git push`. |
| Source | <img src="./assets/icons/commit.svg" width="20" alt=""/> Azure Repos | `dev` + `prod` branches; items under `fabric/`; branch policy on `prod`. |
| Orchestration | <img src="./assets/icons/azure-devops.svg" width="20" alt=""/> Azure Pipelines | `deploy-workspace-per-branch.yml`: Validate -> SyncFabricFromBranch -> InjectEnvValues. |
| Configuration | <img src="./assets/icons/keys.svg" width="20" alt=""/> Library variable groups | `contoso-fabric-env-dev` / `-prod`: IDs, SQL endpoint, label, value-set name. |
| Governance | <img src="./assets/icons/policy.svg" width="20" alt=""/> ADO environments | `fabric-dev` / `fabric-prod`; optional approval check on prod. |
| Identity | <img src="./assets/icons/app-registrations.svg" width="20" alt=""/> Service principal | Workspace Admin; ADO org user; owns its Fabric ADO connection. |
| Identity | <img src="./assets/icons/entra-workload-id.svg" width="20" alt=""/> Service connection | Workload identity federation - no stored client secret. |
| Platform | <img src="./assets/icons/git-branch-sync.svg" width="20" alt=""/> Fabric Git integration | Workspace <-> branch binding; `git/status`, `updateFromGit`. |
| Platform | <img src="./assets/icons/fabric.svg" width="20" alt=""/> Fabric capacity | F2+ or trial; hosts both workspaces. |
| Data | <img src="./assets/icons/lakehouse.svg" width="20" alt=""/> Lakehouse, <img src="./assets/icons/warehouse.svg" width="20" alt=""/> Warehouse | Bronze/silver and gold. |
| Semantic | <img src="./assets/icons/semantic-model.svg" width="20" alt=""/> Semantic model | Direct Lake on OneLake over the warehouse; M parameters injected. |
| Semantic | <img src="./assets/icons/variable-library.svg" width="20" alt=""/> Variable library | `environmentLabel` and IDs for notebooks / pipelines; value sets Dev / Prod. |
| Consumers | <img src="./assets/icons/power-bi.svg" width="20" alt=""/> Power BI reports | Read the environment-correct model. |

## Request path

| Step | | What happens | Fabric REST |
|---|---|---|---|
| **1** | <img src="./assets/icons/commit.svg" width="24" alt=""/> | Developer pushes to `dev` (or merges to `prod`) | - |
| **2** | <img src="./assets/icons/azure-devops.svg" width="24" alt=""/> | CI trigger fires; PRs run Stage 1 only | - |
| **3** | <img src="./assets/icons/code.svg" width="24" alt=""/> | Stage 1 validates `.platform`, variable library JSON, TMDL, M parameters - no Fabric calls | - |
| **4** | <img src="./assets/icons/git-branch-sync.svg" width="24" alt=""/> | Stage 2 binds `myGitCredentials` (if `GIT_CONNECTION_ID` is set), reads status, pulls the branch, polls the LRO | `PATCH git/myGitCredentials`, `GET git/status`, `POST git/updateFromGit`, `GET operations/{id}` |
| **5** | <img src="./assets/icons/variable-library.svg" width="24" alt=""/> | Stage 3 rewrites the value set and the model's M parameters, skipping identical definitions, then verifies | `POST items/{id}/getDefinition` + `updateDefinition`, `POST semanticModels/{id}/getDefinition?format=TMDL` + `updateDefinition` |
| **6** | <img src="./assets/icons/power-bi.svg" width="24" alt=""/> | Reports read the environment's own warehouse via Direct Lake | - |

The pipeline walk-through below expands each stage. Stage 3 internals are in [10 - Dynamic env injection](./10-dynamic-env-injection.md).

## Pipeline walk-through

[![Pipeline deployment flow](./assets/pipeline-deployment-flow.png)](./assets/pipeline-deployment-flow.png)

<sub>Editable source: [`assets/pipeline-deployment-flow.drawio`](./assets/pipeline-deployment-flow.drawio).</sub>

**Trigger and scope.** Pushes to `dev` or `prod` that touch `fabric/*`, `scripts/*` or `.azuredevops/pipelines/*` run all three stages. A `pr:` trigger runs Stage 1 for PRs into either branch; Stages 2 and 3 carry `condition: ... in(variables['Build.SourceBranch'], 'refs/heads/dev', 'refs/heads/prod')`. ([CI triggers](https://learn.microsoft.com/en-us/azure/devops/pipelines/repos/azure-repos-git?tabs=yaml#ci-triggers))

**Variable group selection at compile time.** `${{ if eq(variables['Build.SourceBranchName'], 'dev') }}: - group: contoso-fabric-env-dev` is a template expression, resolved before the run because group authorisation is resolved at compile time. ([Template expressions](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/template-expressions))

**Authentication.** Stages 2 and 3 use `AzureCLI@2` with the `fabric-cicd-sp` service connection and acquire a Fabric token **inside** each task (`az account get-access-token --resource https://api.fabric.microsoft.com`) rather than passing one across tasks. ([Workload identity federation](https://learn.microsoft.com/en-us/azure/devops/pipelines/library/connect-to-azure))

| Stage | | Runs on | Purpose | Fails the run when |
|---|---|---|---|---|
| **1 Validate** | <img src="./assets/icons/code.svg" width="20" alt=""/> | PR + push | Structure checks; changed-item diff | `.platform` / JSON / TMDL broken; an injected M parameter missing or duplicated |
| **2 SyncFabricFromBranch** | <img src="./assets/icons/git-branch-sync.svg" width="20" alt=""/> | push | Make the workspace observably equal to branch HEAD before Stage 3 (`PreferRemote`) | Any non-`Succeeded` LRO |
| **3 InjectEnvValues** | <img src="./assets/icons/variable-library.svg" width="20" alt=""/> | push | Write the environment's IDs into the value set and model; verify | Zero or several items named `Contoso_Vars` / `Contoso-Sales-Model`; verification mismatch |

<details><summary><b>Show the end-to-end stage sketch</b></summary>

```
push to dev (or prod)
  Stage 1  Validate               checkout (depth 2) -> Python 3.11 -> validate_fabric_items.py -> changed_items.txt
  Stage 2  SyncFabricFromBranch   PATCH myGitCredentials (if GIT_CONNECTION_ID) -> GET git/status
                                  -> POST git/updateFromGit (PreferRemote) -> poll GET operations/{id}
  Stage 3  InjectEnvValues        pip install requests -> az token -> inject_env_values.py
                                  -> VarLib value set + model M params -> verify
=> workspace reflects the variable group, not whatever was committed
```

</details>

> [!NOTE]
> Fabric Git integration also syncs on its own, but only when someone clicks **Update all** or on a background cadence. Calling `updateFromGit` from the pipeline makes the sync observable, bounded and ordered before Stage 3. ([Git automation](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-automation))

## Trust boundaries

| Boundary | Component | Crossed by | Control |
|---|---|---|---|
| ADO -> Entra | <img src="./assets/icons/entra-workload-id.svg" width="20" alt=""/> Service connection | Federated token exchange | No secret stored; scoped to the project's pipelines |
| ADO -> Fabric | <img src="./assets/icons/fabric.svg" width="20" alt=""/> Fabric REST | SP bearer token | Tenant setting scoped to the SP's security group; workspace role |
| Fabric -> ADO | <img src="./assets/icons/git-branch-sync.svg" width="20" alt=""/> Fabric ADO connection | `updateFromGit` clone | SP is an ADO org user with repo Read; `myGitCredentials` per workspace |
| Humans -> Prod | <img src="./assets/icons/policy.svg" width="20" alt=""/> Branch policy + environment check | Merge to `prod` | Required reviewer; optional approval on `fabric-prod` |
| Secrets -> pipeline | <img src="./assets/icons/key-vault.svg" width="20" alt=""/> Key Vault-linked group | Variable read | Values masked; never echoed |

> [!WARNING]
> `PreferRemote` makes the branch the truth: uncommitted edits in a workspace are overwritten on the next sync. Treat Prod as read-only for humans - fix in `dev` and promote.

## Locked decisions

| Decision | Rationale | Alternative rejected |
|---|---|---|
| One branch per workspace | Promotion is a reviewable merge; works for every item Git integration supports under an SP | Single `main` + deployment pipelines (SP + Warehouse gaps; no Direct Lake rules) |
| Per-environment IDs in variable groups | Same Git content on both branches; Key Vault-backable; no drift | IDs committed per branch (merge conflicts, drift) |
| Stage 3 rewrites model M parameters | Deployment rules are unavailable for Direct Lake on OneLake, and semantic models can't consume variable-library values | Manual parameter edits after each promotion |
| Compare decoded bytes before `updateDefinition` | Fabric doesn't promise a no-op on identical input; avoids version churn | Always write |
| Token acquired inside each task | Tokens expire; `AzureCLI@2` owns the login context | Pass a token across stages |
| Two long-lived branches | Enough for change control; add `qa` only with a real reason | Branch per developer as environments |

## Best practices and guardrails

| | Practice | How this repo applies it |
|---|---|---|
| <img src="./assets/icons/commit.svg" width="20" alt=""/> | Merge direction is always `dev -> prod` | Hot-fixes on `prod` are cherry-picked back to `dev` at once |
| <img src="./assets/icons/keys.svg" width="20" alt=""/> | No environment values in Git | Committed IDs are placeholders; the validator checks names, not values |
| <img src="./assets/icons/key-vault.svg" width="20" alt=""/> | Secrets out of YAML | WIF service connection; Key Vault-linked groups for anything sensitive |
| <img src="./assets/icons/policy.svg" width="20" alt=""/> | Boring, repeatable deploys | Identical three stages on every push; approval only where needed |
| <img src="./assets/icons/alerts.svg" width="20" alt=""/> | Rollback | Revert the commit on `prod` and push; the same stages restore the previous state |
| <img src="./assets/icons/fabric-workspace.svg" width="20" alt=""/> | Naming | Workspaces `<App>-<Tier>`; groups `contoso-fabric-env-<tier>`; environments `fabric-<tier>` |

## Pitfalls and constraints

- **Direct Lake parameters.** Deployment-pipeline rules can't swap a Direct Lake on OneLake model's source; Stage 3 does. Mechanism: [06](./06-direct-lake-variables.md), [10](./10-dynamic-env-injection.md).
- **Service principal prerequisites.** Tenant setting *Service principals can call Fabric public APIs*, a workspace role, an ADO org seat and a Fabric ADO connection bound as `myGitCredentials`. Learn lists **Contributor** as the minimum role for `updateFromGit`; this demo grants **Admin**, which is what the originating build validated and what connecting a workspace to Git requires. Runbook: [11](./11-service-principal-fabric-git-setup.md).
- **One branch per workspace.** A workspace binds to one branch at a time; developers who need isolation use *branch out* to a personal workspace.
- **Active value set.** It's a per-workspace setting. Set it once in the portal, or with `PATCH /v1/workspaces/{id}/variableLibraries/{id}` and `properties.activeValueSetName` ([Update Variable Library](https://learn.microsoft.com/en-us/rest/api/fabric/variablelibrary/items/update-variable-library)). Stage 3 keeps the **contents** current, not the selection.

> [!CAUTION]
> Don't add `{{Contoso_Vars.x}}` placeholders to `expressions.tmdl`. Semantic models aren't a supported variable-library consumer ([supported items](https://learn.microsoft.com/en-us/fabric/cicd/variable-library/variable-library-overview)); use the M-parameter pattern this repo ships.

## Options compared

[![Three CI/CD paths](./assets/cicd-paths-comparison.png)](./assets/cicd-paths-comparison.png)

<sub>Editable source: [`assets/cicd-paths-comparison.drawio`](./assets/cicd-paths-comparison.drawio). Full matrix and recommendation: [07 - CI/CD paths](./07-cicd-paths-and-promotion.md).</sub>

| Option | Learn name | In this repo | Status |
|---|---|---|---|
| Path 2 | Option 1 - definition-based deployments using Git integration | `deploy-workspace-per-branch.yml` | <img src="./assets/badges/default.svg" alt="Default"/> <img src="./assets/badges/path2-live.svg" alt="Live-tested"/> |
| Path 1 | Option 3 - deployment pipelines | `alternatives/deploy-via-deployment-pipeline.yml` | <img src="./assets/badges/opt-in.svg" alt="Opt-in"/> <img src="./assets/badges/static-only.svg" alt="Static only"/> |
| Path 3 | Option 2 - definition-based deployments using Fabric Items APIs | `alternatives/deploy-via-python-fabric-cicd.yml` + `deploy_fabric_cicd.py` | <img src="./assets/badges/opt-in.svg" alt="Opt-in"/> <img src="./assets/badges/static-only.svg" alt="Static only"/> |

## Adapting this pattern to another workload

Retargeting is a configuration change. The **`workload` block in [`demo-ids.template.json`](../demo-ids.template.json)** is the only domain-specific surface; [13 - Configuration reference](./13-configuration-reference.md) lists every knob.

| Field | Change it to | Also update |
|---|---|---|
| `workspacePrefix` | e.g. `Fabrikam-Finance` | Workspace names in Fabric; `FABRIC_WORKSPACE_PREFIX` for Path 3 |
| `environments` | add `qa` if needed | Branch lists in the YAML `trigger` / `pr` / `condition` |
| `variableGroupPrefix` | e.g. `fabrikam-fabric-env-` | The `- group:` lines in the YAML |
| `adoEnvironmentPrefix`, `serviceConnection` | your names | `environment:` and `serviceConnection` in the YAML |
| `items.*` | your item display names | Folder names + `.platform` `displayName` under `fabric/`; `VARIABLE_LIBRARY_NAME` / `SEMANTIC_MODEL_NAME` in the groups; `fabric/parameter.yml` |

**What stays fixed:** the three-stage shape, the variable names the scripts read (`WORKSPACE_ID`, `VALUE_SET`, ...), the M parameter names `WorkspaceId` / `LakehouseId` / `WarehouseId`, and the idempotent compare-then-write logic. **Add domain fields** only when a new environment-specific value appears - add it to the variable library, both value sets, the variable groups and the injector's `overrides` map together ([09](./09-semantic-model-deploy.md)). `tests/test_reusability_guards.py` fails if the block and the code drift apart.

## References

| Reference | Topic |
|---|---|
| [Tutorial: Fabric CI/CD with Azure DevOps](https://learn.microsoft.com/en-us/fabric/cicd/tutorial-fabric-cicd-azure-devops) | Microsoft's end-to-end walkthrough (Option 2) |
| [CI/CD workflow options in Fabric](https://learn.microsoft.com/en-us/fabric/cicd/manage-deployment) | Options 1-4 and the hybrid approach |
| [Git integration process](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-integration-process) | Sync semantics |
| [Git - Update From Git](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/update-from-git) | Stage 2 request body and roles |
| [Items - Update Item Definition](https://learn.microsoft.com/en-us/rest/api/fabric/core/items/update-item-definition) | Stage 3 writes |
| [Variable library overview](https://learn.microsoft.com/en-us/fabric/cicd/variable-library/variable-library-overview) | Value sets and supported consumers |
| [Git integration tenant settings](https://learn.microsoft.com/en-us/fabric/admin/git-integration-admin-settings) | Admin prerequisites |

---

Next: [02 - Prerequisites](./02-prerequisites.md) →

*Last updated: 2026-10-07*
