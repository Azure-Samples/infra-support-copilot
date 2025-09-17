@description('The location used for all resources')
param location string = resourceGroup().location

@description('Name used for the deployment environment')
param environmentName string

@description('Unique suffix for naming resources')
param resourceToken string = uniqueString(resourceGroup().id, environmentName)

@description('Tags that will be applied to all resources')
param tags object = {
  'azd-env-name': environmentName
}

@description('Principal ID of the user running the deployment (for role assignments)')
param userPrincipalId string

@description('Type of the principal identified by userPrincipalId. Use "User" for human accounts; "ServicePrincipal" for CI/CD service principals.')
@allowed([
  'User'
  'ServicePrincipal'
  'Group'
  'ForeignGroup'
  'Device'
])
param userPrincipalType string = 'User'

var isUserPrincipal = toLower(userPrincipalType) == 'user'

// ----------------------------------------------------
// App Service and configuration
// ----------------------------------------------------

@description('Name of the App Service for hosting the Python FastAPI app')
param appServiceName string = 'app-${resourceToken}'

@description('App Service Plan SKU')
@allowed([
  'B1'
  'B2'
  'B3'
  'S1'
  'S2'
  'S3'
  'P1v2'
  'P2v2'
  'P3v2'
])
param appServicePlanSku string = 'P2v2'

// Create App Service Plan
resource appServicePlan 'Microsoft.Web/serverfarms@2022-03-01' = {
  name: 'plan-${resourceToken}'
  location: location
  tags: tags
  sku: {
    name: appServicePlanSku
  }
  kind: 'linux'
  properties: {
    reserved: true
  }
}

  // ----------------------------------------------------
  // Application Insights
  // ----------------------------------------------------
  @description('Name of the Application Insights resource')
  param appInsightsName string = 'appi-${resourceToken}'

  resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
    name: appInsightsName
    location: location
    tags: tags
    kind: 'web'
    properties: {
      Application_Type: 'web'
      Flow_Type: 'Bluefield'
      WorkspaceResourceId: logAnalyticsWorkspace.id
    }
  }

// ----------------------------------------------------
// Azure SQL (AAD only authentication, no SQL login/password)
// ----------------------------------------------------

@description('Name of the Azure SQL logical server')
param sqlServerName string = 'sql-${resourceToken}'

@description('Name of the Azure SQL database')
param sqlDatabaseName string = 'arclog'

// Base and conditional administrator properties (AAD)
var sqlServerBaseProps = {
  version: '12.0'
  minimalTlsVersion: '1.2'
  publicNetworkAccess: 'Enabled'
}
var sqlServerAdminProps = (!empty(userPrincipalId) && isUserPrincipal) ? {
  administrators: {
    administratorType: 'ActiveDirectory'
    login: 'aad-admin'
    sid: userPrincipalId
    tenantId: tenant().tenantId
    principalType: 'User'
    azureADOnlyAuthentication: true
  }
} : {}

// SQL Server
resource sqlServer 'Microsoft.Sql/servers@2024-11-01-preview' = {
  name: sqlServerName
  location: location
  tags: tags
  properties: union(sqlServerBaseProps, sqlServerAdminProps)
}

