// Grants "Cognitive Services User" on an existing Document Intelligence /
// Cognitive Services account to a principal. Deployed in the account's resource
// group (cross-RG) from the parent module.

targetScope = 'resourceGroup'

@description('Existing Cognitive Services / Document Intelligence account name.')
param accountName string

@description('Principal id to grant the role to.')
param principalId string

@description('Cognitive Services User role definition GUID.')
param roleCognitiveServicesUser string

resource account 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: accountName
}

resource raCognitiveUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, principalId, roleCognitiveServicesUser)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleCognitiveServicesUser)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
