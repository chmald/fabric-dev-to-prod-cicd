[README](../README.md) › [docs index](./00-reproduce-this-demo.md) › 07 CI/CD paths

# 07 - CI/CD paths and Lakehouse / Warehouse promotion

<p>
<img src="./assets/icons/git-branch-sync.svg" width="40" alt="Fabric Git integration"/>&nbsp;
<img src="./assets/icons/fabric.svg" width="40" alt="Deployment pipelines"/>&nbsp;
<img src="./assets/icons/dev-console.svg" width="40" alt="fabric-cicd"/>&nbsp;
<img src="./assets/icons/azure-devops.svg" width="40" alt="Azure DevOps"/>&nbsp;
<img src="./assets/icons/lakehouse.svg" width="40" alt="Lakehouse"/>&nbsp;
<img src="./assets/icons/warehouse.svg" width="40" alt="Warehouse"/>
</p>

![MS Learn Option 1](./assets/badges/learn-option1.svg) ![MS Learn Option 2](./assets/badges/learn-option2.svg) ![MS Learn Option 3](./assets/badges/learn-option3.svg) ![Default](./assets/badges/default.svg) ![Opt-in](./assets/badges/opt-in.svg) ![fabric-cicd 1.4.0](./assets/badges/fabric-cicd.svg)

There are three production-grade ways to promote Lakehouse, Warehouse and semantic-model objects between Fabric workspaces with Azure DevOps, and they map one-to-one to Microsoft Learn's [CI/CD workflow options in Fabric](https://learn.microsoft.com/en-us/fabric/cicd/manage-deployment). This repo ships **Path 2** live-tested and includes **Paths 1 and 3** as ready-to-adapt, static alternatives. This page compares them on the criteria that decide real projects and gives a recommendation per situation - it's the decision page to share with your team before a workshop.

## At a glance

| | Path | Learn option | In this repo | Status |
|---|---|---|---|---|
| <img src="./assets/icons/git-branch-sync.svg" width="24" alt=""/> | **2** - ADO YAML + Git, one branch per workspace | Option 1 - definition-based deployments using Git integration | `deploy-workspace-per-branch.yml` | <img src="./assets/badges/default.svg" alt="Default"/> <img src="./assets/badges/path2-live.svg" alt="Live-tested"/> |
| <img src="./assets/icons/fabric.svg" width="24" alt=""/> | **1** - ADO YAML -> deployment pipelines | Option 3 - deployment pipelines | `alternatives/deploy-via-deployment-pipeline.yml` | <img src="./assets/badges/opt-in.svg" alt="Opt-in"/> <img src="./assets/badges/static-only.svg" alt="Static only"/> |
| <img src="./assets/icons/dev-console.svg" width="24" alt=""/> | **3** - Python `fabric-cicd` | Option 2 - definition-based deployments using Fabric Items APIs | `alternatives/deploy-via-python-fabric-cicd.yml` + `scripts/deploy_fabric_cicd.py` + `fabric/parameter.yml` | <img src="./assets/badges/opt-in.svg" alt="Opt-in"/> <img src="./assets/badges/static-only.svg" alt="Static only"/> |

> [!NOTE]
> Microsoft's own framing: *"While this article outlines several distinct options, many organizations take a hybrid approach."* The paths aren't exclusive - most of the heavy lifting happens in Azure DevOps whichever you choose; Fabric receives the result. (Learn also defines **Option 4** for ISVs deploying one codebase to many customer workspaces.)

## Side by side

[![Three CI/CD paths](./assets/cicd-paths-comparison.png)](./assets/cicd-paths-comparison.png)

<sub>Editable source: [`assets/cicd-paths-comparison.drawio`](./assets/cicd-paths-comparison.drawio) - regenerate with `python scripts/export_diagrams.py docs/assets`.</sub>

## Decision matrix

