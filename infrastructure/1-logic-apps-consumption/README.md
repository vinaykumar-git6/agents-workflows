# AAWB Ingest Consumption Logic App

This module deploys a Consumption Logic App named `aawb-ingest` with this flow:

1. Trigger: SharePoint file created in a specific folder.
2. Action: Read file content from SharePoint.
3. Action: Write file into Azure Blob Storage in configured path.

It also deploys:

1. A storage account for PDF storage.
2. The target blob container.
3. RBAC assignment (`Storage Blob Data Contributor`) to the Logic App managed identity.

## Files

- `main.bicep`
- `main.bicepparam`
- `workflow-definition.json`

## Deploy

```powershell
az deployment group create `
  --resource-group <rg-name> `
  --template-file main.bicep `
  --parameters main.bicepparam
```

## Important

After deployment, open both API connections in Azure portal and authorize them:

- SharePoint connection (`sharepointonline-*`)
- Azure Blob connection (`azureblob-*`)

The workflow uses values from `main.bicepparam` for SharePoint and Blob paths.
