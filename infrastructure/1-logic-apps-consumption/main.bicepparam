using './main.bicep'

param location = 'uaenorth'
param logicAppName = 'aawb-ingest'

param sharePointConnectionName = 'sharepointonline-aawb-ingest'
param sharePointConnectionDisplayName = 'SharePoint - AAWB Ingest'

param blobConnectionName = 'azureblob-aawb-ingest'
param blobConnectionDisplayName = 'Azure Blob - AAWB Ingest'

// Fill with your storage account where the file should be copied.
param blobStorageAccountName = 'awbstorageek'
param storageAccountSku = 'Standard_LRS'

// Fill with your SharePoint details.
param sharePointSiteAddress = 'https://microsofteur.sharepoint.com/sites/AWB'
param sharePointLibraryName = 'Documents'
param sharePointFolderPath = '/AWB'

// Fill with target blob path details.
param blobContainerName = 'awb-input'
param blobFolderPath = 'pdf'

param tags = {
  workload: 'skycargo-awb'
  component: 'logicapp-consumption-ingest'
  environment: 'dev'
}