// Allow Azure services (0.0.0.0) firewall rule
resource sqlServerAllowAzureServices 'Microsoft.Sql/servers/firewallRules@2024-11-01-preview' = {
  parent: sqlServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// Optional: Allow the deploying client's current public IP
@description('Client public IPv4 address (e.g. 203.0.113.45) to allow through the SQL Server firewall. Leave empty to skip creating this rule.')
param clientPublicIp string = ''

resource sqlServerClientIpFirewallRule 'Microsoft.Sql/servers/firewallRules@2024-11-01-preview' = if (!empty(clientPublicIp)) {
  name: 'ClientIp'
  parent: sqlServer
  properties: {
    startIpAddress: clientPublicIp
    endIpAddress: clientPublicIp
  }
}

// SQL Database (S0 Standard)
resource sqlDatabase 'Microsoft.Sql/servers/databases@2024-11-01-preview' = {
  parent: sqlServer
  name: sqlDatabaseName
  location: location
  sku: {
    name: 'S0'
    tier: 'Standard'
  }
  properties: {}
}

// Create App Service
resource appService 'Microsoft.Web/sites@2022-03-01' = {
  name: appServiceName
  location: location
  tags: union(tags, {
    'azd-service-name': 'web'  // Add tag required by azd for deployment
  })
  identity: {
    type: 'SystemAssigned' // Add system-assigned managed identity for App Service
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      // Configure Linux with Python 3.12
      linuxFxVersion: 'PYTHON|3.12'
      alwaysOn: true
      // Required by FastAPI: start Gunicorn with Uvicorn workers
      appCommandLine: 'gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 app.main:app'
      // Enable application logging
      httpLoggingEnabled: true
      detailedErrorLoggingEnabled: true
      requestTracingEnabled: true
      logsDirectorySizeLimit: 35
      appSettings: [
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
        {
          name: 'AZURE_OPENAI_ENDPOINT'
          value: openAiAccount.properties.endpoint
        }
        {
          name: 'AZURE_OPENAI_API_VERSION'
          value: '2024-05-01-preview'
        }
        {
          name: 'AZURE_OPENAI_GPT_DEPLOYMENT'
          value: openAiGptDeploymentName
        }
        {
          name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT'
          value: openAiEmbeddingDeploymentName
        }
        {
          name: 'AZURE_SEARCH_SERVICE_URL'
          value: 'https://${searchService.name}.search.windows.net'
        }
        {
          name: 'AZURE_SEARCH_INDEX_NAME_INVENTORIES'
          value: searchIndexNameInventories
        }
        {
          name: 'AZURE_SEARCH_INDEX_NAME_INCIDENTS'
          value: searchIndexNameIncidents
        }
        {
          name: 'SYSTEM_PROMPT'
          value: systemPrompt
        }
        {
          name: 'AZURE_SQL_SERVER'
          value: '${sqlServer.name}${environment().suffixes.sqlServerHostname}'
        }
        {
          name: 'AZURE_SQL_DATABASE_NAME'
          value: sqlDatabaseName
        }
        {
          name: 'LOG_ANALYTICS_CUSTOMER_ID'
          value: logAnalyticsWorkspace.properties.customerId
        }
        {
          name: 'LOG_ANALYTICS_WORKSPACE_NAME'
          value: logAnalyticsWorkspace.name
        }
        {
          name: 'LOG_ANALYTICS_WORKSPACE_RESOURCE_ID'
          value: logAnalyticsWorkspace.id
        }
        {
          name: 'USE_AAD'
          value: '1'
        }
        {
          name: 'APPINSIGHTS_INSTRUMENTATIONKEY'
          value: appInsights.properties.InstrumentationKey
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
      ]
    }
  }
}

// ----------------------------------------------------
// System prompt parameter (multi-line for maintainability)
// ----------------------------------------------------
@description('System prompt injected into the application as SYSTEM_PROMPT app setting. Edit here instead of inline in the resource.')
@minLength(10)
param systemPrompt string = '''You are an infrastructure knowledge assistant answering about servers, incidents and ownership.
Use ONLY the information contained in the Sources section. If information is missing, say you don\'t know. Never invent data.

TOLERATE TYPOS & NORMALIZE:
- Accept minor typos / case differences / missing leading zeros in server IDs (srv1/SRV1/SRV01 => SRV001 if that exists).
- Normalize server_id pattern: PREFIX + digits. If digits length < canonical (3), zero-pad (SRV1 => SRV001). Remove extra zeros when comparing.
- Ignore hyphens/underscores/case when matching IDs or team names (auth_api_prod ~ auth-api-prod).
- For team / owner names allow edit distance 1 (Platfrom => Platform).
- If multiple candidates remain, list possible matches and ask user to clarify; do not guess.

ANSWER FORMAT:
- Use concise bullet points (<=5) unless user requests another format.
- Each factual bullet cites the server_id or incident identifier in parentheses.
- When summarizing multiple rows, group by environment or status.

RULES:
1. Use only facts from Sources.
2. Do not output internal reasoning.
3. Say 'insufficient information' in the user's language when data not found.
4. Do not include unrelated marketing or speculative content.

Now answer the user Query in the language of the user Query using only Sources.
Query: {query}
Sources:
{sources}'''

// ----------------------------------------------------
// Azure OpenAI service
// ----------------------------------------------------

@description('Name of the Azure OpenAI service')
param openAiServiceName string = 'ai-${resourceToken}'

@description('Azure OpenAI service SKU')
param openAiSkuName string = 'S0'

@description('GPT model deployment name')
param openAiGptDeploymentName string = 'gpt-4.1'

@description('GPT model name')
param openAiGptModelName string = 'gpt-4.1'

@description('GPT model version')
param openAiGptModelVersion string = '2025-04-14'

@description('Embedding model deployment name')
param openAiEmbeddingDeploymentName string = 'text-embedding-ada-002'

@description('Embedding model name')
param openAiEmbeddingModelName string = 'text-embedding-ada-002'

@description('Embedding model version')
param openAiEmbeddingModelVersion string = '2'

// Create OpenAI service
resource openAiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: openAiServiceName
  location: location
  tags: tags
  kind: 'OpenAI'
  identity: {
    type: 'SystemAssigned' // Add system-assigned managed identity for OpenAI
  }
  sku: {
    name: openAiSkuName
  }
  properties: {
    customSubDomainName: openAiServiceName // Required for Microsoft Entra ID authentication
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      ipRules: []
      virtualNetworkRules: []
    }
  }
}

