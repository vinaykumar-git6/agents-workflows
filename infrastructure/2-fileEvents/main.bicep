// Blob Created -> Event Grid -> Service Bus queue (pointer-only message)
//
// Flow:
//   1. A blob is created in the storage account (by the aawb-ingest Logic App).
//   2. The storage account's Event Grid system topic raises a
//      Microsoft.Storage.BlobCreated event.
//   3. An Event Grid subscription delivers that event to the Service Bus
//      queue 'aws-splitter-q'.
//
// The Event Grid event payload contains a POINTER to the blob
// (data.url = https://<account>.blob.core.windows.net/<container>/<path>),
// NOT the file content itself.
//
// Delivery uses the system topic's MANAGED IDENTITY (keyless). The identity is
// granted 'Azure Service Bus Data Sender' on the namespace.

targetScope = 'resourceGroup'

@description('Azure region.')
param location string = resourceGroup().location

@description('Existing storage account that receives the uploaded PDFs.')
param storageAccountName string

@description('Blob container to watch for new blobs.')
param blobContainerName string

@description('Blob path prefix filter (for example: /blobServices/default/containers/awb-input/blobs/pdf/).')
param blobSubjectPrefix string = ''

@description('Service Bus namespace name (must be globally unique).')
param serviceBusNamespaceName string

@description('Service Bus namespace SKU.')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param serviceBusSku string = 'Standard'

@description('Service Bus queue name.')
param queueName string = 'aws-splitter-q'

@description('Event Grid system topic name.')
param systemTopicName string = 'awb-blob-events'

@description('Event Grid subscription name.')
param eventSubscriptionName string = 'awb-blob-to-splitter'

@description('Tags applied to resources.')
param tags object = {
  workload: 'skycargo-awb'
  component: 'file-events'
}

var roleServiceBusDataSender = '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: serviceBusNamespaceName
  location: location
  tags: tags
  sku: {
    name: serviceBusSku
    tier: serviceBusSku
  }
  properties: {
    minimumTlsVersion: '1.2'
  }
}

resource queue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: serviceBusNamespace
  name: queueName
  properties: {
    lockDuration: 'PT1M'
    maxDeliveryCount: 10
    deadLetteringOnMessageExpiration: true
    enablePartitioning: false
  }
}

resource systemTopic 'Microsoft.EventGrid/systemTopics@2022-06-15' = {
  name: systemTopicName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    source: storageAccount.id
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

// Grant the system topic identity permission to send to the Service Bus namespace.
resource raSystemTopicSbSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBusNamespace.id, systemTopic.id, roleServiceBusDataSender)
  scope: serviceBusNamespace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleServiceBusDataSender)
    principalId: systemTopic.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource eventSubscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2022-06-15' = {
  parent: systemTopic
  name: eventSubscriptionName
  properties: {
    deliveryWithResourceIdentity: {
      identity: {
        type: 'SystemAssigned'
      }
      destination: {
        endpointType: 'ServiceBusQueue'
        properties: {
          resourceId: queue.id
        }
      }
    }
    filter: {
      includedEventTypes: [
        'Microsoft.Storage.BlobCreated'
      ]
      subjectBeginsWith: empty(blobSubjectPrefix)
        ? '/blobServices/default/containers/${blobContainerName}/blobs/'
        : blobSubjectPrefix
      enableAdvancedFilteringOnArrays: true
    }
    eventDeliverySchema: 'EventGridSchema'
    retryPolicy: {
      maxDeliveryAttempts: 30
      eventTimeToLiveInMinutes: 1440
    }
  }
  dependsOn: [
    raSystemTopicSbSender
  ]
}

output serviceBusNamespaceId string = serviceBusNamespace.id
output queueId string = queue.id
output systemTopicId string = systemTopic.id
output systemTopicPrincipalId string = systemTopic.identity.principalId
