// Grants AcrPull on an existing ACR to a principal. Deployed in the ACR's
// resource group (cross-RG) from the parent module.

targetScope = 'resourceGroup'

@description('Existing ACR name.')
param acrName string

@description('Principal id to grant AcrPull to.')
param principalId string

@description('AcrPull role definition GUID.')
param roleAcrPull string

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource raAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, principalId, roleAcrPull)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleAcrPull)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
