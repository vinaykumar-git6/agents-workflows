using './main.bicep'

param location = 'uaenorth'

// Existing storage account that holds the uploaded PDFs.
param storageAccountName = 'awbstorageek'
param blobContainerName = 'awb-input'

// Optional: narrow events to the pdf folder only. Leave '' to watch the whole container.
param blobSubjectPrefix = '/blobServices/default/containers/awb-input/blobs/pdf/'

// Service Bus namespace must be globally unique.
param serviceBusNamespaceName = 'awb-sb-ek'
param serviceBusSku = 'Premium'
param queueName = 'aws-splitter-q'

param systemTopicName = 'awb-blob-events'
param eventSubscriptionName = 'awb-blob-to-splitter'

// Private networking (hub VNet + private DNS zones live in azure-vk-hub).
param networkResourceGroup = 'azure-vk-hub'
param vnetName = 'vnet-hub'
param privateEndpointSubnetName = 'snet-private-endpoints'
param serviceBusPrivateEndpointName = 'pe-awb-servicebus'
param storagePrivateEndpointName = 'pe-awb-blob'

param tags = {
  workload: 'skycargo-awb'
  component: 'file-events'
  environment: 'dev'
}
