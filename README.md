# Contoso Sales Fabric CI/CD Demo

> Companion repo for the **Azure DevOps + Microsoft Fabric CI/CD workshop**.

This repo demonstrates the **one-branch-per-workspace** Fabric CI/CD pattern,
hardened around a single Direct Lake on OneLake semantic model and a small
Warehouse + Lakehouse + Variable Library item set.

Per-environment values (workspace ID, lakehouse ID, warehouse ID, SQL endpoint,
environment label) live in **Azure DevOps variable groups** — not in git — and
get injected into the synced Fabric workspace via the Fabric REST API after
every push. This solves the known limitation that Direct Lake on OneLake
semantic models can't use Deployment Pipeline rules to swap workspace/lakehouse
IDs — the rules UI is greyed out for this model type, so promoting from Dev to
Prod would otherwise leave the model pointing at Dev data.

| | |
|---|---|
| **Mechanism** | ADO YAML + Fabric REST API for Git integration (no Fabric Deployment Pipelines) |
| **Active pipeline** | `.azuredevops/pipelines/deploy-workspace-per-branch.yml` |
| **MS Learn option** | Option 1 — branch-per-workspace (with REST-driven `updateFromGit` and per-workspace env value injection) |
| **Branches → workspaces** | `dev` ↔ `Contoso-Sales-Dev`, `prod` ↔ `Contoso-Sales-Prod` |
| **Per-environment values** | ADO variable groups `contoso-fabric-env-dev` / `contoso-fabric-env-prod` |
| **In-git scaffolding** | `fabric/Contoso-Sales-Model.SemanticModel/definition/expressions.tmdl` (M parameters) + `fabric/Contoso_Vars.VariableLibrary/valueSets/*.json` |

