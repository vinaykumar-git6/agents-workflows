"""Run OCR on a PDF using Azure AI Document Intelligence (keyless / managed identity).

Transient backend errors are retried with exponential backoff via tenacity, and
the whole OCR call is guarded by a circuit breaker so a failing backend does not
get hammered.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError, ServiceRequestError, ServiceResponseError
from azure.identity import DefaultAzureCredential
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from circuit_breaker import CircuitBreaker

logger = logging.getLogger("awb.ocr")

DOCINTEL_ENDPOINT = os.getenv("DOCUMENTINTELLIGENCE_ENDPOINT", "")
DOCINTEL_MODEL = os.getenv("DOCUMENTINTELLIGENCE_MODEL", "prebuilt-layout")
DOCINTEL_API_KEY = os.getenv("DOCUMENTINTELLIGENCE_API_KEY", "").strip()
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID") or None

# In-process OCR retry tuning (per OCR attempt).
OCR_MAX_RETRIES = int(os.getenv("OCR_MAX_RETRIES", "3"))
OCR_BACKOFF_BASE = float(os.getenv("OCR_BACKOFF_BASE", "2"))
OCR_BACKOFF_MAX = float(os.getenv("OCR_BACKOFF_MAX", "30"))

# Circuit breaker tuning (across messages).
_breaker = CircuitBreaker(
    failure_threshold=int(os.getenv("OCR_CB_FAILURE_THRESHOLD", "5")),
    recovery_time=float(os.getenv("OCR_CB_RECOVERY_SECONDS", "30")),
    name="document-intelligence",
)

# Errors that are worth retrying (network / throttling / 5xx).
_TRANSIENT = (ServiceRequestError, ServiceResponseError, HttpResponseError)

_client: DocumentIntelligenceClient | None = None


def _credential():
    if AZURE_CLIENT_ID:
        return DefaultAzureCredential(managed_identity_client_id=AZURE_CLIENT_ID)
    return DefaultAzureCredential()


def get_client() -> DocumentIntelligenceClient:
    global _client
    if _client is None:
        if not DOCINTEL_ENDPOINT:
            raise RuntimeError("DOCUMENTINTELLIGENCE_ENDPOINT is not configured.")
        credential = (
            AzureKeyCredential(DOCINTEL_API_KEY) if DOCINTEL_API_KEY else _credential()
        )
        _client = DocumentIntelligenceClient(
            endpoint=DOCINTEL_ENDPOINT, credential=credential
        )
    return _client


def is_enabled() -> bool:
    return bool(DOCINTEL_ENDPOINT)


def _should_retry(exc: BaseException) -> bool:
    """Retry only transient errors. 4xx (except 429) are permanent."""
    if isinstance(exc, HttpResponseError):
        status = getattr(exc, "status_code", None)
        if status is not None and 400 <= status < 500 and status != 429:
            return False
    return isinstance(exc, _TRANSIENT)


def _analyze(pdf_bytes: bytes) -> AnalyzeResult:
    @retry(
        retry=retry_if_exception_type(_TRANSIENT),
        stop=stop_after_attempt(OCR_MAX_RETRIES),
        wait=wait_exponential(multiplier=OCR_BACKOFF_BASE, max=OCR_BACKOFF_MAX),
        reraise=True,
    )
    def _run() -> AnalyzeResult:
        client = get_client()
        poller = client.begin_analyze_document(
            DOCINTEL_MODEL, body=pdf_bytes, content_type="application/pdf"
        )
        return poller.result()

    return _run()


def run_ocr(pdf_bytes: bytes) -> AnalyzeResult:
    """Analyze a PDF, with retry + circuit breaker. Raises on failure."""
    return _breaker.call(_analyze, pdf_bytes)


def build_markdown(source_name: str, result: AnalyzeResult) -> str:
    lines: list[str] = [
        f"# OCR Result — {source_name}",
        "",
        f"- **Model:** `{DOCINTEL_MODEL}`",
        f"- **Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"- **Pages:** {len(result.pages) if result.pages else 0}",
        f"- **Tables:** {len(result.tables) if result.tables else 0}",
        "",
    ]
    if result.content:
        lines += ["## Extracted Content", "", "```text", result.content, "```", ""]
    return "\n".join(lines)


def result_to_json(result: AnalyzeResult) -> str:
    return json.dumps(result.as_dict(), indent=2, ensure_ascii=False)
