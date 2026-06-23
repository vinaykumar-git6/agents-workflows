# Deploy the awb-ocr-worker PRIVATELY to Azure Container Apps in vnet-ek.
#
# Two phases:
#   1. Build the container image into ACR (Bicep can't build images).
#   2. Deploy main.bicep, which adds the Container App (internal ingress only)
#      to the EXISTING internal environment (cae-skycargo-internal) plus RBAC.
#
# Run from this folder:  ./deploy.ps1

$ErrorActionPreference = 'Stop'

# ---- Settings (keep in sync with main.bicepparam) ----
$RG            = 'emirates-ai-usecase'
$ACR          = 'acrvk012826'                   # existing ACR
$ACR_RG       = 'azure-vk-rg'                    # resource group that holds the ACR
$IMAGE        = 'awb-ocr-worker:v2'
$SOURCE_DIR   = '../../awb-ocr-worker'           # app source (Dockerfile lives here)

# ---- 1. Build the image into the existing ACR (no local Docker) ----
az acr build -g $ACR_RG -r $ACR -t $IMAGE $SOURCE_DIR

# ---- 2. Deploy the private ACA app + RBAC ----
az deployment group create `
    --resource-group $RG `
    --template-file main.bicep `
    --parameters main.bicepparam

# ---- 3. Show the internal FQDN (reachable only from inside vnet-ek) ----
Write-Host "`nInternal FQDN (private, no public ingress):"
az containerapp show -g $RG -n awb-ocr-worker --query properties.configuration.ingress.fqdn -o tsv