> **Canonical Microsoft references**
> · [Tutorial: Fabric CI/CD with Azure DevOps](https://learn.microsoft.com/en-us/fabric/cicd/tutorial-fabric-cicd-azure-devops)
> · [Choose the best Fabric CI/CD workflow option for you](https://learn.microsoft.com/en-us/fabric/cicd/manage-deployment)
> · [Variable Library overview (GA)](https://learn.microsoft.com/en-us/fabric/cicd/variable-library/variable-library-overview)

> **Reproducing this demo from scratch?** Start with [docs/00-reproduce-this-demo.md](docs/00-reproduce-this-demo.md) — end-to-end stand-up guide (Parts A–J + single-page checklist) that orchestrates the deeper runbooks in `docs/06` and `docs/07`.

## Repository layout

```
fabric-cicd-ado-integration/
├── .azuredevops/
│   └── pipelines/
│       └── deploy-workspace-per-branch.yml   ← 3-stage pipeline: Validate → Sync → Inject
├── fabric/                                   ← Fabric items materialised via Git integration
│   ├── Contoso_Sales_LH.Lakehouse/              ← bronze + silver Delta tables
│   ├── Contoso-Sales-WH.Warehouse/              ← gold views + sprocs (+ test table1)
│   ├── Contoso-Sales-Model.SemanticModel/       ← Direct Lake on OneLake — M params overwritten per workspace by Stage 3
│   └── Contoso_Vars.VariableLibrary/            ← env value sets — overwritten per workspace by Stage 3
├── scripts/
│   ├── validate_fabric_items.py              ← Pre-deploy validator (Stage 1)
│   ├── inject_env_values.py                  ← Per-workspace value injection (Stage 3)
│   └── requirements.txt
├── data/sales_orders_sample.csv              ← demo data — small synthetic ERP extract
├── docs/
│   ├── 00-reproduce-this-demo.md             ← **Start here** — end-to-end stand-up guide (Parts A–J + checklist)
│   ├── 01-direct-lake-variables.md           ← Direct Lake + Variable Library pattern
│   ├── 02-lakehouse-warehouse-promotion.md   ← Lakehouse/Warehouse promotion comparison
│   ├── 03-ado-bridge-guidance.md             ← Bridging existing ADO to Fabric CI/CD
│   ├── 04-architecture-best-practices.md     ← Architecture reference
│   ├── 05-semantic-model-deploy.md           ← How to deploy / change the SemanticModel
│   ├── 06-dynamic-env-injection.md           ← ADO variable groups + Fabric REST injection runbook
│   └── 07-service-principal-fabric-git-setup.md ← One-time SP onboarding for Fabric ADO Git integration
├── demo-ids.json                             ← Reference snapshot of workspace + item IDs (NOT read at pipeline runtime)
└── README.md
```

## Demo environment

| Resource | Value |
|---|---|
| Tenant | `00000000-0000-0000-0000-000000000000` (contoso.onmicrosoft.com) |
| Subscription | `00000000-0000-0000-0000-000000000000` (<your-subscription>) |
| Fabric capacity | Trial capacity (60-day) |
| Dev workspace | `Contoso-Sales-Dev` (id `11111111-…`) ↔ branch `dev` |
| Prod workspace | `Contoso-Sales-Prod` (id `22222222-…`) ↔ branch `prod` |
| ADO project | https://dev.azure.com/<your-org>/<your-project> |
| Service connection | `fabric-cicd-sp` (SP-backed; Workspace Admin on both workspaces; Fabric ADO source-control Connection + `myGitCredentials` bound — see [docs/07](docs/07-service-principal-fabric-git-setup.md)) |
| ADO variable groups | `contoso-fabric-env-dev`, `contoso-fabric-env-prod` (see docs/06) |

## Pipeline at a glance

```
push to dev or prod
        │
        ▼
┌───────────────────────────────┐
│ Stage 1 · Validate            │  scripts/validate_fabric_items.py
│   (no Fabric calls)           │
└───────────────────────────────┘
        │ on success + push-to-branch
        ▼
┌───────────────────────────────┐
│ Stage 2 · SyncFabricFromBranch│  POST /workspaces/{wsId}/git/updateFromGit
│   loads env variable group    │  → poll LRO → workspace at branch HEAD
└───────────────────────────────┘
        │ on success
        ▼
┌───────────────────────────────┐
│ Stage 3 · InjectEnvValues     │  scripts/inject_env_values.py
│   loads env variable group    │  → VarLib  valueSets/<set>.json overrides
│                               │  → SemModel expressions.tmdl M params
│                               │  (idempotent; skip on identical bytes)
└───────────────────────────────┘
        │
        ▼
Workspace now reflects per-environment values from ADO,
not whatever was committed in git.
```

See `docs/06-dynamic-env-injection.md` for the full architecture, ADO variable
group setup, verification queries, and failure-mode runbook.

## Live workshop flow (the demo)

1. Open the **Dev workspace** in Fabric. Show the Lakehouse, Warehouse, SemanticModel, and Variable Library.
2. In VS Code, change `fabric/Contoso-Sales-Model.SemanticModel/definition/tables/table1.tmdl` (add a measure / column).
3. Commit + push to `dev`.
4. ADO pipeline triggers:
   - **Validate** — `scripts/validate_fabric_items.py`
   - **SyncFabricFromBranch** — Fabric pulls the new commit into `Contoso-Sales-Dev`
   - **InjectEnvValues** — `scripts/inject_env_values.py` overwrites the workspace's `Contoso_Vars` Dev value set + the SemanticModel's M parameters with Dev values from `contoso-fabric-env-dev`
5. Refresh the Dev workspace UI → see the change live with environment-correct values.
6. Promote: `git checkout prod`, merge or cherry-pick from `dev`, `git push origin prod`.
7. Same three stages run, loading `contoso-fabric-env-prod`. The Prod workspace gets the model + the Prod IDs / SQL endpoint without any per-branch divergence in expressions.tmdl being necessary.

## Recommended next steps for Contoso

1. **Adopt this pattern** — branch-per-workspace + ADO-driven env injection avoids the Direct Lake Deployment Pipeline rule gap and keeps env-specific identifiers out of git.
2. **Key Vault-back the variable groups** — flip each ADO variable to "linked from Azure Key Vault" for any value that should be a secret.
3. **Wire branch policies** on `prod` — require PR approval from a non-author before merge.
4. **Extend the variable groups** as new env-specific values appear (e.g., additional connections, scheduled refresh tokens). Add the variable to ADO + `valueSets/*.json` + the relevant Fabric item; the pipeline picks it up.
5. **Plan capacity split** before flipping production traffic — separating ingestion/EDW from reporting reduces risk of CI/CD jobs starving report users.

---

*Workshop owner: Microsoft Solution Engineering team. Contact your Microsoft account team for follow-ups.*
