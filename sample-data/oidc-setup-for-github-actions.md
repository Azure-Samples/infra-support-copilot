# OIDC Setup for GitHub Actions

This guide walks you through configuring OpenID Connect (OIDC) authentication between GitHub Actions and Azure, enabling passwordless deployments without storing long-lived credentials.

## Prerequisites

- Azure subscription with appropriate permissions (Owner or Contributor + User Access Administrator)
- Azure CLI installed and configured (`az`)
- GitHub CLI installed (`gh`) - optional but recommended
- Bash or Git Bash shell environment

## Overview

OIDC allows GitHub Actions to authenticate to Azure using short-lived tokens instead of storing service principal secrets. This provides better security through:
- No long-lived credentials stored in GitHub
- Automatic token rotation
- Fine-grained access control via federated credentials

---

## Step 1: Get Your Azure Information

First, gather the Azure subscription and tenant information needed for configuration.

```bash
# Login to Azure
az login

# Get your subscription ID and tenant ID
az account show --query "{subscriptionId:id, tenantId:tenantId}" -o table

# Store values for later use
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)

echo "Subscription ID: $SUBSCRIPTION_ID"
echo "Tenant ID: $TENANT_ID"
```

**Save these values** - you'll need them for GitHub environment configuration.

---

## Step 2: Create (or Use Existing) Microsoft Entra App Registration

Create a new app registration for GitHub Actions authentication, or use an existing one.

### Option A: Create New App Registration

```bash
# Set variables for your app
APP_NAME="github-actions-oidc-infra-support-copilot"

# Create the app registration
APP_ID=$(az ad app create \
  --display-name "$APP_NAME" \
  --query appId -o tsv)

echo "Created App Registration with Client ID: $APP_ID"

# Create a service principal for the app
az ad sp create --id $APP_ID

# Get the service principal object ID
SP_OBJECT_ID=$(az ad sp show --id $APP_ID --query id -o tsv)

echo "Service Principal Object ID: $SP_OBJECT_ID"
```

### Option B: Use Existing App Registration

```bash
# If you have an existing app, get its ID
APP_NAME="your-existing-app-name"
APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)

# Verify it exists and get service principal object ID
SP_OBJECT_ID=$(az ad sp show --id $APP_ID --query id -o tsv)

echo "Using existing App with Client ID: $APP_ID"
echo "Service Principal Object ID: $SP_OBJECT_ID"
```

---

## Step 3: Assign Azure Permissions

Grant the service principal permissions to deploy resources in your subscription.

```bash
# Set your resource group name (or create a new one)
RESOURCE_GROUP="rg-infra-support-copilot"
LOCATION="eastus2"  # or your preferred location

# Create resource group if it doesn't exist
az group create --name $RESOURCE_GROUP --location $LOCATION

# Assign Contributor role at subscription level (or resource group level for more restrictive access)
az role assignment create \
  --assignee $APP_ID \
  --role "Contributor" \
  --scope "/subscriptions/$SUBSCRIPTION_ID"

echo "Assigned Contributor role to service principal"

# For Azure SQL with Entra authentication, also assign Directory Readers role
# This allows the service principal to read directory information
az role assignment create \
  --assignee $SP_OBJECT_ID \
  --role "Directory Readers" \
  --scope "/providers/Microsoft.Entra"

echo "Assigned Directory Readers role for SQL Server Entra authentication"
```

**Note:** For production environments, consider using more restrictive roles scoped to specific resource groups instead of subscription-wide Contributor access.

---

## Step 4: Configure Federated Credentials

Set up federated identity credentials to allow GitHub Actions to authenticate using OIDC tokens.

```bash
# Set your GitHub repository information
GITHUB_ORG="Azure-Samples"  # or your GitHub username/org
GITHUB_REPO="infra-support-copilot"
GITHUB_ENV="rukasakurai-env"  # your GitHub environment name

# Create federated credential for the GitHub environment
az ad app federated-credential create \
  --id $APP_ID \
  --parameters '{
    "name": "github-'"$GITHUB_ENV"'",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:'"$GITHUB_ORG"'/'"$GITHUB_REPO"':environment:'"$GITHUB_ENV"'",
    "description": "GitHub Actions OIDC for '"$GITHUB_ENV"' environment",
    "audiences": ["api://AzureADTokenExchange"]
  }'

echo "Created federated credential for environment: $GITHUB_ENV"
```

### Adding Credentials for Multiple Environments

If you have multiple GitHub environments (e.g., dev, staging, production):

```bash
# Example: Add federated credential for another environment
GITHUB_ENV_2="another-env"

az ad app federated-credential create \
  --id $APP_ID \
  --parameters '{
    "name": "github-'"$GITHUB_ENV_2"'",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:'"$GITHUB_ORG"'/'"$GITHUB_REPO"':environment:'"$GITHUB_ENV_2"'",
    "description": "GitHub Actions OIDC for '"$GITHUB_ENV_2"' environment",
    "audiences": ["api://AzureADTokenExchange"]
  }'
```

### Verifying Federated Credentials

