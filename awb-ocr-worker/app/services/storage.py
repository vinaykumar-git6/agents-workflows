"""Blob storage helpers for the OCR worker (keyless / managed identity).

- download_blob(url): fetch the split AWB PDF referenced by an event.
- upload_outputs(...): write the AWB artifacts (.json + .md) to the output
  container under a path derived from the source blob.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

BLOB_ACCOUNT_URL = os.getenv("BLOB_ACCOUNT_URL", "")
# Container where AWB artifacts are written. Kept separate from the input/split
# containers so writes never re-trigger upstream Event Grid subscriptions.
BLOB_OUTPUT_CONTAINER = os.getenv("BLOB_OUTPUT_CONTAINER", "awb-output")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID") or None


def _credential() -> DefaultAzureCredential:
    if AZURE_CLIENT_ID:
        return DefaultAzureCredential(managed_identity_client_id=AZURE_CLIENT_ID)
    return DefaultAzureCredential()


def _service_client() -> BlobServiceClient:
    if not BLOB_ACCOUNT_URL:
        raise RuntimeError("BLOB_ACCOUNT_URL is not configured.")
    return BlobServiceClient(account_url=BLOB_ACCOUNT_URL, credential=_credential())


def is_enabled() -> bool:
    return bool(BLOB_ACCOUNT_URL)


def download_blob(blob_url: str) -> bytes:
    """Download a blob given its full https URL using managed identity."""
    parsed = urlparse(blob_url)
    parts = parsed.path.lstrip("/").split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Unexpected blob URL: {blob_url}")
    container_name, blob_name = parts
    service = _service_client()
    blob = service.get_blob_client(container=container_name, blob=blob_name)
    return blob.download_blob().readall()


def output_prefix_for(blob_url: str) -> str:
    """Mirror the source blob path (minus its container) for the output layout.

    Source: <split-container>/pdf/<timestamp>/splitted-awb/<awb>.pdf
    Output prefix: pdf/<timestamp>/splitted-awb/<awb>
    """
    path = urlparse(blob_url).path.lstrip("/")
    parts = path.split("/")
    rel = "/".join(parts[1:]) if len(parts) > 1 else path
    if rel.lower().endswith(".pdf"):
        rel = rel[: -len(".pdf")]
    return rel


def upload_outputs(prefix: str, *, json_text: str, md_text: str) -> list[str]:
    """Write <prefix>.json and <prefix>.md to the output container."""
    service = _service_client()
    container = service.get_container_client(BLOB_OUTPUT_CONTAINER)
    prefix = prefix.strip("/")

    written: list[str] = []
    for suffix, data, content_type in (
        (".json", json_text, "application/json"),
        (".md", md_text, "text/markdown"),
    ):
        blob_path = f"{prefix}{suffix}"
        container.upload_blob(
            name=blob_path,
            data=data.encode("utf-8"),
            overwrite=True,
            content_type=content_type,
        )
        written.append(f"{BLOB_OUTPUT_CONTAINER}/{blob_path}")
    return written
