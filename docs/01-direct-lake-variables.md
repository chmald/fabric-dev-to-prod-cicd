# Ask 1 — Direct Lake semantic models with environment-driven source

> **The problem Contoso hit**: Direct Lake on OneLake semantic models can't use
> the **Deployment Pipeline rules** UI to swap the workspace/lakehouse the
> model points at — the rules are greyed out for this model type.
> Promoting from Dev to Prod leaves the model pointing at Dev data.
>
> **The workaround**: define M parameters `WorkspaceId` + `LakehouseId`
> in `expressions.tmdl` and embed them in the `AzureStorage.DataLake(...)`
> source URL. The open problem with this pattern is that every time you
> apply changes to your model and promote it, you manually need to change
> the parameters again.
>
> **This repo's automation**: the ADO pipeline overwrites the M parameter
> values per workspace using the Fabric REST API after every `updateFromGit`,
> driven by per-environment ADO variable groups.

## How it works in this repo

### Step 1 — TMDL parameters in `expressions.tmdl`

`fabric/Contoso-Sales-Model.SemanticModel/definition/expressions.tmdl`:

```tmdl
expression WorkspaceId = "11111111-1111-1111-1111-111111111111" meta [IsParameterQuery=true, Type="Text"]
expression LakehouseId = "33333333-3333-3333-3333-333333333333" meta [IsParameterQuery=true, Type="Text"]

expression 'DirectLake - Contoso-Sales-WH' =
    let
        Source = AzureStorage.DataLake(
            "https://onelake.dfs.fabric.microsoft.com/" & #"WorkspaceId" & "/" & #"LakehouseId",
            [HierarchicalNavigation=true])
    in
        Source
```

The committed values are **scaffolding only** — they're whatever happened to be
in the model at the last commit. They matter for at most a few seconds between
`updateFromGit` and the pipeline's injection step.

### Step 2 — Per-environment values from ADO variable groups

| ADO variable group | When loaded | Holds |
|---|---|---|
| `contoso-fabric-env-dev` | pushes to `dev` branch | Dev workspace ID, lakehouse ID, warehouse ID, SQL endpoint, env label `Dev` |
| `contoso-fabric-env-prod` | pushes to `prod` branch | Prod workspace ID, lakehouse ID, warehouse ID, SQL endpoint, env label `Prod` |

Each variable can be plain text or linked to **Azure Key Vault** secret references.

### Step 3 — Pipeline injects via Fabric REST API

After `POST /workspaces/{wsId}/git/updateFromGit` succeeds in Stage 2, Stage 3
runs `scripts/inject_env_values.py`. The script:

1. Locates the workspace's `Contoso_Vars` Variable Library and `Contoso-Sales-Model`
   SemanticModel by displayName (fails if not exactly one match).
2. Calls `POST .../items/{id}/getDefinition` (VarLib) and
   `POST .../semanticModels/{id}/getDefinition?format=TMDL` (SemModel).
3. Decodes the base64-encoded parts. For VarLib, mutates the
   `valueSets/<Dev|Prod>.json` overrides. For SemModel, rewrites the M
   parameter values in `expressions.tmdl` (exactly-one-match regex; fails
   loudly otherwise).
4. Skips the `updateDefinition` call entirely if the decoded content is
   already byte-equal to the desired state (idempotent).
5. Re-fetches the SemanticModel and verifies the new values are observable
   before declaring success.

### Step 4 — Variable Library `environmentLabel` for workspace-wide signals

The Variable Library also holds an `environmentLabel` variable (`Dev` | `Prod`)
that notebooks, data pipelines, and future calculated tables can read without
knowing which environment they're running in. The active value set
(Dev or Prod) is a per-workspace one-time manual setting in the Fabric portal —
there's no clean public REST endpoint for this today.

## Files in this repo

- `fabric/Contoso-Sales-Model.SemanticModel/definition/expressions.tmdl` — M parameter scaffolding
- `fabric/Contoso_Vars.VariableLibrary/variables.json` + `settings.json` + `valueSets/Dev.json` + `valueSets/Prod.json` — Variable Library structure
- `.azuredevops/pipelines/deploy-workspace-per-branch.yml` — three-stage pipeline (Validate → Sync → Inject)
- `scripts/validate_fabric_items.py` — pre-deploy structural checks
- `scripts/inject_env_values.py` — Stage 3 REST injection
- `docs/06-dynamic-env-injection.md` — full runbook for the ADO variable groups + Fabric REST injection

## Common pitfalls (preempt customer questions)

- **Don't put `{{Contoso-Vars.x}}` placeholders inside `expression` blocks in
  `expressions.tmdl`** — TMDL doesn't yet support Variable Library binding
  inside M code for Direct Lake. Use M parameters (this repo's pattern); the
  pipeline overwrites them per workspace.
- **Direct Lake fallback to Import mode** still happens for unsupported
  operations (complex SUMMARIZECOLUMNS with row-context, etc.). The
  M-parameter pattern doesn't change fallback behaviour.
- **Active value-set selection is one-time per workspace.** After the first
  deploy, set the active value set in the Fabric portal (`Dev` for the Dev
  workspace, `Prod` for the Prod workspace). The pipeline keeps the value-set
  CONTENTS current; it does NOT change which value set is active.
- **Adding a new ADO variable** requires three coordinated changes: add to the
  ADO variable group, add to the `overrides` dict in
  `scripts/inject_env_values.py`, and reference it from the Fabric item that
  needs it.

## Reference links

- [Variable Library overview (GA)](https://learn.microsoft.com/en-us/fabric/cicd/variable-library/variable-library-overview)
- [Direct Lake overview](https://learn.microsoft.com/en-us/power-bi/enterprise/directlake-overview)
- [Power BI / TMDL projects (source-controlled semantic models)](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview)
- [Fabric REST API — Items getDefinition / updateDefinition](https://learn.microsoft.com/en-us/rest/api/fabric/core/items)
- [Fabric REST API — Semantic Models getDefinition / updateDefinition](https://learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items)
- [docs/05-semantic-model-deploy.md](05-semantic-model-deploy.md) — step-by-step change → promote runbook
- [docs/06-dynamic-env-injection.md](06-dynamic-env-injection.md) — full ADO + REST API setup runbook