```bash
# List all federated credentials for your app
az ad app federated-credential list --id $APP_ID -o table
```

---

## Step 5: Configure GitHub Environment Variables and Secrets

Configure your GitHub repository with the necessary environment variables and secrets.

### Using GitHub CLI (Recommended)

```bash
# Login to GitHub CLI
gh auth login

# Navigate to your repository directory
cd /path/to/your/repo

# Set the GitHub environment name
GITHUB_ENV="rukasakurai-env"

# Create the environment if it doesn't exist
gh api --method PUT \
  "repos/$GITHUB_ORG/$GITHUB_REPO/environments/$GITHUB_ENV" \
  --silent

# Add environment secrets (sensitive data)
echo $TENANT_ID | gh secret set AZURE_TENANT_ID --env $GITHUB_ENV
echo $SUBSCRIPTION_ID | gh secret set AZURE_SUBSCRIPTION_ID --env $GITHUB_ENV

echo "Environment secrets configured"

# Add environment variables (non-sensitive identifiers)
gh variable set AZURE_CLIENT_ID --env $GITHUB_ENV --body "$APP_ID"
gh variable set AZURE_PRINCIPAL_ID --env $GITHUB_ENV --body "$APP_ID"
gh variable set AZURE_PRINCIPAL_TYPE --env $GITHUB_ENV --body "ServicePrincipal"
gh variable set AZURE_RESOURCE_GROUP --env $GITHUB_ENV --body "$RESOURCE_GROUP"
gh variable set AZURE_ENV_NAME --env $GITHUB_ENV --body "$GITHUB_ENV"
gh variable set AZURE_LOCATION --env $GITHUB_ENV --body "$LOCATION"

echo "Environment variables configured"
```

### Using GitHub Web UI (Alternative)

If you prefer using the GitHub web interface:

1. Go to your repository: `https://github.com/$GITHUB_ORG/$GITHUB_REPO`
2. Navigate to **Settings** → **Environments**
3. Click on your environment (or create a new one)
4. Add **Environment secrets**:
   - `AZURE_TENANT_ID` = `<your-tenant-id>`
   - `AZURE_SUBSCRIPTION_ID` = `<your-subscription-id>`
5. Add **Environment variables**:
   - `AZURE_CLIENT_ID` = `<your-app-client-id>`
   - `AZURE_PRINCIPAL_ID` = `<your-app-client-id>` (same as CLIENT_ID for service principals)
   - `AZURE_PRINCIPAL_TYPE` = `ServicePrincipal`
   - `AZURE_RESOURCE_GROUP` = `<your-resource-group>`
   - `AZURE_ENV_NAME` = `<your-environment-name>`
   - `AZURE_LOCATION` = `<azure-region>` (e.g., `eastus2`, `japaneast`)

### Configuration Summary

Print a summary of all values for reference:

```bash
echo "==================================="
echo "GitHub Environment Configuration"
echo "==================================="
echo "Environment Name: $GITHUB_ENV"
echo ""
echo "Secrets (add via GitHub UI/CLI):"
echo "  AZURE_TENANT_ID: $TENANT_ID"
echo "  AZURE_SUBSCRIPTION_ID: $SUBSCRIPTION_ID"
echo ""
echo "Variables (add via GitHub UI/CLI):"
echo "  AZURE_CLIENT_ID: $APP_ID"
echo "  AZURE_PRINCIPAL_ID: $APP_ID"
echo "  AZURE_PRINCIPAL_TYPE: ServicePrincipal"
echo "  AZURE_RESOURCE_GROUP: $RESOURCE_GROUP"
echo "  AZURE_ENV_NAME: $GITHUB_ENV"
echo "  AZURE_LOCATION: $LOCATION"
echo "==================================="
```

---

## Step 6: Verify Configuration

Test your OIDC configuration by running a GitHub Actions workflow.

### Verify Azure Configuration

```bash
# Verify service principal has correct role assignments
az role assignment list --assignee $APP_ID --output table

# Verify federated credentials are configured
az ad app federated-credential list --id $APP_ID -o table

# Test that the service principal can access the subscription
az account list --query "[?id=='$SUBSCRIPTION_ID']" -o table
```

### Verify GitHub Actions Workflow

1. **Trigger a workflow run** in your repository (push to the branch or manually trigger)
2. **Monitor the workflow logs** in GitHub Actions
3. **Check the "Azure login" step** - it should authenticate successfully using OIDC
4. Look for log output similar to:
   ```
   Login successful
   ```

### Troubleshooting Common Issues

#### Issue: "Failed to get federated token"

**Solution:** Verify federated credential subject matches exactly:
```bash
# Check existing credentials
az ad app federated-credential list --id $APP_ID -o json | grep subject

# Subject should be: repo:ORG/REPO:environment:ENV_NAME
```

#### Issue: "Insufficient privileges to complete the operation"

**Solution:** Ensure service principal has correct role assignments:
```bash
# Re-assign Contributor role
az role assignment create \
  --assignee $APP_ID \
  --role "Contributor" \
  --scope "/subscriptions/$SUBSCRIPTION_ID"
```

#### Issue: "Directory Readers role required for SQL"