// Deploy GPT model
resource openAiGptDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openAiAccount
  name: openAiGptDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: 20
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: openAiGptModelName
      version: openAiGptModelVersion
    }
  }
}

// Deploy Embedding model
resource openAiEmbeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openAiAccount
  name: openAiEmbeddingDeploymentName
  dependsOn: [
    openAiGptDeployment // Add explicit dependency to ensure sequential deployment
  ]
  sku: {
    name: 'Standard'
    capacity: 20
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: openAiEmbeddingModelName
      version: openAiEmbeddingModelVersion
    }
  }
}

// ----------------------------------------------------
// Azure AI Search service
// ----------------------------------------------------

@description('Name of the Azure AI Search service')
param searchServiceName string = 'srch-${resourceToken}'

@description('Azure AI Search service SKU')
@allowed([
  'basic'
  'standard'
  'standard2'
  'standard3'
])
param searchServiceSku string = 'standard'

@description('Search index name')
param searchIndexNameInventories string = 'index-inventories'
param searchIndexNameIncidents string = 'index-incidents'

// Update Search service properties to support network security
resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchServiceName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned' // Add system-assigned managed identity for Search
  }
  sku: {
    name: searchServiceSku
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    semanticSearch: 'free'
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
  }
}

// ----------------------------------------------------
// Storage account for document storage
// ----------------------------------------------------

@description('Name of the storage account')
param storageAccountName string = 'st${replace(resourceToken, '-', '')}'

@description('Name of the blob container for inventories')
param inventoriesContainerName string = 'inventories'

@description('Name of the blob container for incidents')
param incidentsContainerName string = 'incidents'

// Create Storage Account
resource storageAccount 'Microsoft.Storage/storageAccounts@2022-09-01' = {
  name: storageAccountName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    networkAcls: {
      defaultAction: 'Allow'
      ipRules: []
      virtualNetworkRules: []
    }
  }
}

// Create blob services
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2022-09-01' = {
  parent: storageAccount
  name: 'default'
}

// Create container for inventories
resource inventoriesContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2022-09-01' = {
  parent: blobService
  name: inventoriesContainerName
  properties: {
    publicAccess: 'None'
  }
}

// Create container for incidents
resource incidentsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2022-09-01' = {
  parent: blobService
  name: incidentsContainerName
  properties: {
    publicAccess: 'None'
  }
}

// Diagnostic settings for Azure SQL Server -> Log Analytics
resource sqlServerDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: sqlServer
  name: 'sqlServerDiagnostics'
  properties: {
    workspaceId: logAnalyticsWorkspace.id
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// Enable SQL Auditing to Azure Monitor (Log Analytics) at the server level
resource sqlServerAuditing 'Microsoft.Sql/servers/auditingSettings@2024-11-01-preview' = {
  name: 'default'
  parent: sqlServer
  properties: {
    state: 'Enabled'
    isAzureMonitorTargetEnabled: true
    retentionDays: 0
    auditActionsAndGroups: [
      'SUCCESSFUL_DATABASE_AUTHENTICATION_GROUP'
      'FAILED_DATABASE_AUTHENTICATION_GROUP'
      'BATCH_COMPLETED_GROUP'
    ]
  }
}

// Diagnostic settings for Azure SQL Database -> Log Analytics
resource sqlDatabaseDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: sqlDatabase
  name: 'sqlDatabaseDiagnostics'
  properties: {
    workspaceId: logAnalyticsWorkspace.id
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// Enable SQL Auditing to Azure Monitor (Log Analytics) at the database level
resource sqlDatabaseAuditing 'Microsoft.Sql/servers/databases/auditingSettings@2024-11-01-preview' = {
  name: 'default'
  parent: sqlDatabase
  properties: {
    state: 'Enabled'
    isAzureMonitorTargetEnabled: true
    retentionDays: 0
    auditActionsAndGroups: [
      'SUCCESSFUL_DATABASE_AUTHENTICATION_GROUP'
      'FAILED_DATABASE_AUTHENTICATION_GROUP'
      'BATCH_COMPLETED_GROUP'
    ]
  }
}

// Diagnostic settings for Storage Account -> Log Analytics
resource storageDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: storageAccount
  name: 'storageDiagnostics'
  properties: {
    workspaceId: logAnalyticsWorkspace.id
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// Diagnostic settings for Azure AI Search -> Log Analytics
resource searchDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: searchService
  name: 'searchDiagnostics'
  properties: {
    workspaceId: logAnalyticsWorkspace.id
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// Diagnostic settings for Azure OpenAI -> Log Analytics
resource openAiDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: openAiAccount
  name: 'openAiDiagnostics'
  properties: {
    workspaceId: logAnalyticsWorkspace.id
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// ----------------------------------------------------
// Role assignments
// ----------------------------------------------------

// Assign 'Cognitive Services OpenAI User' role to App Service to call OpenAI
resource appServiceOpenAIUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appService.id, openAiAccount.id, 'Cognitive Services OpenAI User')
  scope: openAiAccount
  properties: {
    principalId: appService.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd') // Cognitive Services OpenAI User
  }
}

// Assign 'Search Index Data Reader' role to OpenAI to query search data
resource openAISearchDataReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openAiAccount.id, searchService.id, 'Search Index Data Reader')
  scope: searchService
  properties: {
    principalId: openAiAccount.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f') // Search Index Data Reader
  }
}

// Assign 'Search Service Contributor' role to OpenAI for index schema access
resource openAISearchContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openAiAccount.id, searchService.id, 'Search Service Contributor')
  scope: searchService
  properties: {
    principalId: openAiAccount.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0') // Search Service Contributor
  }
}