| Criterion | Path 1: deployment pipelines | Path 2: Git branch per workspace | Path 3: `fabric-cicd` |
|---|---|---|---|
| **Fits a team already on deployment pipelines** | ✅ Least change | ⚠️ Needs branch-per-environment restructuring | ⚠️ New Python patterns |
| **Branching model** | One `main` | One branch per environment | Any; `test`/`prod` as deployment records in the tutorial |
| **Item coverage** | What deployment pipelines support | What Git integration supports | Widest - Items APIs + library dependency ordering |
| **SP-driven Warehouse promotion** | ❌ Failed in the originating build (`PrincipalTypeNotSupported`); SP deploys need every item to support SPs | ✅ Worked | ✅ Supported by the APIs |
| **Direct Lake on OneLake model** | ❌ No rules; needs a separate rewrite | ✅ Stage 3 | ✅ `parameter.yml` `find_replace` |
| **Per-environment values** | Variable library + deployment rules | Variable groups -> Stage 3 | `parameter.yml` tokens; Key Vault / env vars |
| **PR-driven workflow** | Less natural - push to `main` = deploy | Natural - the merge is the promotion | Decoupled - any trigger |
| **Audit + rollback** | ADO history + deployment history | Git history + Fabric sync log | Git history + your own logging |
| **Code you own** | YAML only | YAML + two small scripts | YAML + a Python deploy script, pinned library |
| **Recommendation** | **When** the team is on deployment pipelines today and has no Direct Lake on OneLake models | **Default** for new ADO + Fabric CI/CD, Direct Lake models, SP-only automation | **When** you need code-first control, fan-out to many workspaces, or items the others miss |