**Solution:** Assign Directory Readers role to service principal object ID:
```bash
# Get the service principal object ID (not the app ID)
SP_OBJECT_ID=$(az ad sp show --id $APP_ID --query id -o tsv)

# Assign Directory Readers role
az role assignment create \
  --assignee $SP_OBJECT_ID \
  --role "Directory Readers" \
  --scope "/providers/Microsoft.Entra"
```

#### Issue: Environment variables not showing in workflow

**Solution:** Ensure you're using `vars.VARIABLE_NAME` syntax in workflow:
```yaml
# Correct
client-id: ${{ vars.AZURE_CLIENT_ID }}

# Incorrect (this is for secrets only)
client-id: ${{ secrets.AZURE_CLIENT_ID }}
```

---

## Additional Resources

- [GitHub Actions OIDC Documentation](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-azure)
- [Azure Federated Identity Credentials](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation)
- [GitHub Actions Secrets vs Variables](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [Azure Role-Based Access Control](https://learn.microsoft.com/en-us/azure/role-based-access-control/overview)

---

## Security Best Practices

1. **Use environment-specific credentials**: Create separate app registrations for each environment (dev, staging, prod)
2. **Scope permissions narrowly**: Assign roles at resource group level instead of subscription level when possible
3. **Rotate credentials regularly**: Although OIDC tokens are short-lived, periodically review and rotate app registrations
4. **Enable environment protection rules**: Configure required reviewers for production environments in GitHub
5. **Monitor access**: Regularly review role assignments and federated credentials:
   ```bash
   # Audit role assignments
   az role assignment list --assignee $APP_ID --output table
   
   # Audit federated credentials
   az ad app federated-credential list --id $APP_ID -o table
   ```

---

## Complete Setup Script

For convenience, here's a complete script that automates the entire setup:

```bash
#!/bin/bash
set -e

# Configuration variables
APP_NAME="github-actions-oidc-infra-support-copilot"
GITHUB_ORG="Azure-Samples"
GITHUB_REPO="infra-support-copilot"
GITHUB_ENV="rukasakurai-env"
RESOURCE_GROUP="rg-infra-support-copilot"
LOCATION="eastus2"

echo "Starting OIDC setup for GitHub Actions..."

# Step 1: Get Azure information
echo "Step 1: Getting Azure information..."
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
echo "✓ Subscription ID: $SUBSCRIPTION_ID"
echo "✓ Tenant ID: $TENANT_ID"

# Step 2: Create app registration
echo "Step 2: Creating app registration..."
APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
az ad sp create --id $APP_ID > /dev/null
SP_OBJECT_ID=$(az ad sp show --id $APP_ID --query id -o tsv)
echo "✓ App Client ID: $APP_ID"
echo "✓ Service Principal Object ID: $SP_OBJECT_ID"

# Step 3: Assign Azure permissions
echo "Step 3: Assigning Azure permissions..."
az group create --name $RESOURCE_GROUP --location $LOCATION > /dev/null
az role assignment create --assignee $APP_ID --role "Contributor" \
  --scope "/subscriptions/$SUBSCRIPTION_ID" > /dev/null
az role assignment create --assignee $SP_OBJECT_ID --role "Directory Readers" \
  --scope "/providers/Microsoft.Entra" > /dev/null 2>&1 || echo "Note: Directory Readers role may require additional permissions"
echo "✓ Permissions assigned"

# Step 4: Configure federated credentials
echo "Step 4: Configuring federated credentials..."
az ad app federated-credential create --id $APP_ID --parameters '{
  "name": "github-'"$GITHUB_ENV"'",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:'"$GITHUB_ORG"'/'"$GITHUB_REPO"':environment:'"$GITHUB_ENV"'",
  "description": "GitHub Actions OIDC for '"$GITHUB_ENV"' environment",
  "audiences": ["api://AzureADTokenExchange"]
}' > /dev/null
echo "✓ Federated credential created for $GITHUB_ENV"

# Step 5: Display GitHub configuration
echo ""
echo "==================================="
echo "GitHub Environment Configuration"
echo "==================================="
echo "Configure these in GitHub Settings → Environments → $GITHUB_ENV"
echo ""
echo "Secrets:"
echo "  AZURE_TENANT_ID: $TENANT_ID"
echo "  AZURE_SUBSCRIPTION_ID: $SUBSCRIPTION_ID"
echo ""
echo "Variables:"
echo "  AZURE_CLIENT_ID: $APP_ID"
echo "  AZURE_PRINCIPAL_ID: $APP_ID"
echo "  AZURE_PRINCIPAL_TYPE: ServicePrincipal"
echo "  AZURE_RESOURCE_GROUP: $RESOURCE_GROUP"
echo "  AZURE_ENV_NAME: $GITHUB_ENV"
echo "  AZURE_LOCATION: $LOCATION"
echo "==================================="
echo ""
echo "✓ Setup complete! Configure GitHub environment and trigger a workflow to test."
```

Save this script as `setup-oidc.sh`, make it executable (`chmod +x setup-oidc.sh`), and run it to automate the entire setup process.
