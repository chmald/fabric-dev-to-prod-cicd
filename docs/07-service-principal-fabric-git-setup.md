# 07 — Service Principal setup for Fabric + Azure DevOps Git integration

> One-time onboarding runbook. Run this once per **service principal**, per **Fabric tenant**, and per **workspace** that the pipeline drives. Skipping any step manifests as one of the two errors in the *Troubleshooting* table at the bottom.

The pipeline in [.azuredevops/pipelines/deploy-workspace-per-branch.yml](../.azuredevops/pipelines/deploy-workspace-per-branch.yml) calls three Fabric Git endpoints under the SP identity:

- `GET  /v1/workspaces/{wsId}/git/status`
- `POST /v1/workspaces/{wsId}/git/updateFromGit`
- `GET  /v1/operations/{opId}`

For a **user** identity, Fabric's portal handshake transparently sets up everything these calls need. For a **service principal** there is no interactive handshake — every prerequisite below is explicit.

---

## Prerequisites checklist

Work through these in order. The next step will not succeed until the previous step is done.

### 1. Entra app registration

- App registration exists in the same Entra tenant as the Fabric tenant.
- Note the **Application (client) ID** and **Object ID**.
- A credential is configured for ADO to use:
  - **Recommended:** federated credential bound to the ADO service connection (`fabric-cicd-sp`).
  - Acceptable: client secret in an ADO service connection or Key Vault.
- No Microsoft Graph / Power BI delegated permissions are required for Fabric REST — token audience is `https://api.fabric.microsoft.com`.

### 2. Fabric tenant settings (Fabric Admin Portal → *Tenant settings*)

All three of these must be **Enabled** and scoped to a security group that contains the SP (or to the whole org):

| Setting | Section | Why |
|---|---|---|
| **Service principals can use Fabric APIs** | Developer settings | Without this, every Fabric REST call from the SP is rejected at the tenant boundary. |
| **Users can synchronize workspace items with their Git repositories** | Git integration | Gates `git/status`, `git/updateFromGit`, `git/commitToGit`. The "Users" label is misleading — it gates SPs too. |
| **Users can export items to Git repositories in their organization** | Git integration | Required if any pipeline path ever calls `commitToGit` (not used by Stage 2 today, but enable for completeness). |

Tenant settings can take several minutes to propagate.

### 3. Workspace role assignment

For **every workspace** the pipeline targets (here: `Contoso-Sales-Dev` and `Contoso-Sales-Prod`):

- Fabric portal → workspace → **Manage access** → add the SP by app name or object id.
- Role: **Admin**. (Member is *not* sufficient for Git endpoints — they require Admin.)

### 4. Azure DevOps user assignment

The SP must also be a real user in the Azure DevOps organization that hosts the repo:

- ADO → **Organization Settings → Users → Add users** → search the SP by app name.
- Access level: **Basic**.
- Project membership: add to the **Contributors** group of the project containing the repo.
- Verify the SP has at minimum **Read** on the repo (Project Settings → Repositories → Security).

Without this, the *Fabric → ADO* call inside `updateFromGit` fails on the ADO side even after the rest of the chain works.

### 5. Fabric Azure DevOps source-control **Connection**

This is the SP equivalent of "click *Connect to Azure DevOps* in the workspace portal as a user". It's a one-time creation per SP per tenant; the same Connection can be reused by all workspaces.

1. Fabric portal → **Manage connections and gateways** → **Connections** → **+ New**.
2. Connection type: **Azure DevOps (source control)**.
3. Authentication method: **Service Principal**. Fill in:
   - Tenant ID
   - Application (client) ID — the SP's
   - Client secret or federated credential, matching what the ADO service connection uses
4. Save. **Copy the Connection ID (GUID)** — you'll need it in the next step.
5. Open the new Connection → **Settings → Manage users** → grant the SP itself the **User** role on the Connection. (Yes, the SP must own its own Connection.)

### 6. Bind the Connection to each workspace as the SP's `myGitCredentials`

`myGitCredentials` is per-(identity, workspace). The SP itself must call this — running it as a human won't set the SP's credentials. The simplest way is a one-shot Azure CLI invocation under the ADO service connection (or from the pipeline; see *Optional: automate in pipeline* below).

```powershell
# Run under the SP identity (e.g. inside an AzureCLI@2 task using the same
# service connection the pipeline uses, or `az login --service-principal ...`).

$wsId         = "<workspace-guid>"          # e.g. 11111111-1111-1111-1111-111111111111
$connectionId = "<fabric-connection-guid>"  # from step 5

$token   = az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv
$headers = @{ Authorization = "Bearer $token"; 'Content-Type' = 'application/json' }
$body    = @{ source = "ConfiguredConnection"; connectionId = $connectionId } | ConvertTo-Json

Invoke-RestMethod -Method PATCH `
    -Uri "https://api.fabric.microsoft.com/v1/workspaces/$wsId/git/myGitCredentials" `
    -Headers $headers -Body $body
```

A successful response is HTTP 200 with the bound credential source echoed back. Repeat for each workspace (Dev + Prod). The same `connectionId` can be reused — `myGitCredentials` is per-workspace state, not per-Connection.

