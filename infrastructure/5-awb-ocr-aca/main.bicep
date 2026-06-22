// Deploy the awb-ocr-worker PRIVATELY to Azure Container Apps inside vnet-ek.
//
// Reuses the existing internal (VNet-injected) Container Apps environment that
// was created for the splitter (cae-skycargo-internal). Adds a new internal-only
// Container App plus the RBAC its managed identity needs:
//   * AcrPull on the container registry (cross-RG module)
//   * Storage Blob Data Contributor on the data storage account (keyless)
//   * Azure Service Bus Data Receiver on the namespace (consume awb-worker-q)
//   * Cognitive Services User on the Document Intelligence account (cross-RG)
//
// Build the image into ACR BEFORE deploying (see deploy.ps1).

targetScope = 'resourceGroup'

@description('Azure region.')
param location string = resourceGroup().location

@description('Existing internal Container Apps environment (created by the splitter).')
param environmentName string = 'cae-skycargo-internal'

@description('Existing Azure Container Registry name.')
param acrName string

@description('Resource group that holds the Azure Container Registry.')
param acrResourceGroup string = 'azure-vk-rg'

@description('Container image reference, e.g. <acr>.azurecr.io/awb-ocr-worker:v1.')
param containerImage string

@description('Container App name.')
param appName string = 'awb-ocr-worker'

@description('Existing data storage account.')
param storageAccountName string = 'awbstorageek'

@description('Output blob container for OCR artifacts.')
param outputContainerName string = 'awb-output'

@description('Existing Service Bus namespace that holds the worker queue.')
param serviceBusNamespaceName string = 'awb-sb-ek'

@description('Service Bus queue the worker consumes.')
param queueName string = 'awb-worker-q'

@description('Document Intelligence (Form Recognizer) account name.')
param docIntelAccountName string = 'docintelligencmbc'

@description('Resource group of the Document Intelligence account.')
param docIntelResourceGroup string = 'logicapp-rg'

@description('Document Intelligence endpoint.')
param docIntelEndpoint string = 'https://docintelligencmbc.cognitiveservices.azure.com/'

@description('Document Intelligence model id.')
param docIntelModel string = 'prebuilt-layout'

@description('Microsoft Foundry (AI Services) account name hosting the chat model.')
param foundryAccountName string = 'mydevfoundry0603'

@description('Resource group of the Foundry account.')
param foundryResourceGroup string = 'logicapp-rg'

@description('Azure OpenAI / Foundry endpoint.')
param azureOpenAiEndpoint string = 'https://mydevfoundry0603.cognitiveservices.azure.com/'

@description('Chat model deployment name used by the AWB agent.')
param azureOpenAiDeployment string = 'gpt-5.4'

@description('Azure OpenAI API version.')
param azureOpenAiApiVersion string = '2024-12-01-preview'

@description('Container target port.')
param targetPort int = 8000

@description('Tags applied to resources.')
param tags object = {
  workload: 'skycargo-awb'
  component: 'awb-ocr-aca'
}

var roleAcrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var roleStorageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var roleServiceBusDataReceiver = '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
var roleServiceBusDataSender = '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
var roleCognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var roleCognitiveServicesOpenAiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

// ---------------------------------------------------------------------------
// Existing resources
// ---------------------------------------------------------------------------

resource acaEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
  scope: resourceGroup(acrResourceGroup)
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' existing = {
  name: serviceBusNamespaceName
}

// ---------------------------------------------------------------------------
// Container App (internal ingress only)
// ---------------------------------------------------------------------------

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: acaEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: appName
          image: containerImage
          resources: {
            cpu: json('1.0')
            memory: '2.0Gi'
          }
          env: [
            {
              name: 'BLOB_ACCOUNT_URL'
              value: 'https://${storageAccountName}.blob.${environment().suffixes.storage}'
            }
            {
              name: 'BLOB_OUTPUT_CONTAINER'
              value: outputContainerName
            }
            {
              name: 'SERVICEBUS_NAMESPACE'
              value: '${serviceBusNamespaceName}.servicebus.windows.net'
            }
            {
              name: 'SERVICEBUS_QUEUE'
              value: queueName
            }
            {
              name: 'DOCUMENTINTELLIGENCE_ENDPOINT'
              value: docIntelEndpoint
            }
            {
              name: 'DOCUMENTINTELLIGENCE_MODEL'
              value: docIntelModel
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: azureOpenAiEndpoint
            }
            {
              name: 'AZURE_OPENAI_DEPLOYMENT'
              value: azureOpenAiDeployment
            }
            {
              name: 'AZURE_OPENAI_API_VERSION'
              value: azureOpenAiApiVersion
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 5
        rules: [
          {
            name: 'sb-queue-length'
            custom: {
              type: 'azure-servicebus'
              identity: 'system'
              metadata: {
                namespace: serviceBusNamespaceName
                queueName: queueName
                messageCount: '5'
              }
            }
          }
        ]
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Role assignments for the app's managed identity
// ---------------------------------------------------------------------------

module raAcrPull 'acr-pull.bicep' = {
  name: 'ocr-acrpull'
  scope: resourceGroup(acrResourceGroup)
  params: {
    acrName: acrName
    principalId: containerApp.identity.principalId
    roleAcrPull: roleAcrPull
  }
}

module raCognitive 'cognitive-user.bicep' = {
  name: 'ocr-cognitive-user'
  scope: resourceGroup(docIntelResourceGroup)
  params: {
    accountName: docIntelAccountName
    principalId: containerApp.identity.principalId
    roleCognitiveServicesUser: roleCognitiveServicesUser
  }
}

// Foundry chat model access for the AWB agent (Cognitive Services OpenAI User).
module raFoundryOpenAi 'cognitive-user.bicep' = {
  name: 'ocr-foundry-openai-user'
  scope: resourceGroup(foundryResourceGroup)
  params: {
    accountName: foundryAccountName
    principalId: containerApp.identity.principalId
    roleCognitiveServicesUser: roleCognitiveServicesOpenAiUser
  }
}

resource raBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, containerApp.id, roleStorageBlobDataContributor)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleStorageBlobDataContributor)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource raSbReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBusNamespace.id, containerApp.id, roleServiceBusDataReceiver)
  scope: serviceBusNamespace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleServiceBusDataReceiver)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Sender is required because the consumer reschedules messages (exponential
// backoff) via sender.schedule_messages on the same queue.
resource raSbSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBusNamespace.id, containerApp.id, roleServiceBusDataSender)
  scope: serviceBusNamespace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleServiceBusDataSender)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output containerAppId string = containerApp.id
output internalFqdn string = containerApp.properties.configuration.ingress.fqdn
output appPrincipalId string = containerApp.identity.principalId