// Assign 'Search Index Data Reader' role to App Service so it can query search indexes using AAD (managed identity)
resource appServiceSearchDataReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appService.id, searchService.id, 'Search Index Data Reader')
  scope: searchService
  properties: {
    principalId: appService.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f') // Search Index Data Reader
  }
}

// Assign 'Storage Blob Data Contributor' role to OpenAI for file access
resource openAIStorageBlobDataContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openAiAccount.id, storageAccount.id, 'Storage Blob Data Contributor')
  scope: storageAccount
  properties: {
    principalId: openAiAccount.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe') // Storage Blob Data Contributor
  }
}

// Assign 'Cognitive Services OpenAI Contributor' role to Search to access OpenAI embeddings
resource searchOpenAIContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, openAiAccount.id, 'Cognitive Services OpenAI Contributor')
  scope: openAiAccount
  properties: {
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a001fd3d-188f-4b5d-821b-7da978bf7442') // Cognitive Services OpenAI Contributor
  }
}

// Assign 'Storage Blob Data Reader' role to Search for document and chunk access
resource searchStorageBlobDataReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, storageAccount.id, 'Storage Blob Data Reader')
  scope: storageAccount
  properties: {
    principalId: searchService.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1') // Storage Blob Data Reader
  }
}

// Assign 'Storage Blob Data Contributor' role to the user running the deployment
resource userStorageBlobDataContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId) && isUserPrincipal) {
  name: guid(storageAccount.id, userPrincipalId, 'Storage Blob Data Contributor')
  scope: storageAccount
  properties: {
    principalId: userPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe') // Storage Blob Data Contributor
  }
}

// Assign 'Search Service Contributor' role to the user running the deployment
resource userSearchServiceContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId) && isUserPrincipal) {
  name: guid(searchService.id, userPrincipalId, 'Search Service Contributor')
  scope: searchService
  properties: {
    principalId: userPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0') // Search Service Contributor
  }
}

// Assign 'Search Index Data Reader' role to the user running the deployment so local CLI-based execution can query index documents
resource userSearchIndexDataReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId) && isUserPrincipal) {
  name: guid(searchService.id, userPrincipalId, 'Search Index Data Reader')
  scope: searchService
  properties: {
    principalId: userPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f') // Search Index Data Reader
  }
}

// Assign 'Cognitive Services OpenAI Contributor' role to the user running the deployment
resource userOpenAIContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId) && isUserPrincipal) {
  name: guid(openAiAccount.id, userPrincipalId, 'Cognitive Services OpenAI Contributor')
  scope: openAiAccount
  properties: {
    principalId: userPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a001fd3d-188f-4b5d-821b-7da978bf7442') // Cognitive Services OpenAI Contributor
  }
}

// Grant App Service managed identity read access to the Log Analytics workspace
resource appServiceLogAnalyticsReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appService.id, logAnalyticsWorkspace.id, 'Log Analytics Reader')
  scope: logAnalyticsWorkspace
  properties: {
    principalId: appService.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '73c42c96-874c-492b-b04d-ab87d138a893') // Log Analytics Reader
  }
}