### 7. Workspace must already be Git-connected

`myGitCredentials` only configures the *identity's* credentials — the *workspace ↔ repo branch* binding is a separate one-time setup done by a human via the portal:

- Fabric portal → workspace → **Workspace settings → Git integration** → connect to the Azure DevOps org / project / repo / branch / folder (`fabric/`).
- Repeat for each workspace (`Contoso-Sales-Dev` ↔ `dev`, `Contoso-Sales-Prod` ↔ `prod`).

Once connected, the SP (with steps 1–6 in place) can drive sync going forward.

---

## Verification

From a local shell, logged in as the SP (`az login --service-principal ...` or via the ADO service connection):

```powershell
$token   = az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv
$headers = @{ Authorization = "Bearer $token" }

Invoke-RestMethod -Method GET `
    -Uri "https://api.fabric.microsoft.com/v1/workspaces/<wsId>/git/status" `
    -Headers $headers
```

Expected: a JSON body with `workspaceHead`, `remoteCommitHash`, and `changes`. Any error response means a step above was missed — see the table below.

---

## Troubleshooting

| HTTP error body | Root cause | Fix |
|---|---|---|
| `InsufficientPrivileges` — *"The caller does not have sufficient permissions to access the requested resource"*, `relatedResource.resourceType = "Workspace"` | SP is not a Workspace Admin on the target workspace, **or** the "Service principals can use Fabric APIs" tenant setting is off / not scoped to the SP. | Step 3 (workspace Admin) and step 2 (tenant setting). Workspace role is by far the most common cause. |
| `GitCredentialsNotConfigured` — *"The user's Git credentials are not configured."* | The SP has no `myGitCredentials` binding for this workspace. | Steps 5 + 6 — create the ADO source-control Connection, then PATCH `myGitCredentials` per workspace. |
| `PrincipalTypeNotSupported` on Warehouse promotion via Deployment Pipelines | Known Fabric DP limitation for SPs against Warehouse items — unrelated to Git integration. | See [02-lakehouse-warehouse-promotion.md](02-lakehouse-warehouse-promotion.md). |
| `GitCloneFailure` / 401 from ADO inside `updateFromGit` | SP is not a user in the ADO organization or has no Read on the repo. | Step 4. |
| `400 InvalidParameter` on `myGitCredentials` PATCH | Connection ID typo, Connection not of type *Azure DevOps source control*, or SP has no role on the Connection itself. | Re-check step 5; ensure the SP is a **User** on the Connection. |

---

## Automated `myGitCredentials` bind in the pipeline

This bind is **already wired** into the `sync_workspace` job in [deploy-workspace-per-branch.yml](../.azuredevops/pipelines/deploy-workspace-per-branch.yml) as the first step, gated on a `GIT_CONNECTION_ID` variable in each env group:

```yaml
- task: AzureCLI@2
  displayName: 'Ensure myGitCredentials bound to Fabric ADO connection'
  condition: and(succeeded(), ne(variables['GIT_CONNECTION_ID'], ''))
  inputs:
    azureSubscription: '$(serviceConnection)'
    scriptType: pscore
    scriptLocation: inlineScript
    inlineScript: |
      $token   = az account get-access-token --resource https://api.fabric.microsoft.com --query accessToken -o tsv
      $headers = @{ Authorization = "Bearer $token"; 'Content-Type' = 'application/json' }
      $body    = @{ source = "ConfiguredConnection"; connectionId = "$(GIT_CONNECTION_ID)" } | ConvertTo-Json

      Invoke-RestMethod -Method PATCH `
          -Uri "https://api.fabric.microsoft.com/v1/workspaces/$(WORKSPACE_ID)/git/myGitCredentials" `
          -Headers $headers -Body $body | Out-Null
      Write-Host "✓ myGitCredentials bound to connection $(GIT_CONNECTION_ID)"
```

To activate it, add `GIT_CONNECTION_ID` (the GUID from step 5) to each environment variable group:

- `contoso-fabric-env-dev` → `GIT_CONNECTION_ID = <fabric-connection-guid>`
- `contoso-fabric-env-prod` → `GIT_CONNECTION_ID = <fabric-connection-guid>`

Environments without that variable just skip the bind (the condition is a no-op), so the pipeline stays backward-compatible with the manual step-6 flow above. The PATCH is idempotent — re-running it with the same `connectionId` is a no-op on Fabric's side, so the step is safe on every pipeline run.

---

## Canonical references

- [Fabric REST: `myGitCredentials - Update`](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/update-my-git-credentials)
- [Fabric REST: `Git - Get Status`](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/get-status)
- [Fabric REST: `Git - Update From Git`](https://learn.microsoft.com/en-us/rest/api/fabric/core/git/update-from-git)
- [Fabric Git integration — service principal support](https://learn.microsoft.com/en-us/fabric/cicd/git-integration/git-integration-process)
- [Fabric Admin Portal — tenant settings reference](https://learn.microsoft.com/en-us/fabric/admin/about-tenant-settings)
