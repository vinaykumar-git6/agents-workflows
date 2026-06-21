# 2-fileEvents

Publishes blob-created events to Event Grid and forwards them to a Service Bus
queue. The queue message carries a **pointer to the blob**, not the file itself.

## Flow

```
Blob created (awb-input/pdf/...)  ->  Event Grid system topic  ->  Service Bus queue (aws-splitter-q)
```

## Resources

- Service Bus namespace + queue `aws-splitter-q`
- Event Grid system topic on the storage account
- Event Grid subscription filtering `Microsoft.Storage.BlobCreated`
- RBAC: system topic managed identity granted `Azure Service Bus Data Sender`

## Message content

The delivered event uses the Event Grid schema. The blob pointer is in:

- `data.url` — full blob URL, e.g. `https://awbstorageek.blob.core.windows.net/awb-input/pdf/<timestamp>/<file>`
- `subject` — `/blobServices/default/containers/awb-input/blobs/pdf/<timestamp>/<file>`

The actual file content is **never** placed on the queue. The consumer reads the
blob using the URL pointer.

## Prerequisites

- The storage account (`storageAccountName`) already exists.

## Deploy

```powershell
az deployment group create `
  --resource-group emirates-ai-usecase `
  --template-file main.bicep `
  --parameters main.bicepparam
```
