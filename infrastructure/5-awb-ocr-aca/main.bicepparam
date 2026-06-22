using './main.bicep'

param location = 'uaenorth'

param environmentName = 'cae-skycargo-internal'

param acrName = 'acrvk012826'
param acrResourceGroup = 'azure-vk-rg'
param containerImage = 'acrvk012826.azurecr.io/awb-ocr-worker:v1'

param appName = 'awb-ocr-worker'

param storageAccountName = 'awbstorageek'
param outputContainerName = 'awb-output'

param serviceBusNamespaceName = 'awb-sb-ek'
param queueName = 'awb-worker-q'

param docIntelAccountName = 'docintelligencmbc'
param docIntelResourceGroup = 'logicapp-rg'
param docIntelEndpoint = 'https://docintelligencmbc.cognitiveservices.azure.com/'
param docIntelModel = 'prebuilt-layout'

param targetPort = 8000

param tags = {
  workload: 'skycargo-awb'
  component: 'awb-ocr-aca'
  environment: 'dev'
}
