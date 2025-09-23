// Module for assigning Directory Readers role at subscription level
// This is required for Azure SQL Server to resolve external users/principals

targetScope = 'subscription'

@description('Principal ID to assign Directory Readers role')
param principalId string

@description('Principal type (User or ServicePrincipal)')
param principalType string

// Assign 'Directory Readers' role to the specified principal
resource directoryReadersRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, principalId, 'Directory Readers')
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: tenantResourceId('Microsoft.Authorization/roleDefinitions', '88d8e3e3-8f55-4a1e-953a-9b9898b8876b') // Directory Readers
  }
}

output roleAssignmentId string = directoryReadersRoleAssignment.id
