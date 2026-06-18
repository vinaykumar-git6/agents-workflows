"""Upload split AWB PDFs to Azure Blob Storage using managed identity (keyless).

Blob layout is configurable via env vars. Default path:
    <container>/<document_name>/<date>/<flight>/<awb>.pdf
e.g. awb-input/AWB_BATCH_2026-06-18/2026-06-18/EK0123/176-12345678.pdf
"""
from __future__ import annotations

import os

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

# ---- Configurable via environment variables ----
# Storage account blob endpoint, e.g. https://stskycargoawbdata.blob.core.windows.net
BLOB_ACCOUNT_URL = os.getenv("BLOB_ACCOUNT_URL", "")
# Destination container (the "awb_input" root).
BLOB_CONTAINER = os.getenv("BLOB_CONTAINER", "awb-input")
# Virtual path template within the container. Available fields:
#   {document_name} {date} {flight} {awb}
BLOB_PATH_TEMPLATE = os.getenv(
    "BLOB_PATH_TEMPLATE", "{document_name}/{date}/{flight}/{awb}.pdf"
)
# Optional user-assigned managed identity client id (omit for system-assigned).
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID") or None


def _credential() -> DefaultAzureCredential:
    if AZURE_CLIENT_ID:
        return DefaultAzureCredential(managed_identity_client_id=AZURE_CLIENT_ID)
    return DefaultAzureCredential()


def build_blob_path(document_name: str, date: str, flight: str, awb: str) -> str:
    """Render the configured blob path template for one AWB file."""
    return BLOB_PATH_TEMPLATE.format(
        document_name=document_name,
        date=date,
        flight=flight,
        awb=awb,
    )


def is_enabled() -> bool:
    """Blob upload is active only when a storage account URL is configured."""
    return bool(BLOB_ACCOUNT_URL)


def upload_split_pdfs(
    files: dict[str, bytes],
    *,
    document_name: str,
    date: str,
    flight: str,
) -> list[str]:
    """Upload each per-AWB PDF to blob storage. Returns the blob paths written."""
    if not BLOB_ACCOUNT_URL:
        raise RuntimeError("BLOB_ACCOUNT_URL is not configured.")

    service = BlobServiceClient(account_url=BLOB_ACCOUNT_URL, credential=_credential())
    container = service.get_container_client(BLOB_CONTAINER)

    written: list[str] = []
    for filename, data in files.items():
        awb = filename.rsplit(".pdf", 1)[0]
        blob_path = build_blob_path(document_name, date, flight, awb)
        container.upload_blob(
            name=blob_path,
            data=data,
            overwrite=True,
            content_type="application/pdf",
        )
        written.append(f"{BLOB_CONTAINER}/{blob_path}")
    return written
