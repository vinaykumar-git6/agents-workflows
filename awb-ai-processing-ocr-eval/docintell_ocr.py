"""SkyCargo OCR — Azure Document Intelligence.

Reads every PDF in the `input/` folder, runs OCR with Azure AI Document
Intelligence, and writes two artifacts per document into `output/`:

  - <name>.json  : structured extraction result (pages, lines, tables, words)
  - <name>.md    : human-readable Markdown summary

Authentication:
  - If DOCUMENTINTELLIGENCE_API_KEY is set, uses key-based auth.
  - Otherwise falls back to Azure AD via DefaultAzureCredential (az login).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.core.credentials import AzureKeyCredential

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"


def get_client() -> tuple[DocumentIntelligenceClient, str]:
    """Build a Document Intelligence client from environment variables."""
    load_dotenv(BASE_DIR / ".env")

    endpoint = os.getenv("DOCUMENTINTELLIGENCE_ENDPOINT")
    if not endpoint:
        raise SystemExit(
            "Missing DOCUMENTINTELLIGENCE_ENDPOINT. Copy .env.example to .env and fill it in."
        )

    model = os.getenv("DOCUMENTINTELLIGENCE_MODEL", "prebuilt-layout")
    api_key = os.getenv("DOCUMENTINTELLIGENCE_API_KEY", "").strip()

    if api_key:
        # Optional override: explicit key-based auth.
        credential = AzureKeyCredential(api_key)
    else:
        # Default: Azure AD. Uses Azure CLI credential locally (`az login`)
        # and Managed Identity when deployed in Azure.
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()

    client = DocumentIntelligenceClient(endpoint=endpoint, credential=credential)
    return client, model


def analyze_pdf(client: DocumentIntelligenceClient, model: str, pdf_path: Path) -> AnalyzeResult:
    """Run OCR on a single PDF and return the analyze result."""
    with pdf_path.open("rb") as f:
        poller = client.begin_analyze_document(model, body=f, content_type="application/pdf")
    return poller.result()


def build_markdown(pdf_name: str, model: str, result: AnalyzeResult) -> str:
    """Create a human-readable Markdown summary from the analyze result."""
    lines: list[str] = []
    lines.append(f"# OCR Result — {pdf_name}")
    lines.append("")
    lines.append(f"- **Model:** `{model}`")
    lines.append(f"- **Generated:** {datetime.now(timezone.utc).isoformat()}")
    page_count = len(result.pages) if result.pages else 0
    table_count = len(result.tables) if result.tables else 0
    lines.append(f"- **Pages:** {page_count}")
    lines.append(f"- **Tables:** {table_count}")
    lines.append("")

    # Full extracted content first (most useful).
    if result.content:
        lines.append("## Extracted Content")
        lines.append("")
        lines.append("```text")
        lines.append(result.content)
        lines.append("```")
        lines.append("")

    # Per-page line breakdown.
    if result.pages:
        for page in result.pages:
            lines.append(f"## Page {page.page_number}")
            lines.append("")
            if page.lines:
                for line in page.lines:
                    lines.append(f"- {line.content}")
            else:
                lines.append("_No text lines detected._")
            lines.append("")

    # Tables as Markdown.
    if result.tables:
        for idx, table in enumerate(result.tables, start=1):
            lines.append(f"## Table {idx} ({table.row_count} x {table.column_count})")
            lines.append("")
            grid: list[list[str]] = [
                ["" for _ in range(table.column_count)] for _ in range(table.row_count)
            ]
            for cell in table.cells:
                if cell.row_index < table.row_count and cell.column_index < table.column_count:
                    grid[cell.row_index][cell.column_index] = (cell.content or "").replace("\n", " ")
            for r, row in enumerate(grid):
                lines.append("| " + " | ".join(row) + " |")
                if r == 0:
                    lines.append("| " + " | ".join(["---"] * table.column_count) + " |")
            lines.append("")

    return "\n".join(lines)


def process_one(client: DocumentIntelligenceClient, model: str, pdf_path: Path) -> None:
    """Process a single PDF: run OCR, write JSON + MD."""
    stem = pdf_path.stem
    print(f"  -> Analyzing {pdf_path.name} ...")
    result = analyze_pdf(client, model, pdf_path)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / f"{stem}.json"
    json_path.write_text(
        json.dumps(result.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    md_path = OUTPUT_DIR / f"{stem}.md"
    md_path.write_text(build_markdown(pdf_path.name, model, result), encoding="utf-8")

    print(f"     JSON -> {json_path.relative_to(BASE_DIR)}")
    print(f"     MD   -> {md_path.relative_to(BASE_DIR)}")


def main() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDF files found in {INPUT_DIR}. Drop a PDF there and re-run.")
        return

    client, model = get_client()
    print(f"Found {len(pdfs)} PDF(s). Using model '{model}'.")

    failures = 0
    for pdf_path in pdfs:
        try:
            process_one(client, model, pdf_path)
        except Exception as exc:  # noqa: BLE001 - report and continue with next file
            failures += 1
            print(f"     ERROR processing {pdf_path.name}: {exc}")

    processed = len(pdfs) - failures
    print(f"\nDone. {processed} succeeded, {failures} failed.")


if __name__ == "__main__":
    main()
