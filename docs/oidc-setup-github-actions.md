# OIDC Setup for GitHub Actions

This guide configures GitHub Actions to deploy to Azure using Microsoft Entra workload identity federation (OIDC) for this repository. Commands use the Azure CLI and assume bash/Git Bash.

> [!TIP]
> Use GitHub Environments so that secrets/variables are scoped per subscription. Protect environments if you want approvals on variable use.

## Prerequisites

- Azure CLI (`az`) 2.57.0+ and logged in (`az login`)
- Permission to create an app registration (or reuse an existing one) and to assign roles at the subscription/resource group scope
- Target subscription selected (`az account set --subscription <name-or-id>`)

```bash
# Verify context
az account show --output table
```

> [!IMPORTANT]
> Your GitHub Actions workflow must have OIDC permissions enabled:
>
> ```yaml
> permissions:
>   id-token: write
>   contents: read
> ```
>
> If you bind the federated credential to a GitHub Environment (recommended), the workflow job must also set `environment: <name>` and the `<name>` must match the federated credential `subject`.

## Step 1: Get your Azure information

```bash
AZURE_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)

# Choose or create your deployment resource group
AZURE_RESOURCE_GROUP="your-resource-group-name"  # e.g., rg-infra-support-copilot
AZURE_LOCATION="japaneast"  # e.g., japaneast, eastus2, westeurope
az group create -n "$AZURE_RESOURCE_GROUP" -l "$AZURE_LOCATION"

# Name the azd environment (per subscription)
AZURE_ENV_NAME="your-azd-env-name"  # e.g., infra-support-copilot-env

# Name of the GitHub Environment used by the workflow job `environment:`.
# In this repo's workflow, this is the matrix entry (see .github/workflows/cicd.yml).
GITHUB_ENVIRONMENT="your-github-environment-name"  # e.g., rukasakurai-env
```

## Step 2: Create (or use existing) Microsoft Entra app registration

```bash
APP_DISPLAY_NAME="infra-support-copilot-gha"  # Use any unique display name

# Create the app registration (or fetch existing appId)
AZURE_CLIENT_ID=$(az ad app create --display-name "$APP_DISPLAY_NAME" --query appId -o tsv)
# If reusing an existing app: AZURE_CLIENT_ID=$(az ad app list --display-name "$APP_DISPLAY_NAME" --query "[0].appId" -o tsv)

# App registration object ID (different from client/app ID)
AZURE_APP_OBJECT_ID=$(az ad app show --id "$AZURE_CLIENT_ID" --query id -o tsv)

# Ensure a service principal exists (idempotent)
az ad sp show --id "$AZURE_CLIENT_ID" --only-show-errors >/dev/null 2>&1 || az ad sp create --id "$AZURE_CLIENT_ID"
AZURE_PRINCIPAL_ID=$(az ad sp show --id "$AZURE_CLIENT_ID" --query id -o tsv)
AZURE_PRINCIPAL_TYPE="ServicePrincipal"
```

## Step 3: Assign Azure permissions

Grant least privilege at the subscription or resource-group scope. The sample below scopes to the resource group.

> [!IMPORTANT]
> To assign the **User Access Administrator** role, you must have elevated privileges such as **Owner** at the target scope (resource group or subscription), or **Global Administrator** / **Privileged Role Administrator** at the tenant level. If you cannot assign this role, ask an administrator with sufficient permissions to run these commands on your behalf, or to grant you temporary elevated access.

```bash
SCOPE="/subscriptions/$AZURE_SUBSCRIPTION_ID/resourceGroups/$AZURE_RESOURCE_GROUP"

az role assignment create --assignee-object-id "$AZURE_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal --role "Contributor" --scope "$SCOPE"
az role assignment create --assignee-object-id "$AZURE_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal --role "User Access Administrator" --scope "$SCOPE"
```

## Step 4: Configure federated credentials

Create a federated credential that binds the app registration to a GitHub Environment. Replace `GITHUB_ENVIRONMENT` with your environment name (matches the workflow `environment:` value).

```bash
GITHUB_ORG="Azure-Samples"       # Use your fork org if different
GITHUB_REPO="infra-support-copilot"  # Use your fork repo name if different
GITHUB_ENVIRONMENT="$GITHUB_ENVIRONMENT"

cat <<EOF > fc.json
{
  "name": "gha-${GITHUB_ENVIRONMENT}",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:${GITHUB_ORG}/${GITHUB_REPO}:environment:${GITHUB_ENVIRONMENT}",
  "audiences": ["api://AzureADTokenExchange"]
}
EOF

az ad app federated-credential create --id "$AZURE_APP_OBJECT_ID" --parameters @fc.json
```

## Step 5: Configure GitHub environment variables and secrets

Set these on `Settings → Environments → <GITHUB_ENVIRONMENT>`:

- **Secrets** (kept masked): `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`
- **Variables** (non-confidential values): `AZURE_CLIENT_ID`, `AZURE_PRINCIPAL_ID` (service principal `object ID`, not `client ID`), `AZURE_PRINCIPAL_TYPE` (value: `ServicePrincipal`), `AZURE_RESOURCE_GROUP`, `AZURE_ENV_NAME`, `AZURE_LOCATION`

> [!NOTE]
> `AZURE_APP_OBJECT_ID` is only needed when creating/listing the federated credential via Azure CLI. You typically do not need to store it in GitHub.

Protect the environment if you require approvals before variable use.
Subscription and tenant IDs are kept as secrets so they stay masked in logs and are not exposed to forks.
Use the service principal object ID from Step 2 (`az ad sp show --id "$AZURE_CLIENT_ID" --query id -o tsv`). Role assignments and the Bicep template expect the object ID, while the client ID is used by login.

Example login step for workflows:

```yaml
- name: Azure login (OIDC)
  uses: azure/login@v2
  with:
    client-id: ${{ vars.AZURE_CLIENT_ID }}
    tenant-id: ${{ secrets.AZURE_TENANT_ID }}
    subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```

## Step 6: Verify configuration

```bash
# Federated credential is present
az ad app federated-credential list --id "$AZURE_APP_OBJECT_ID" --query "[].{name:name,subject:subject}" -o table

# Role assignments are in place
az role assignment list --assignee-object-id "$AZURE_PRINCIPAL_ID" --scope "$SCOPE" -o table
```

Then run the GitHub Actions workflow against the environment; the `azure/login@v2` step should succeed without storing client secrets.
