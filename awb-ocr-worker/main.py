"""Health/info API for the AWB OCR worker. The real work runs in a background
Service Bus consumer started on app startup."""
from __future__ import annotations

from fastapi import FastAPI

import consumer
import ocr
import storage

app = FastAPI(title="AWB OCR Worker", version="1.0.0")


@app.on_event("startup")
def _start_consumer() -> None:
    consumer.start_background()


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "ocr_configured": ocr.is_enabled(),
        "blob_configured": storage.is_enabled(),
        "servicebus_configured": consumer.is_enabled(),
    }
