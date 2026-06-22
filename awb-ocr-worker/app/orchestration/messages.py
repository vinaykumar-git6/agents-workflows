"""Messages passed between executors in the AWB orchestration workflow."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OcrRequest:
    """Input to the workflow: the PDF bytes and a human-readable source name."""

    pdf_bytes: bytes
    source_name: str


@dataclass
class OcrPayload:
    """Output of the OCR executor: raw text + a Markdown rendering."""

    text: str
    markdown: str


@dataclass
class FormattedResult:
    """Final workflow output: normalized AWB JSON + the OCR Markdown."""

    json_text: str
    markdown: str
