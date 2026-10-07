# Changelog

## 2.0.0 - 2026-10-07

Retrofit to the current demo-pattern standard (docs/-first layout, draw.io diagrams with official icons, visual-richness lint) and fold-in of the reusable workshop material from the originating engagement.

### Docs restructure

- Standard layout: `01-architecture`, `02-prerequisites`, `03-deployment`, `03b-manual-deployment`, `04-testing`, `05-troubleshooting`, `13-configuration-reference` are new or rebuilt. Previous docs were renumbered: 01 -> 06 (Direct Lake + variables), 02 -> 07 (CI/CD paths), 03 -> 08 (ADO bridge), 04 -> 01 (architecture), 05 -> 09, 06 -> 10, 07 -> 11. `12-workshop-walkthrough` is new.
- Every page now has a breadcrumb, hero product icons, status badges, an At-a-glance table, GitHub alert callouts, icon tables, step cards, a Next link and a footer. `scripts/lint_doc_visuals.py --strict` passes with 0 errors.
- 15 draw.io diagrams with official Microsoft Fabric and Azure (V24) icons, exported to PNG at 2x: architecture, service catalog, prerequisites map, pipeline deployment flow, manual deployment steps, testing matrix, troubleshooting tree, Direct Lake parameter injection, CI/CD paths comparison, ADO bridge path, semantic model change flow, Stage 3 sequence, SP onboarding, workshop story, configuration flow.
- Hand-drawn ASCII flow charts replaced by diagrams (00 keeps a short terminal-friendly sketch).

### Folded in from the originating engagement (generalized)

- Three-path framing (deployment pipelines / Git branch-per-workspace / `fabric-cicd`) mapped to Microsoft Learn Options 3 / 1 / 2, with a decision matrix and recommended combinations ([07](./docs/07-cicd-paths-and-promotion.md)).
- Path 1 and Path 3 pipelines under `.azuredevops/pipelines/alternatives/` (no CI trigger, static-only), `scripts/deploy_fabric_cicd.py`, `scripts/requirements-fabric-cicd.txt`, and `fabric/parameter.yml`.
- 60-minute run of show, pre-flight, recovery plan and audience take-aways ([12](./docs/12-workshop-walkthrough.md)); 6-step migration path and handout ([08](./docs/08-ado-bridge-guidance.md)).
- Field-observed `DiscoverDependenciesFailed` on Git sync of hand-authored variable-library value sets, with the workaround ([05](./docs/05-troubleshooting.md)).

### Code

- `validate_fabric_items.py` reads `SEMANTIC_MODEL_NAME` (as the injector does) and checks all three M parameters Stage 3 rewrites (`WorkspaceId`, `LakehouseId`, `WarehouseId`); previously `WarehouseId` was unchecked, so a missing line failed only in Stage 3.
- Both scripts force UTF-8 console output so local runs on Windows don't crash on the status glyphs.
- Pipeline `serviceConnection` default is now the generic `fabric-cicd-sp` - **set it to your service connection name before running**. [11 § 1](./docs/11-service-principal-fabric-git-setup.md#1-entra-app-registration), [03](./docs/03-deployment.md) and [00](./docs/00-reproduce-this-demo.md) spell out the setup step: create an Azure Resource Manager (workload identity federation) service connection named `fabric-cicd-sp`, or change `serviceConnection` in each pipeline YAML to your own name.
- New tests: `test_reusability_guards.py`, `test_configuration.py`, `test_scripts_offline.py`, `test_doc_visuals.py`. All test files run with or without `pytest`.
- `demo-ids.template.json` gains `_template`, a `workload` config block (the only domain-specific surface) and `optionalPaths`; `.gitignore` covers `demo-ids.local.json`, `*.local.json`, `.env*`, keys and `.leak-patterns.txt`.
- Org- and person-specific names (tenant label, subscription name, ADO organisation, service connection) removed from docs and YAML.

### Microsoft Learn accuracy pass (verified 2026-10-07)

| Claim | Was | Now | Source |
|---|---|---|---|
| Variable library GA date | "GA April 2026" | GA since September 2025 | [Variable library overview](https://learn.microsoft.com/en-us/fabric/cicd/variable-library/variable-library-overview) |
| Active value set via REST | "no public REST endpoint" | `PATCH /v1/workspaces/{id}/variableLibraries/{id}` with `properties.activeValueSetName` | [Update Variable Library](https://learn.microsoft.com/en-us/rest/api/fabric/variablelibrary/items/update-variable-library) |
| SP tenant setting | "Service principals can use Fabric APIs" | Split into "Service principals can call Fabric public APIs" (needed) and "... can create workspaces, connections, and deployment pipelines" | [Developer settings](https://learn.microsoft.com/en-us/fabric/admin/service-admin-portal-developer) |
| Git export setting | "... in their organization" | "Users can export items to Git repositories in other geographical locations" | [Git integration settings](https://learn.microsoft.com/en-us/fabric/admin/git-integration-admin-settings) |
| Role for `updateFromGit` | "Admin required" | Learn minimum is Contributor; repo keeps Admin as validated | [Update From Git](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/update-from-git) |
| Option names | Options 1-3 loosely named | Option 1 Git integration, Option 2 Fabric Items APIs, Option 3 deployment pipelines, Option 4 ISVs | [CI/CD workflow options](https://learn.microsoft.com/en-us/fabric/cicd/manage-deployment) |
| Trial capacity | "FTL64" | Trial is an F4 or F64 capacity for 60 days | [Fabric trial](https://learn.microsoft.com/en-us/fabric/fundamentals/fabric-trial) |
| SP + deployment pipelines | "SP can't promote Warehouse" | SP deploys need every item to support SPs; Warehouse failed in the originating build | [Deploy stage content](https://learn.microsoft.com/en-us/rest/api/fabric/core/deployment-pipelines/deploy-stage-content) |
| Semantic models + variable library | implied possible later | Not a supported consumer | Variable library overview |
| `fabric-cicd` | `>=0.1.16` | pinned `1.4.0`; `parameter.yml` must sit at the root of `repository_directory` | [fabric-cicd parameterization](https://microsoft.github.io/fabric-cicd/latest/how_to/parameterization/) |
| Model text in doc 06 | source built from `LakehouseId` | source built from `WorkspaceId` + `WarehouseId` (matches the committed TMDL) | repo |

Not verifiable on Learn: `DiscoverDependenciesFailed` (marked field-observed), and the "rules greyed out for Direct Lake on OneLake" behaviour (Learn doesn't carve it out; an open Fabric idea confirms it).

### Not done

- No live re-run in this release; Path 2 evidence is from the originating build (2026-05). Paths 1 and 3 are static-only.
- No azd template: the pattern creates Fabric items and ADO objects, not ARM resources.

## 1.0.0 - 2026-05

Initial generic release: branch-per-workspace pipeline (Validate -> Sync -> Inject), Contoso Sales Fabric items, injector + validator, docs 00-07.
