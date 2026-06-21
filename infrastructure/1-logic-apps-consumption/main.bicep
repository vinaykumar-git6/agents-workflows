// Consumption Logic App: SharePoint PDF upload -> Azure Blob Storage

targetScope = 'resourceGroup'

@description('Azure region for the Consumption Logic App and API connections.')
param location string = resourceGroup().location

@description('Consumption Logic App name.')
param logicAppName string = 'aawb-ingest'

@description('Name for the SharePoint API connection resource.')
param sharePointConnectionName string = 'sharepointonline-aawb-ingest'

@description('Display name for the SharePoint API connection.')
param sharePointConnectionDisplayName string = 'SharePoint - AAWB Ingest'

@description('Name for the Azure Blob API connection resource.')
param blobConnectionName string = 'azureblob-aawb-ingest'

@description('Display name for the Azure Blob API connection.')
param blobConnectionDisplayName string = 'Azure Blob - AAWB Ingest'

@description('Storage account name used by Azure Blob connector.')
param blobStorageAccountName string

@description('SharePoint site address (for example: https://contoso.sharepoint.com/sites/Docs).')
param sharePointSiteAddress string

@description('SharePoint document library name (for example: Shared Documents).')
param sharePointLibraryName string

@description('SharePoint folder path to monitor (for example: /AWB-Incoming).')
param sharePointFolderPath string

@description('Azure Blob container name.')
param blobContainerName string

@description('Azure Blob folder path where files are stored (for example: awb/input).')
param blobFolderPath string

@description('Storage account SKU for PDF storage.')
@allowed([
  'Standard_LRS'
  'Standard_GRS'
  'Standard_RAGRS'
  'Standard_ZRS'
  'Premium_LRS'
])
param storageAccountSku string = 'Standard_LRS'

@description('Tags applied to resources.')
param tags object = {
  workload: 'skycargo-awb'
  component: 'logicapp-consumption-ingest'
}

var roleStorageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: blobStorageAccountName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: storageAccountSku
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource blobContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: blobContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource sharePointManagedApi 'Microsoft.Web/locations/managedApis@2016-06-01' existing = {
  scope: subscription()
  name: '${location}/sharepointonline'
}

resource blobManagedApi 'Microsoft.Web/locations/managedApis@2016-06-01' existing = {
  scope: subscription()
  name: '${location}/azureblob'
}

resource sharePointConnection 'Microsoft.Web/connections@2016-06-01' = {
  name: sharePointConnectionName
  location: location
  tags: tags
  properties: {
    displayName: sharePointConnectionDisplayName
    api: {
      id: sharePointManagedApi.id
    }
  }
}

resource blobConnection 'Microsoft.Web/connections@2016-06-01' = {
  name: blobConnectionName
  location: location
  tags: tags
  properties: {
    displayName: blobConnectionDisplayName
    // Keyless: use managed identity instead of account key.
    #disable-next-line BCP037 BCP089
    parameterValueSet: {
      name: 'managedIdentityAuth'
      values: {}
    }
    api: {
      id: blobManagedApi.id
    }
  }
}

resource logicApp 'Microsoft.Logic/workflows@2019-05-01' = {
  name: logicAppName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    state: 'Enabled'
    definition: loadJsonContent('workflow-definition.json')
    parameters: {
      '$connections': {
        value: {
          sharepointonline: {
            connectionId: sharePointConnection.id
            connectionName: sharePointConnection.name
            id: sharePointManagedApi.id
          }
          azureblob: {
            connectionId: blobConnection.id
            connectionName: blobConnection.name
            id: blobManagedApi.id
            connectionProperties: {
              authentication: {
                type: 'ManagedServiceIdentity'
              }
            }
          }
        }
      }
      spSiteAddress: {
        value: sharePointSiteAddress
      }
      spLibraryName: {
        value: sharePointLibraryName
      }
      spFolderPath: {
        value: sharePointFolderPath
      }
      blobStorageAccountName: {
        value: blobStorageAccountName
      }
      blobContainerName: {
        value: blobContainerName
      }
      blobFolderPath: {
        value: blobFolderPath
      }
    }
  }
}

resource roleAssignmentBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, logicApp.id, roleStorageBlobDataContributor)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleStorageBlobDataContributor)
    principalId: logicApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output logicAppId string = logicApp.id
output logicAppNameOut string = logicApp.name
output sharePointConnectionId string = sharePointConnection.id
output blobConnectionId string = blobConnection.id
output storageAccountId string = storageAccount.id
output blobContainerResourceId string = blobContainer.id