// Optionally grant the deploying user read access to the Log Analytics workspace
resource userLogAnalyticsReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId) && isUserPrincipal) {
  name: guid(logAnalyticsWorkspace.id, userPrincipalId, 'Log Analytics Reader')
  scope: logAnalyticsWorkspace
  properties: {
    principalId: userPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '73c42c96-874c-492b-b04d-ab87d138a893') // Log Analytics Reader
  }
}

// ----------------------------------------------------
// Output values
// ----------------------------------------------------

output AZURE_OPENAI_ENDPOINT string = openAiAccount.properties.endpoint
output AZURE_OPENAI_GPT_DEPLOYMENT string = openAiGptDeploymentName
output AZURE_OPENAI_EMBEDDING_DEPLOYMENT string = openAiEmbeddingDeploymentName
output AZURE_SEARCH_INDEX_NAME_INVENTORIES string = 'index-inventories'
output AZURE_SEARCH_INDEX_NAME_INCIDENTS string = 'index-incidents'
output AZURE_SEARCH_SERVICE_URL string = 'https://${searchService.name}.search.windows.net'
output AZURE_STORAGE_ACCOUNT_NAME string = storageAccount.name
output AZURE_SEARCH_SERVICE_NAME string = searchService.name
output AZURE_SQL_DATABASE_NAME string = sqlDatabaseName
output AZURE_SQL_SERVER string = '${sqlServer.name}${environment().suffixes.sqlServerHostname}'
output AZURE_OPENAI_API_VERSION string = '2024-05-01-preview'
output USE_AAD int = 1
output SYSTEM_PROMPT string = 'You are an infrastructure knowledge assistant answering about servers, incidents and ownership.\nUse ONLY the information contained in the Sources section. If information is missing, state you don\'t know. Never invent data.\n\nTOLERATE TYPOS & NORMALIZE:\n- Accept minor typos / case differences / missing leading zeros in server IDs (e.g. srv1, SRV1, SRV01 => SRV001 if that exists; payment-gw-stagin => payment-gw-staging).\n- Normalize server_id pattern: PREFIX + digits. If digits length < canonical (3), zero‑pad (SRV1 => SRV001). Remove extra zeros when comparing.\n- Ignore hyphens/underscores/case when matching IDs or team names (auth_api_prod ~ auth-api-prod).\n- For team / owner names allow edit distance 1 (Platfrom => Platform).\n- If multiple candidates remain, list the possible matches and ask the user to clarify; do not guess.\n\nANSWER FORMAT:\n- Provide concise bullet points (<=5) unless user requests another format.\n- For each factual bullet cite the server_id or incident identifier in parentheses.\n- If summarizing multiple rows, group by environment or status.\n\nRULES:\n1. Use only facts from Sources.\n2. Do not output internal reasoning.\n3. Clearly say \'insufficient information\' in the user\'s language when data not found.\n4. Do not include unrelated marketing or speculative content.\n\nNow answer the user Query in the language of the user Query using only Sources.\nQuery: {query}\nSources:\n{sources}'
output AZURE_APP_SERVICE_NAME string = appService.name
output LOG_ANALYTICS_WORKSPACE_RESOURCE_ID string = logAnalyticsWorkspace.id
output LOG_ANALYTICS_WORKSPACE_NAME string = logAnalyticsWorkspace.name
output LOG_ANALYTICS_CUSTOMER_ID string = logAnalyticsWorkspace.properties.customerId
output APPINSIGHTS_INSTRUMENTATIONKEY string = appInsights.properties.InstrumentationKey
output APPLICATIONINSIGHTS_CONNECTION_STRING string = appInsights.properties.ConnectionString

// ----------------------------------------------------
// App Service diagnostics settings
// ----------------------------------------------------

// Create Log Analytics workspace for App Service logs
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'law-${resourceToken}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

// Configure diagnostic settings for the App Service
resource appServiceDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: appService
  name: 'appServiceDiagnostics'
  properties: {
    workspaceId: logAnalyticsWorkspace.id
    logs: [
      {
        category: 'AppServiceHTTPLogs'
        enabled: true
      }
      {
        category: 'AppServiceConsoleLogs'
        enabled: true
      }
      {
        category: 'AppServiceAppLogs'
        enabled: true
      }
      {
        category: 'AppServiceAuditLogs'
        enabled: true
      }
      {
        category: 'AppServiceIPSecAuditLogs'
        enabled: true
      }
      {
        category: 'AppServicePlatformLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}
