# AWB PDF Splitter

Splits a single multi-AWB PDF (many Air Waybill numbers in one file) into one PDF per AWB.
Exposed as a small FastAPI service and deployed **privately** to Azure Container Apps (no public ingress).

## How AWB detection works

- AWB number format: `NNN-NNNNNNNN` (3-digit airline prefix + 8-digit serial), e.g. `176-12345678`.
- Each page is scanned for an AWB number. A new AWB number starts a new output PDF;
  pages with no AWB number are treated as continuation pages of the current bill.
- Assumes **text-based** PDFs. For scanned/image PDFs, add OCR (e.g. `ocrmypdf`) before splitting.

## Run locally

```powershell
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## API

| Method | Path             | Description                                            |
|--------|------------------|--------------------------------------------------------|
| GET    | `/health`        | Health probe.                                          |
| POST   | `/split`         | Upload a PDF (`file`), returns a ZIP of per-AWB PDFs.   |
| POST   | `/split/manifest`| Upload a PDF (`file`), returns detected AWB list (JSON).|
| POST   | `/split/blob`    | Split and write each AWB to blob storage (JSON result).|

Example:

```bash
curl -X POST "http://localhost:8000/split" -F "file=@multi-awb.pdf" -o awb-split.zip
```

## Write split AWBs to Blob Storage

`POST /split/blob` splits the PDF and uploads each AWB to blob storage using
**managed identity** (keyless). Blob layout is configurable via env vars; the
default path is:

```
<BLOB_CONTAINER>/<document_name>/<date>/<flight>/<awb>.pdf
```

e.g. `awb-input/AWB_BATCH_2026-06-18/2026-06-18/EK0123/176-12345678.pdf`

### Configuration (env vars)

| Variable             | Default                                         | Description                                              |
|----------------------|-------------------------------------------------|----------------------------------------------------------|
| `BLOB_ACCOUNT_URL`   | _(unset — blob upload disabled)_                | Blob endpoint, e.g. `https://stskycargoawbdata.blob.core.windows.net` |
| `BLOB_CONTAINER`     | `awb-input`                                     | Destination container (the `awb_input` root).            |
| `BLOB_PATH_TEMPLATE` | `{document_name}/{date}/{flight}/{awb}.pdf`     | Virtual path template. Fields: `document_name`, `date`, `flight`, `awb`. |
| `AZURE_CLIENT_ID`    | _(unset — uses system-assigned identity)_       | User-assigned managed identity client id, if applicable. |

### Request

```bash
curl -X POST "http://localhost:8000/split/blob" \
  -F "file=@multi-awb.pdf" \
  -F "document_name=AWB_BATCH_2026-06-18" \
  -F "date=2026-06-18" \
  -F "flight=EK0123"
```

Returns the list of blob paths written:

```json
{ "count": 3, "blobs": ["awb-input/AWB_BATCH_2026-06-18/2026-06-18/EK0123/176-12345678.pdf", "..."] }
```

> The app's managed identity needs **Storage Blob Data Contributor** on the target account.

## Build the container

```powershell
docker build -t awb-pdf-splitter:v1 .
docker run -p 8000:8000 awb-pdf-splitter:v1
```

## Deploy privately to Azure Container Apps

```powershell
./deploy.ps1
```

This builds the image in ACR, creates a **VNet-injected, internal-only** Container Apps
environment, and deploys the app with `--ingress internal`. The result is reachable only
on its internal FQDN from inside `vnet-ek` (or peered networks) — **no public endpoint**.
