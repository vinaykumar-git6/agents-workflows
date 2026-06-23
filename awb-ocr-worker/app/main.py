"""Health/info API for the AWB OCR worker. The real work runs in a background
Service Bus consumer started on app startup.

TEST ENDPOINT: POST /test/orchestrate with a PDF file to test the orchestration locally.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

# Load local environment variables before importing modules that read them.
# .env.local takes precedence (local dev); falls back to .env if present.
_BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BASE_DIR / ".env.local", override=True)
load_dotenv(_BASE_DIR / ".env", override=False)

# Configure logging (console + app.log file) before importing app modules.
from app.logging_setup import setup_logging

setup_logging()

import time
import uuid

from fastapi import FastAPI, File, Request, UploadFile

from app import consumer
from app.orchestration import is_enabled as agent_is_enabled
from app.orchestration import run_orchestration
from app.services import ocr, storage

logger = logging.getLogger("awb.main")

app = FastAPI(title="AWB OCR Worker", version="1.0.0")


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    """Log every HTTP request and response (method, path, status, duration)."""
    req_id = uuid.uuid4().hex[:8]
    start = time.perf_counter()
    logger.info("REQ  [%s] %s %s from %s", req_id, request.method, request.url.path,
                request.client.host if request.client else "-")
    try:
        response = await call_next(request)
    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        logger.exception("ERR  [%s] %s %s failed after %.0f ms", req_id,
                         request.method, request.url.path, elapsed)
        raise
    elapsed = (time.perf_counter() - start) * 1000
    logger.info("RESP [%s] %s %s -> %d (%.0f ms)", req_id, request.method,
                request.url.path, response.status_code, elapsed)
    return response


@app.on_event("startup")
def _start_consumer() -> None:
    consumer.start_background()


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "ocr_configured": ocr.is_enabled(),
        "agent_configured": agent_is_enabled(),
        "blob_configured": storage.is_enabled(),
        "servicebus_configured": consumer.is_enabled(),
    }


@app.post("/test/orchestrate")
async def test_orchestrate(file: UploadFile = File(...)) -> dict[str, str]:
    """TEST ENDPOINT: Upload a PDF and run the orchestration pipeline end-to-end.
    
    Returns the normalized JSON and markdown output.
    Not for production use — Service Bus consumer is the canonical flow.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return {"error": "File must be a PDF"}

    pdf_bytes = await file.read()
    if not pdf_bytes:
        return {"error": "PDF file is empty"}

    try:
        logger.info("TEST: Running orchestration on %s (%d bytes)", file.filename, len(pdf_bytes))
        json_text, md_text = await run_orchestration(pdf_bytes, file.filename)
        logger.info("TEST: Orchestration succeeded for %s (json=%d chars, md=%d chars)",
                    file.filename, len(json_text), len(md_text))
        logger.debug("TEST: Output JSON for %s:\n%s", file.filename, json_text)
        return {
            "filename": file.filename,
            "json": json_text,
            "markdown": md_text,
        }
    except Exception as exc:
        logger.exception("TEST: Orchestration failed for %s", file.filename)
        return {
            "error": str(exc),
            "error_type": type(exc).__name__,
        }
