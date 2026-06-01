# 03 — Bridging "configured but unused" Azure DevOps to a working CI/CD pattern

> **Reading guide.** This was originally a multi-step migration playbook with `dev` / `qa` / `main` branching and two competing CI/CD paths. It has been replaced by the single shipped path documented in [00-reproduce-this-demo.md](00-reproduce-this-demo.md) and [02-lakehouse-warehouse-promotion.md](02-lakehouse-warehouse-promotion.md). The condensed migration outline below is what remains useful.

## Starting state vs. target state

| | Starting state | Target state (this repo) |
|---|---|---|
| **ADO** | Connected to Dev workspace via Fabric Git integration, otherwise inert. | Drives end-to-end promotion via [`deploy-workspace-per-branch.yml`](../.azuredevops/pipelines/deploy-workspace-per-branch.yml). |
| **Promotion mechanism** | Manual Fabric Deployment Pipeline clicks for Dev → QA → Prod. | `git merge dev → prod; git push origin prod`. |
| **Per-env values** | Hand-edited in each workspace after promotion. | Injected by Stage 3 from ADO variable groups (Key Vault–backable). |
| **Workspaces** | Three (Dev / QA / Prod) bound to a single capacity. | Two (`Contoso-Sales-Dev`, `Contoso-Sales-Prod`) — add `qa` later by repeating the same pattern. |
| **Governance** | None enforced. | Branch policy on `prod` (required reviewers); optional ADO Environment approval gate on `fabric-prod`. |

## Migration sequence (high level)

1. **Stand up the SP, tenant settings, and Fabric ADO source-control Connection** — one-time per tenant. Follow [07-service-principal-fabric-git-setup.md](07-service-principal-fabric-git-setup.md).
2. **Bind each Fabric workspace to its branch** in the Fabric portal — one-time per workspace. See [00 Part D](00-reproduce-this-demo.md).
3. **Create the two ADO variable groups + ADO Environments** — see [06 §1, §4](06-dynamic-env-injection.md).
4. **Register the pipeline + push to `dev` once** — Stage 1 → 2 → 3 should run green. See [00 Part E + Part F](00-reproduce-this-demo.md).
5. **Promote to `prod` via `git merge`** — same three stages, loads `contoso-fabric-env-prod`. See [00 Part G](00-reproduce-this-demo.md).
6. **Add branch policy on `prod`** requiring PR approval from a non-author (recommended).
7. **(Optional)** Add ADO Environment approval gate on `fabric-prod` for an explicit promote-to-prod human checkpoint. See [06 §4](06-dynamic-env-injection.md).

## Anti-patterns to avoid

- **Credentials in YAML.** Use the ADO service connection (workload identity federation preferred) and Key Vault–linked variable groups for any secret.
- **Direct workspace-to-workspace deploys.** You lose the audit + rollback story Git gives you for free.
- **Manual edits in the Prod workspace.** Pick one source of truth (the repo). Treat manual prod edits as "fix it in `dev` and re-promote".
- **Branch sprawl for environments.** Two long-lived branches (`dev`, `prod`) are enough. Add a `qa` branch + workspace + variable group only if there's a real change-control reason to.
- **Hand-edited per-env IDs in committed Fabric items.** That's exactly what Stage 3 exists to overwrite — see [docs/01](01-direct-lake-variables.md).

## Reference links

- [Get started with Git integration](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-get-started)
- [Manage branches](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/manage-branches)
- [CI/CD best practices](https://learn.microsoft.com/en-us/fabric/cicd/best-practices-cicd)
- [docs/00 — end-to-end stand-up guide](00-reproduce-this-demo.md)
- [docs/02 — chosen path overview](02-lakehouse-warehouse-promotion.md)
- [docs/06 — Stage 3 runbook](06-dynamic-env-injection.md)
