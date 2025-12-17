# Security Guidelines

## Environment Configuration: Secrets vs Variables

This document explains the rationale for classifying GitHub Environment configuration as either Secrets or Variables in this repository.

### Overview

For public repositories, GitHub provides two mechanisms for storing environment-specific configuration:
- **Secrets**: Encrypted values that are masked in logs and not accessible to workflows from forks
- **Variables**: Plain-text values visible in workflow logs and repository settings

### Classification Rationale

#### Environment Secrets (Sensitive Data)

The following values are stored as **Environment Secrets** because they represent sensitive identifiers that should remain masked in logs:

| Secret Name | Description | Rationale |
|-------------|-------------|-----------|
| `AZURE_TENANT_ID` | Azure Active Directory tenant identifier | Tenant IDs can be used to identify organizational boundaries and should remain masked to reduce information leakage |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription identifier | Subscription IDs are subscription-level identifiers that should be protected to prevent enumeration attacks |

**Why these are secrets:**
- Reduces information disclosure in public repositories
- Masked in all workflow logs automatically
- Not available to workflows triggered from forks (security boundary)
- Minimal operational overhead for managing as secrets

#### Environment Variables (Non-Sensitive Data)

The following values are stored as **Environment Variables** because they are non-sensitive identifiers that benefit from visibility:

| Variable Name | Description | Rationale |
|---------------|-------------|-----------|
| `AZURE_CLIENT_ID` | Service Principal Application (Client) ID | Application IDs are not credentials; they identify the app registration but cannot be used alone for authentication |
| `AZURE_PRINCIPAL_ID` | Principal Object ID | Object IDs are identifiers only; they do not grant access or contain sensitive information |
| `AZURE_PRINCIPAL_TYPE` | Type of principal (e.g., ServicePrincipal, User) | Descriptive metadata with no security implications |
| `AZURE_RESOURCE_GROUP` | Resource group name | Non-sensitive resource identifier visible in Azure Portal |
| `AZURE_ENV_NAME` | Environment name for azd | Internal environment label with no security implications |
| `AZURE_LOCATION` | Azure region/location (e.g., eastus, japaneast) | Public information about Azure regions |

**Why these are variables:**
- Easier to view and verify values without decryption
- Simplifies troubleshooting and debugging workflow issues
- Values are already visible in Azure Portal and other public locations
- No security benefit from encrypting them as secrets

### Best Practices

1. **Never store credentials as variables**: Client secrets, passwords, tokens, and connection strings must always be stored as secrets
2. **Review access regularly**: Ensure only authorized users have access to environment secrets
3. **Use environment protection rules**: Configure required reviewers for production environments
4. **Rotate secrets periodically**: Establish a rotation schedule for all credential-based secrets
5. **Monitor for leakage**: Use secret scanning and audit logs to detect accidental exposure

### GitHub Security Features

This repository leverages the following GitHub security features:
- **Environment-scoped secrets/variables**: Isolates configuration per deployment target
- **Required reviewers**: Can be enabled for production environments
- **Secret scanning**: Automatically detects accidentally committed secrets
- **Dependabot**: Monitors dependencies for known vulnerabilities

### References

- [GitHub Actions: Encrypted Secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [GitHub Actions: Variables](https://docs.github.com/en/actions/learn-github-actions/variables)
- [GitHub Environments](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment)
- [Azure Well-Architected Framework: Security](https://learn.microsoft.com/azure/well-architected/security/)

## Reporting Security Issues

Please refer to [Microsoft's Security Response Center](https://www.microsoft.com/msrc) for reporting security vulnerabilities.
