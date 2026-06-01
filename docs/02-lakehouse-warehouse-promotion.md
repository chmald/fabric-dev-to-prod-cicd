# 02 — Lakehouse / Warehouse object promotion

> **Scope.** This repo implements **one** Fabric CI/CD path end-to-end: **ADO YAML + Fabric Git, one branch per workspace** (Microsoft Learn [Option 1](https://learn.microsoft.com/en-us/fabric/cicd/manage-deployment)). Everything below describes that path. Alternative paths (Fabric Deployment Pipelines, `microsoft/fabric-cicd` Python SDK) are summarised at the bottom for context only — they are **not** implemented here.

> **The problem Contoso hit.** Fabric **Deployment Pipelines** are good for some object types (semantic models, reports, dataflows) but have known gaps for Warehouse views / sprocs, Lakehouse table structures, and — critically — Service Principal–driven Warehouse promotion (`PrincipalTypeNotSupported`). Contoso's team needs a single mechanism that covers every Fabric item type they own, drives end-to-end from ADO under a service principal, and supports PR-driven governance.

## The path this repo implements

```
                            ┌──────────────────┐
                            │ ADO Repo         │
                            │ contoso-fabric-cicd │
                            └─┬─────────┬──────┘
        Fabric Git (bound)    │         │     Fabric Git (bound)
                              ▼         ▼
                     ┌──────────────┐ ┌──────────────┐
                     │  dev branch  │ │  prod branch │
                     └──────┬───────┘ └──────┬───────┘
                            │                │
                       updateFromGit    updateFromGit
                       (REST, SP)       (REST, SP)
                            │                │
                            ▼                ▼
                     ┌──────────────┐ ┌──────────────┐
                     │ Dev Workspace│ │Prod Workspace│
                     └──────────────┘ └──────────────┘
                            │                │
                            ▼                ▼
                   inject_env_values.py  inject_env_values.py
                   (Stage 3 — REST)      (Stage 3 — REST)
```

### How it works

1. **Each workspace is bound to one branch** via Fabric Git integration: `Contoso-Sales-Dev` ↔ `dev`, `Contoso-Sales-Prod` ↔ `prod`. The portal binding is a one-time setup (see [00 §D1](00-reproduce-this-demo.md)).
2. **Promotion = git merge.** `git checkout prod; git merge dev; git push origin prod` is the entire promotion mechanism. No Deployment Pipeline rules, no rule-template export.
3. **The ADO pipeline adds three things** plain Git integration doesn't:
   - **Stage 1 · Validate** — `scripts/validate_fabric_items.py` runs schema + TMDL + manifest checks before any Fabric call.
   - **Stage 2 · SyncFabricFromBranch** — `POST /workspaces/{wsId}/git/updateFromGit` so the workspace catches up the instant the push lands (instead of waiting on Fabric's background sync interval).
   - **Stage 3 · InjectEnvValues** — `scripts/inject_env_values.py` overwrites the workspace's per-environment values (Variable Library value set + SemanticModel M parameters) from the matching ADO variable group, solving the Direct Lake parameter problem (see [docs/01](01-direct-lake-variables.md)).

### Why this path for Contoso

| Property | Why it matters |
|---|---|
| **No SP-Warehouse limitation** | `updateFromGit` works under SP creds for every item type Fabric Git integration supports — Warehouse, Lakehouse, SemanticModel, VariableLibrary, Notebooks, Pipelines. |
| **Branches = environments mental model** | Natural for PR-driven governance. `prod` can carry branch policies (required reviewers, build validation). |
| **Lower-touch promotion** | A merge IS the deploy. No Deployment Pipeline stage management, no rules UI to keep in sync. |
| **One mechanism for all item types** | Fabric Git integration's coverage is broader than Deployment Pipelines and avoids the SP gaps. |
| **Environment values stay out of git** | Stage 3 owns per-env IDs via ADO variable groups (Key Vault-backable). Git holds structure + scaffolding only. |

### Files

| File | Role |
|---|---|
| `.azuredevops/pipelines/deploy-workspace-per-branch.yml` | The pipeline (Validate → Sync → Inject) |
| `scripts/validate_fabric_items.py` | Stage 1 pre-deploy validator |
| `scripts/inject_env_values.py` | Stage 3 per-workspace value injector |
| `fabric/` | Fabric items (Lakehouse, Warehouse, SemanticModel, VariableLibrary) — Git-integrated |
| [docs/00](00-reproduce-this-demo.md) | End-to-end stand-up guide |
| [docs/06](06-dynamic-env-injection.md) | Full runbook for Stage 3 (variable groups + REST injection) |
| [docs/07](07-service-principal-fabric-git-setup.md) | One-time SP onboarding for SP-driven `updateFromGit` |

---

## Alternative paths (not implemented here)

Microsoft Learn's [Choose the best Fabric CI/CD workflow option for you](https://learn.microsoft.com/en-us/fabric/cicd/manage-deployment) defines several options. This repo deliberately ships only the one above. The others, in brief:

- **Fabric Deployment Pipelines (MS Option 3).** Single `main` branch; Fabric DP promotes between stages via `POST /v1/deploymentPipelines/{id}/deploy`. ⚠ Hits `PrincipalTypeNotSupported` for SP-driven Warehouse promotion today, and the DP rules UI is greyed out for Direct Lake on OneLake — both of which are blockers for Contoso.
- **`microsoft/fabric-cicd` Python SDK / pure REST (MS Option 2).** Code-first; the SDK (`FabricWorkspace.publish_all_items`) or the Bulk-Import-Item-Definitions API uploads items directly. Useful for multi-tenant fan-out or item types Git integration doesn't yet cover. Adds a Python codebase to maintain — not warranted for Contoso's two-workspace footprint.

If a future requirement (e.g. multi-customer-tenant fan-out) pushes Contoso toward one of these, the variable-group + injection pattern from [docs/06](06-dynamic-env-injection.md) carries over unchanged — only the orchestration mechanism changes.

---

## Reference links

### Start here
- **[Tutorial: Fabric CI/CD with Azure DevOps](https://learn.microsoft.com/en-us/fabric/cicd/tutorial-fabric-cicd-azure-devops)** — Microsoft's canonical end-to-end tutorial.
- [Choose the best Fabric CI/CD workflow option for you](https://learn.microsoft.com/en-us/fabric/cicd/manage-deployment) — the option matrix this doc maps to.
- [Fabric CI/CD best practices](https://learn.microsoft.com/en-us/fabric/cicd/best-practices-cicd)

### Path specifics (the implemented path)
- [Git integration intro](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/intro-to-git-integration)
- [Git integration process](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-integration-process)
- [Git automation (REST)](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-automation)
- [Source code format per item type](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/source-code-format)
- [Conflict resolution](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/conflict-resolution)
- [Manage branches](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/manage-branches)

### Item-specific source control
- [Warehouse source control](https://learn.microsoft.com/en-us/fabric/data-warehouse/source-control)
- [Variable Library overview (GA)](https://learn.microsoft.com/en-us/fabric/cicd/variable-library/variable-library-overview)

### Tenant admin (gotchas to flag with Contoso IT)
- [Git integration admin settings](https://learn.microsoft.com/en-us/fabric/admin/git-integration-admin-settings)
