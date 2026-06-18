# Deploy AWB PDF Splitter privately to Azure Container Apps (no public ingress).
# Reuses existing RG + VNet. Run from the awb-pdf-splitter/ folder.

$ErrorActionPreference = "Stop"

# ---- Variables (edit if needed) ----
$RG           = "emirates-ai-usecase"
$LOCATION     = "uaenorth"
$ACR          = "skycargoacr$(Get-Random -Maximum 99999)"   # must be globally unique
$ENV_NAME     = "cae-skycargo-internal"
$APP          = "awb-pdf-splitter"
$VNET         = "vnet-ek"
$INFRA_SUBNET = "snet-aca-infra"
$SUBNET_CIDR  = "10.10.3.0/27"

# Blob storage target for split AWBs (keyless, managed identity).
$DATA_STORAGE      = "stskycargoawbdata"
$BLOB_ACCOUNT_URL  = "https://$DATA_STORAGE.blob.core.windows.net"
$BLOB_CONTAINER    = "awb-input"
$BLOB_PATH_TEMPLATE = "{document_name}/{date}/{flight}/{awb}.pdf"

# ---- 1. Container registry + build image in ACR (no local Docker needed) ----
az acr create -g $RG -n $ACR --sku Standard
az acr build -g $RG -r $ACR -t "$APP`:v1" .

# ---- 2. Dedicated infra subnet for the ACA environment (min /27) ----
az network vnet subnet create -g $RG --vnet-name $VNET -n $INFRA_SUBNET `
  --address-prefixes $SUBNET_CIDR
$SUBNET_ID = az network vnet subnet show -g $RG --vnet-name $VNET -n $INFRA_SUBNET --query id -o tsv

# ---- 3. INTERNAL (private) Container Apps environment — VNet-injected, no public IP ----
az containerapp env create -g $RG -n $ENV_NAME --location $LOCATION `
  --infrastructure-subnet-resource-id $SUBNET_ID `
  --internal-only true

# ---- 4. Deploy the app with INTERNAL ingress only ----
$ACR_LOGIN = az acr show -g $RG -n $ACR --query loginServer -o tsv
az containerapp create -g $RG -n $APP --environment $ENV_NAME `
  --image "$ACR_LOGIN/$APP`:v1" `
  --target-port 8000 `
  --ingress internal `
  --registry-server $ACR_LOGIN `
  --system-assigned `
  --min-replicas 1 --max-replicas 5 `
  --cpu 1.0 --memory 2.0Gi `
  --env-vars "BLOB_ACCOUNT_URL=$BLOB_ACCOUNT_URL" "BLOB_CONTAINER=$BLOB_CONTAINER" "BLOB_PATH_TEMPLATE=$BLOB_PATH_TEMPLATE"

# ---- 5. Grant the app's managed identity pull rights on ACR ----
$APP_PRINCIPAL = az containerapp show -g $RG -n $APP --query identity.principalId -o tsv
$ACR_ID = az acr show -g $RG -n $ACR --query id -o tsv
az role assignment create --assignee $APP_PRINCIPAL --role AcrPull --scope $ACR_ID

# ---- 6. Grant the app's managed identity write access to the data storage account ----
$DATA_ID = az storage account show -g $RG -n $DATA_STORAGE --query id -o tsv
az role assignment create --assignee $APP_PRINCIPAL `
  --role "Storage Blob Data Contributor" --scope $DATA_ID

Write-Host "Done. The app is reachable ONLY on its internal FQDN from inside $VNET:"
az containerapp show -g $RG -n $APP --query properties.configuration.ingress.fqdn -o tsv
