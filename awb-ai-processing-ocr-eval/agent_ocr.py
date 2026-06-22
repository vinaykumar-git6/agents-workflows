"""SkyCargo OCR via a Microsoft Foundry agent (gpt-5.4).

Reads every PDF in the `input/` folder, sends it to a Microsoft Foundry
prompt agent backed by a vision-capable model (gpt-5.4), and writes the
structured OCR result into `output/` as:

  - <name>.agent.json : the model's structured transcription + metadata
  - <name>.agent.md   : human-readable Markdown summary

The agent is created (or a new version is registered) on each run using the
`PromptAgentDefinition`, then the PDF is analyzed through the Responses API.

Authentication:
  Azure AD only — Azure CLI credential locally (`az login`) and Managed
  Identity when deployed in Azure. No API keys are used.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import AzureCliCredential, ChainedTokenCredential, ManagedIdentityCredential

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

AGENT_INSTRUCTIONS = (
    "You are an OCR engine for air waybill (AWB) and air-cargo documents. "
    "Transcribe every piece of text in the supplied document exactly as it "
    "appears, preserving the natural reading order. Do not summarize, "
    "translate, infer, or omit any text. Reproduce numbers, codes, and "
    "punctuation verbatim.\n\n"
    "Return ONLY a single JSON object — no markdown, no code fences, no "
    "commentary — that matches this schema exactly:\n"
    "{\n"
    '  "content": "full plain-text transcription of the entire document",\n'
    '  "pages": [{"page_number": 1, "lines": ["<line text>", "..."]}],\n'
    '  "tables": [{"rows": [["<cell>", "<cell>"], ["..."]]}],\n'
    '  "key_values": {"<field label>": "<field value>"}\n'
    "}\n\n"
    "If a section is not present in the document, use an empty array or "
    "empty object for it. Always produce valid JSON."
)


def get_config() -> tuple[str, str, str]:
    """Load Foundry settings from the environment."""
    load_dotenv(BASE_DIR / ".env")

    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not endpoint:
        raise SystemExit(
            "Missing FOUNDRY_PROJECT_ENDPOINT. Add it to .env, e.g.\n"
            "  FOUNDRY_PROJECT_ENDPOINT="
            "https://mydevfoundry0603.services.ai.azure.com/api/projects/<project-name>"
        )

    model = os.getenv("FOUNDRY_MODEL_DEPLOYMENT", "gpt-5.4").strip()
    agent_name = os.getenv("FOUNDRY_AGENT_NAME", "skycargo-ocr-agent").strip()
    return endpoint, model, agent_name


def build_credential() -> ChainedTokenCredential:
    """Managed Identity (in Azure) then Azure CLI credential (local dev)."""
    return ChainedTokenCredential(ManagedIdentityCredential(), AzureCliCredential())


def ensure_agent(project: AIProjectClient, model: str, agent_name: str):
    """Create (or register a new version of) the OCR prompt agent."""
    return project.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(model=model, instructions=AGENT_INSTRUCTIONS),
    )


def analyze_pdf(openai_client, agent_name: str, pdf_path: Path) -> str:
    """Send a PDF to the agent and return the raw model output text."""
    data_uri = "data:application/pdf;base64," + base64.b64encode(
        pdf_path.read_bytes()
    ).decode("ascii")

    response = openai_client.responses.create(
        extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Perform OCR on the attached document and return the "
                            "JSON object defined in your instructions."
                        ),
                    },
                    {
                        "type": "input_file",
                        "filename": pdf_path.name,
                        "file_data": data_uri,
                    },
                ],
            }
        ],
    )
    return response.output_text


def extract_json(text: str) -> dict:
    """Pull the JSON object out of the model's raw text output."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Model output did not contain a JSON object.")
    return json.loads(text[start : end + 1])


def build_markdown(pdf_name: str, model: str, result: dict) -> str:
    """Create a human-readable Markdown summary from the agent result."""
    lines: list[str] = []
    lines.append(f"# Agent OCR Result — {pdf_name}")
    lines.append("")
    lines.append(f"- **Engine:** Foundry agent")
    lines.append(f"- **Model:** `{model}`")
    lines.append(f"- **Generated:** {datetime.now(timezone.utc).isoformat()}")

    pages = result.get("pages") or []
    tables = result.get("tables") or []
    key_values = result.get("key_values") or {}
    lines.append(f"- **Pages:** {len(pages)}")
    lines.append(f"- **Tables:** {len(tables)}")
    lines.append("")

    content = result.get("content") or ""
    if content:
        lines.append("## Extracted Content")
        lines.append("")
        lines.append("```text")
        lines.append(content)
        lines.append("```")
        lines.append("")

    for page in pages:
        lines.append(f"## Page {page.get('page_number', '?')}")
        lines.append("")
        for line in page.get("lines") or []:
            lines.append(f"- {line}")
        lines.append("")

    for idx, table in enumerate(tables, start=1):
        rows = table.get("rows") or []
        cols = max((len(r) for r in rows), default=0)
        lines.append(f"## Table {idx} ({len(rows)} x {cols})")
        lines.append("")
        for r, row in enumerate(rows):
            padded = list(row) + [""] * (cols - len(row))
            lines.append("| " + " | ".join(str(c).replace("\n", " ") for c in padded) + " |")
            if r == 0:
                lines.append("| " + " | ".join(["---"] * cols) + " |")
        lines.append("")

    if key_values:
        lines.append("## Key / Value Fields")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("| --- | --- |")
        for k, v in key_values.items():
            lines.append(f"| {k} | {str(v).replace(chr(10), ' ')} |")
        lines.append("")

    return "\n".join(lines)


def process_one(openai_client, agent_name: str, model: str, pdf_path: Path) -> None:
    """Process a single PDF: run agent OCR, write JSON + MD."""
    stem = pdf_path.stem
    print(f"  -> Analyzing {pdf_path.name} with agent '{agent_name}' ...")

    raw = analyze_pdf(openai_client, agent_name, pdf_path)
    result = extract_json(raw)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    document = {
        "document": pdf_path.name,
        "engine": "foundry-agent",
        "model": model,
        "agent": agent_name,
        "generated": datetime.now(timezone.utc).isoformat(),
        "result": result,
    }

    json_path = OUTPUT_DIR / f"{stem}.agent.json"
    json_path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")

    md_path = OUTPUT_DIR / f"{stem}.agent.md"
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

    endpoint, model, agent_name = get_config()

    project = AIProjectClient(endpoint=endpoint, credential=build_credential())
    agent = ensure_agent(project, model, agent_name)
    print(f"Agent ready (name: {agent.name}, version: {agent.version}, model: {model}).")

    openai_client = project.get_openai_client()
    print(f"Found {len(pdfs)} PDF(s).")

    failures = 0
    for pdf_path in pdfs:
        try:
            process_one(openai_client, agent_name, model, pdf_path)
        except Exception as exc:  # noqa: BLE001 - report and continue with next file
            failures += 1
            print(f"     ERROR processing {pdf_path.name}: {exc}")

    processed = len(pdfs) - failures
    print(f"\nDone. {processed} succeeded, {failures} failed.")


if __name__ == "__main__":
    main()
