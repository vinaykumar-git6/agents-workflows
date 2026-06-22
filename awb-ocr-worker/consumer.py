"""Service Bus consumer: OCR-process split AWB PDFs.

For each message on the worker queue (an Event Grid `BlobCreated` event that
points to a split AWB PDF in the awb-split container), this worker:

  1. Reads the blob URL from the event (data.url).
  2. Downloads the PDF from Blob Storage (managed identity, keyless).
  3. Runs OCR with Azure Document Intelligence (retry + circuit breaker).
  4. Writes the OCR artifacts (.json + .md) to the awb-output container.

Reliability model
-----------------
- PERMANENT errors (bad content / malformed event)  -> dead-letter immediately.
- TRANSIENT errors (OCR backend down, throttling, circuit open):
    retry with EXPONENTIAL BACKOFF by re-scheduling the message with an
    increasing delay (tracked via the `attempt` application property). After
    MAX_ATTEMPTS the message is sent to the dead-letter queue.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage

import ocr
import storage
from circuit_breaker import CircuitOpenError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("awb.ocr.consumer")

SERVICEBUS_NAMESPACE = os.getenv("SERVICEBUS_NAMESPACE", "")
QUEUE_NAME = os.getenv("SERVICEBUS_QUEUE", "awb-worker-q")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID") or None

# Exponential backoff across redeliveries.
MAX_ATTEMPTS = int(os.getenv("OCR_MAX_ATTEMPTS", "5"))
BACKOFF_BASE_SECONDS = float(os.getenv("OCR_BACKOFF_BASE_SECONDS", "10"))
BACKOFF_MAX_SECONDS = float(os.getenv("OCR_BACKOFF_MAX_SECONDS", "600"))

# Errors that will never succeed on retry -> dead-letter straight away.
try:
    from pypdf.errors import PdfReadError, PdfStreamError

    PERMANENT_ERRORS: tuple[type[Exception], ...] = (
        PdfReadError,
        PdfStreamError,
        ValueError,
        json.JSONDecodeError,
    )
except Exception:  # noqa: BLE001
    PERMANENT_ERRORS = (ValueError, json.JSONDecodeError)


def _credential() -> DefaultAzureCredential:
    if AZURE_CLIENT_ID:
        return DefaultAzureCredential(managed_identity_client_id=AZURE_CLIENT_ID)
    return DefaultAzureCredential()


def is_enabled() -> bool:
    return bool(SERVICEBUS_NAMESPACE)


def extract_blob_url(message_body: str) -> str | None:
    payload = json.loads(message_body)
    event = payload[0] if isinstance(payload, list) else payload
    data = event.get("data", {})
    url = data.get("url")
    if not url:
        return None
    if event.get("eventType") and event["eventType"] != "Microsoft.Storage.BlobCreated":
        return None
    return url


def process_message(message_body: str) -> list[str]:
    """OCR one split AWB PDF end-to-end. Returns the output blob paths."""
    blob_url = extract_blob_url(message_body)
    if not blob_url:
        logger.warning("Message had no usable blob URL; skipping.")
        return []

    blob_path = urlparse(blob_url).path.lstrip("/")
    if not blob_path.lower().endswith(".pdf"):
        logger.info("Skipping non-PDF blob: %s", blob_path)
        return []

    logger.info("OCR processing blob: %s", blob_url)
    pdf_bytes = storage.download_blob(blob_url)
    result = ocr.run_ocr(pdf_bytes)

    source_name = blob_path.rsplit("/", 1)[-1]
    prefix = storage.output_prefix_for(blob_url)
    written = storage.upload_outputs(
        prefix,
        json_text=ocr.result_to_json(result),
        md_text=ocr.build_markdown(source_name, result),
    )
    logger.info("Wrote OCR outputs: %s", ", ".join(written))
    return written


def _attempt_of(message) -> int:
    props = message.application_properties or {}
    raw = props.get(b"attempt") or props.get("attempt") or 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _backoff_seconds(attempt: int) -> float:
    return min(BACKOFF_BASE_SECONDS * (2 ** attempt), BACKOFF_MAX_SECONDS)


def _reschedule(sender, message, attempt: int) -> None:
    """Re-enqueue the message with exponential delay for the next attempt."""
    delay = _backoff_seconds(attempt)
    enqueue_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    clone = ServiceBusMessage(
        str(message),
        application_properties={"attempt": attempt + 1},
        content_type=message.content_type,
    )
    sender.schedule_messages(clone, enqueue_at)
    logger.warning(
        "Transient failure; rescheduled attempt %d in %.0fs.", attempt + 1, delay
    )


def run() -> None:
    if not is_enabled():
        logger.info("SERVICEBUS_NAMESPACE not set; consumer disabled.")
        return

    logger.info("Starting OCR consumer on %s / %s", SERVICEBUS_NAMESPACE, QUEUE_NAME)
    while True:
        try:
            client = ServiceBusClient(SERVICEBUS_NAMESPACE, credential=_credential())
            with client:
                receiver = client.get_queue_receiver(
                    queue_name=QUEUE_NAME, max_wait_time=30
                )
                sender = client.get_queue_sender(queue_name=QUEUE_NAME)
                with receiver, sender:
                    for message in receiver:
                        attempt = _attempt_of(message)
                        try:
                            process_message(str(message))
                            receiver.complete_message(message)
                        except PERMANENT_ERRORS as exc:
                            logger.exception("Permanent error; dead-lettering.")
                            receiver.dead_letter_message(
                                message,
                                reason="PermanentError",
                                error_description=str(exc)[:200],
                            )
                        except (CircuitOpenError, Exception) as exc:  # noqa: BLE001
                            # Transient: back off exponentially, or give up.
                            if attempt + 1 >= MAX_ATTEMPTS:
                                logger.exception(
                                    "Retries exhausted (%d); dead-lettering.", attempt
                                )
                                receiver.dead_letter_message(
                                    message,
                                    reason="RetriesExhausted",
                                    error_description=str(exc)[:200],
                                )
                            else:
                                _reschedule(sender, message, attempt)
                                receiver.complete_message(message)
        except Exception:  # noqa: BLE001 - connection-level error: reconnect
            logger.exception("Service Bus receiver error; reconnecting in 5s.")
            time.sleep(5)


def start_background() -> threading.Thread | None:
    if not is_enabled():
        logger.info("SERVICEBUS_NAMESPACE not set; background consumer not started.")
        return None
    thread = threading.Thread(target=run, name="ocr-consumer", daemon=True)
    thread.start()
    return thread
