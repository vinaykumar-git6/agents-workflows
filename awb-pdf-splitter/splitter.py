"""Split a multi-AWB PDF into one PDF per Air Waybill number."""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter

# AWB format: 3-digit prefix + 8-digit serial, e.g. "176-12345678" or "176 12345678".
AWB_REGEX = re.compile(r"\b(\d{3})[-\s]?(\d{8})\b")


@dataclass
class AwbSegment:
    awb_number: str
    start_page: int
    end_page: int  # inclusive


def _normalize(prefix: str, serial: str) -> str:
    return f"{prefix}-{serial}"


def find_awb_on_page(text: str) -> str | None:
    """Return the first AWB number found on a page, or None."""
    if not text:
        return None
    match = AWB_REGEX.search(text)
    if match:
        return _normalize(match.group(1), match.group(2))
    return None


def detect_segments(reader: PdfReader) -> list[AwbSegment]:
    """Group consecutive pages by AWB number."""
    segments: list[AwbSegment] = []
    current: AwbSegment | None = None

    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        awb = find_awb_on_page(text)

        if awb and (current is None or awb != current.awb_number):
            # New AWB starts here.
            if current is not None:
                segments.append(current)
            current = AwbSegment(awb_number=awb, start_page=i, end_page=i)
        elif current is not None:
            # Continuation page of the current AWB.
            current.end_page = i
        else:
            # Pages before the first detected AWB -> bucket as "unclassified".
            current = AwbSegment(awb_number="UNCLASSIFIED", start_page=i, end_page=i)

    if current is not None:
        segments.append(current)
    return segments


def split_pdf(pdf_bytes: bytes) -> dict[str, bytes]:
    """Return {filename: pdf_bytes} for each detected AWB."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    segments = detect_segments(reader)

    results: dict[str, bytes] = {}
    seen: dict[str, int] = {}
    for seg in segments:
        writer = PdfWriter()
        for p in range(seg.start_page, seg.end_page + 1):
            writer.add_page(reader.pages[p])

        # Handle duplicate AWB numbers across non-consecutive sections.
        base = seg.awb_number
        seen[base] = seen.get(base, 0) + 1
        name = base if seen[base] == 1 else f"{base}_{seen[base]}"

        buf = io.BytesIO()
        writer.write(buf)
        results[f"{name}.pdf"] = buf.getvalue()

    return results


def build_zip(files: dict[str, bytes]) -> bytes:
    """Bundle the split PDFs into a single ZIP archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()