> [!WARNING]
> Deployment pipelines dropped support for semantic models without enhanced metadata from 2026-02-12. Models stored as TMDL (as here) are fine; legacy-format models must be upgraded before Path 1 can deploy them. See [Fabric CI/CD troubleshooting](https://learn.microsoft.com/en-us/fabric/cicd/troubleshoot-cicd).

## Path 2 - the shipped path

Each workspace is bound to one branch; a merge is the promotion; the pipeline adds what plain Git integration lacks.

| Stage | | Adds |
|---|---|---|
| **1 Validate** | <img src="./assets/icons/code.svg" width="20" alt=""/> | Structure checks on every PR before Fabric sees the commit |
| **2 SyncFabricFromBranch** | <img src="./assets/icons/git-branch-sync.svg" width="20" alt=""/> | Immediate, observable `updateFromGit` instead of waiting for someone to click **Update all** |
| **3 InjectEnvValues** | <img src="./assets/icons/variable-library.svg" width="20" alt=""/> | Per-environment IDs into the value set and the Direct Lake model |

Why it's the default: no SP-Warehouse gap, branches map cleanly to environments, promotion is a reviewable PR, Git integration covers every item type the repo ships, and environment values never live in Git. Setup: [03 - Deployment](./03-deployment.md).

## Path 1 - deployment pipelines

`alternatives/deploy-via-deployment-pipeline.yml` validates, then calls `POST /v1/deploymentPipelines/{id}/deploy` with `sourceStageId`, `targetStageId` and an explicit item list, and polls the operation ([Deploy stage content](https://learn.microsoft.com/en-us/rest/api/fabric/core/deployment-pipelines/deploy-stage-content)). It deploys **Lakehouse + VariableLibrary only**, because a service principal can deploy only when every item in the request supports service principals, and Warehouse returned `PrincipalTypeNotSupported` in the originating build.

<details><summary><b>Show how to adopt Path 1</b></summary>

1. Create a deployment pipeline; assign `Contoso-Sales-Dev` and `Contoso-Sales-Prod` to its stages.
2. Make the SP an admin of the deployment pipeline and Contributor (or higher) on both workspaces; enable *Service principals can create workspaces, connections, and deployment pipelines* only if the SP must create the pipeline itself.
3. Create variable group `contoso-fabric-dp` with `DEPLOYMENT_PIPELINE_ID`, `SOURCE_STAGE_ID`, `TARGET_STAGE_ID`, `DP_LAKEHOUSE_ID`, `DP_VARIABLE_LIBRARY_ID`.
4. Register the YAML, set `serviceConnection`, and add a `trigger:` on `main` when you're ready.
5. Keep Path 2's Stage 3 (or Path 3's `parameter.yml`) for the Direct Lake model and the Warehouse.

</details>

## Path 3 - `fabric-cicd`

`alternatives/deploy-via-python-fabric-cicd.yml` follows the [Microsoft tutorial](https://learn.microsoft.com/en-us/fabric/cicd/tutorial-fabric-cicd-azure-devops): only the Dev workspace is Git-connected, `test` and `prod` branches are deployment records, and a merge into either runs `scripts/deploy_fabric_cicd.py --target_env <env>`. The script resolves the workspace by display name (`FABRIC_WORKSPACE_PREFIX`-`<Env>`), builds a `FabricWorkspace`, and runs `publish_all_items()` then `unpublish_all_orphan_items()`. `fabric/parameter.yml` swaps the model's placeholder GUIDs for `$workspace.$id` and `$items.<Type>.<Name>.$id` at deploy time ([parameterization](https://microsoft.github.io/fabric-cicd/latest/how_to/parameterization/)).

| Tutorial section | This repo |
|---|---|
| §4.1-4.3 Key Vault + two variable groups | `fabric_cicd_group_sensitive`, `fabric_cicd_group_non_sensitive` in the YAML |
| §4.4 Environments + approvals | `fabric-test`, `fabric-prod` |
| §6.2 Workspace lookup by name | `find_workspace_id_by_name()` |
| §6.5 Authentication | `get_credential()`: client secret from env, else `DefaultAzureCredential` |
| §6.7 Publish | `deploy_with_library()` |
| §7 Parameter file | `fabric/parameter.yml` (root of `repository_directory`) |

> [!TIP]
> `--mode rest` in the same script lists items and calls `git/updateFromGit` directly - a compact teaching example of the REST calls Path 2's Stage 2 makes. Use `--dry-run` in a workshop to show resolution without changing anything.

> [!CAUTION]
> Pin `fabric-cicd` (`scripts/requirements-fabric-cicd.txt`, currently 1.4.0) and re-run the Path 3 checks in [04](./04-testing.md) after every upgrade. The library moves quickly and parameterization behaviour has changed between releases.

## Recommended combinations

| Situation | | Use |
|---|---|---|
| New ADO + Fabric CI/CD, Direct Lake models | <img src="./assets/icons/git-branch-sync.svg" width="20" alt=""/> | Path 2 |
| Already on deployment pipelines, reports and dataflows only | <img src="./assets/icons/fabric.svg" width="20" alt=""/> | Path 1 |
| Already on deployment pipelines **and** Direct Lake models | <img src="./assets/icons/fabric.svg" width="20" alt=""/> | Path 1 for reports + Path 2 Stage 3 (or Path 3) for the model and Warehouse |
| Many workspaces from one codebase | <img src="./assets/icons/dev-console.svg" width="20" alt=""/> | Path 3 in a loop (Learn Option 4 for ISVs) |
| Tenant won't allow SP API access yet | <img src="./assets/icons/users.svg" width="20" alt=""/> | [03b - Manual](./03b-manual-deployment.md) until it does |

## References

| Reference | Topic |
|---|---|
| [CI/CD workflow options in Fabric](https://learn.microsoft.com/en-us/fabric/cicd/manage-deployment) | Options 1-4, hybrid approach |
| [Git integration process](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-integration-process) | Path 2 mechanics |
| [Deployment pipelines overview](https://learn.microsoft.com/en-us/fabric/cicd/deployment-pipelines/intro-to-deployment-pipelines) | Path 1 mechanics |
| [fabric-cicd docs](https://microsoft.github.io/fabric-cicd/latest/) | Path 3 library |
| [Warehouse source control](https://learn.microsoft.com/en-us/fabric/data-warehouse/source-control) | Warehouse items in Git |

---

Next: [08 - ADO bridge guidance](./08-ado-bridge-guidance.md) →

*Last updated: 2026-10-07*
