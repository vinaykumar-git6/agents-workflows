"""Judge OCR quality: Document Intelligence vs Foundry agent (gpt-5.4).

The local `compare_ocr.py` only measures how *similar* the two outputs are.
It cannot say which one is *correct*, because it has no ground truth.

This script adds ground truth: it sends the ORIGINAL PDF plus BOTH OCR
transcriptions to gpt-5.4 (acting as an impartial judge) and asks it to
score each engine against what the document actually says, adjudicate every
disagreement, and declare an overall winner.

For each document that has both `<name>.json` (Document Intelligence) and
`<name>.agent.json` (Foundry agent) in `output/`, it writes:

  - <name>.verdict.json : structured scores, per-field adjudication, winner
  - <name>.verdict.md   : human-readable verdict

Authentication:
  Azure AD only — Azure CLI credential locally (`az login`) and Managed
  Identity when deployed in Azure.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential, ChainedTokenCredential, ManagedIdentityCredential

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

JUDGE_INSTRUCTIONS = (
    "You are an impartial OCR quality adjudicator for air waybill (AWB) and "
    "air-cargo documents. You are given the ORIGINAL document and two OCR "
    "transcriptions of it produced by two different engines:\n"
    "  - Engine A: Azure AI Document Intelligence (prebuilt-layout)\n"
    "  - Engine B: a gpt-5.4 vision agent\n\n"
    "Read the ORIGINAL document yourself. Treat the document as the single "
    "source of truth. Judge each transcription ONLY against what the document "
    "actually shows — never against the other transcription.\n\n"
    "Score each engine from 0-100 on each dimension:\n"
    "  - accuracy:      are characters, digits, codes, and amounts correct?\n"
    "  - completeness:  is all visible text captured, nothing missing?\n"
    "  - structure:     are reading order, tables, and field grouping faithful?\n"
    "  - hallucination: 100 = invented nothing; lower = added text not present.\n\n"
    "Pay special attention to critical AWB fields: the AWB number, airport "
    "codes, account numbers, phone numbers, weights, piece counts, and money "
    "amounts. A single wrong digit in these fields is a serious error.\n\n"
    "Return ONLY a single JSON object — no markdown, no code fences — with "
    "this exact schema:\n"
    "{\n"
    '  "winner": "doc_intelligence" | "agent" | "tie",\n'
    '  "overall_score": {"doc_intelligence": <0-100>, "agent": <0-100>},\n'
    '  "scores": {\n'
    '    "doc_intelligence": {"accuracy": n, "completeness": n, "structure": n, "hallucination": n},\n'
    '    "agent": {"accuracy": n, "completeness": n, "structure": n, "hallucination": n}\n'
    "  },\n"
    '  "critical_field_adjudication": [\n'
    '    {"field": "AWB number", "ground_truth": "<what the document shows>",\n'
    '     "doc_intelligence": "<value>", "agent": "<value>",\n'
    '     "correct": "doc_intelligence" | "agent" | "both" | "neither"}\n'
    "  ],\n"
    '  "doc_intelligence_errors": ["<specific error>"],\n'
    '  "agent_errors": ["<specific error>"],\n'
    '  "summary": "<2-4 sentence plain-English verdict on which is more precise and why>"\n'
    "}\n"
    "Always produce valid JSON."
)


def get_config() -> tuple[str, str]:
    """Load Foundry settings from the environment."""
    load_dotenv(BASE_DIR / ".env")

    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not endpoint or "<project-name>" in endpoint:
        raise SystemExit(
            "Missing/placeholder FOUNDRY_PROJECT_ENDPOINT in .env. Set it to e.g.\n"
            "  https://mydevfoundry0603.services.ai.azure.com/api/projects/<project-name>"
        )

    model = os.getenv("FOUNDRY_MODEL_DEPLOYMENT", "gpt-5.4").strip()
    return endpoint, model


def build_credential() -> ChainedTokenCredential:
    """Managed Identity (in Azure) then Azure CLI credential (local dev)."""
    return ChainedTokenCredential(ManagedIdentityCredential(), AzureCliCredential())


def di_text(data: dict) -> str:
    if data.get("content"):
        return data["content"]
    parts: list[str] = []
    for page in data.get("pages") or []:
        for line in page.get("lines") or []:
            parts.append(line.get("content", ""))
    return "\n".join(parts)


def agent_text(data: dict) -> str:
    result = data.get("result", data)
    if result.get("content"):
        return result["content"]
    parts: list[str] = []
    for page in result.get("pages") or []:
        parts.extend(page.get("lines") or [])
    return "\n".join(parts)


def extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Judge output did not contain a JSON object.")
    return json.loads(text[start : end + 1])


def judge_one(openai_client, model: str, pdf_path: Path, di: dict, agent: dict) -> dict:
    """Ask gpt-5.4 to judge both transcriptions against the original PDF."""
    data_uri = "data:application/pdf;base64," + base64.b64encode(
        pdf_path.read_bytes()
    ).decode("ascii")

    prompt = (
        "Original document is attached. Adjudicate the two OCR transcriptions "
        "below against it and return the verdict JSON.\n\n"
        "=== Engine A: Document Intelligence transcription ===\n"
        f"{di_text(di)}\n\n"
        "=== Engine B: gpt-5.4 agent transcription ===\n"
        f"{agent_text(agent)}\n"
    )

    response = openai_client.responses.create(
        model=model,
        instructions=JUDGE_INSTRUCTIONS,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_file",
                        "filename": pdf_path.name,
                        "file_data": data_uri,
                    },
                ],
            }
        ],
    )
    return extract_json(response.output_text)


def build_markdown(name: str, verdict: dict) -> str:
    lines: list[str] = []
    lines.append(f"# OCR Verdict — {name}")
    lines.append("")
    lines.append(f"- **Generated:** {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- **Judge model:** gpt-5.4 (reads the original PDF as ground truth)")
    lines.append("")

    winner = verdict.get("winner", "?")
    pretty = {"doc_intelligence": "Document Intelligence", "agent": "Foundry Agent (gpt-5.4)"}
    lines.append(f"## Winner: **{pretty.get(winner, winner)}**")
    lines.append("")
    summary = verdict.get("summary")
    if summary:
        lines.append(summary)
        lines.append("")

    overall = verdict.get("overall_score") or {}
    scores = verdict.get("scores") or {}
    lines.append("## Scores")
    lines.append("")
    lines.append("| Dimension | Document Intelligence | Foundry Agent (gpt-5.4) |")
    lines.append("| --- | ---: | ---: |")
    for dim in ("accuracy", "completeness", "structure", "hallucination"):
        di_v = (scores.get("doc_intelligence") or {}).get(dim, "-")
        ag_v = (scores.get("agent") or {}).get(dim, "-")
        lines.append(f"| {dim.capitalize()} | {di_v} | {ag_v} |")
    lines.append(
        f"| **Overall** | **{overall.get('doc_intelligence', '-')}** "
        f"| **{overall.get('agent', '-')}** |"
    )
    lines.append("")

    fields = verdict.get("critical_field_adjudication") or []
    if fields:
        lines.append("## Critical field adjudication")
        lines.append("")
        lines.append("| Field | Ground truth | Doc Intelligence | Agent | Correct |")
        lines.append("| --- | --- | --- | --- | --- |")
        for f in fields:
            lines.append(
                f"| {f.get('field','')} | {f.get('ground_truth','')} "
                f"| {f.get('doc_intelligence','')} | {f.get('agent','')} "
                f"| {f.get('correct','')} |"
            )
        lines.append("")

    di_errs = verdict.get("doc_intelligence_errors") or []
    ag_errs = verdict.get("agent_errors") or []
    lines.append(f"## Document Intelligence errors ({len(di_errs)})")
    lines.append("")
    lines.extend([f"- {e}" for e in di_errs] or ["_None reported._"])
    lines.append("")
    lines.append(f"## Agent errors ({len(ag_errs)})")
    lines.append("")
    lines.extend([f"- {e}" for e in ag_errs] or ["_None reported._"])
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    if not OUTPUT_DIR.exists():
        print(f"No output folder at {OUTPUT_DIR}. Run main.py and agent_ocr.py first.")
        return

    di_files = {p.stem: p for p in OUTPUT_DIR.glob("*.json") if not p.name.endswith(".agent.json")}
    agent_files = {p.name[: -len(".agent.json")]: p for p in OUTPUT_DIR.glob("*.agent.json")}

    common = sorted(set(di_files) & set(agent_files))
    if not common:
        print(
            "No documents have both outputs. Run main.py and agent_ocr.py on the "
            "same PDF first."
        )
        return

    endpoint, model = get_config()
    project = AIProjectClient(endpoint=endpoint, credential=build_credential())
    openai_client = project.get_openai_client()
    print(f"Judging {len(common)} document(s) with '{model}' as ground-truth adjudicator.\n")

    roll_up: list[dict] = []
    failures = 0
    for name in common:
        pdf_path = INPUT_DIR / f"{name}.pdf"
        if not pdf_path.exists():
            print(f"  SKIP {name}: original PDF not found at {pdf_path.relative_to(BASE_DIR)}")
            continue

        try:
            di = json.loads(di_files[name].read_text(encoding="utf-8"))
            agent = json.loads(agent_files[name].read_text(encoding="utf-8"))
            verdict = judge_one(openai_client, model, pdf_path, di, agent)

            json_path = OUTPUT_DIR / f"{name}.verdict.json"
            json_path.write_text(
                json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            md_path = OUTPUT_DIR / f"{name}.verdict.md"
            md_path.write_text(build_markdown(name, verdict), encoding="utf-8")

            overall = verdict.get("overall_score") or {}
            print(
                f"  {name}: winner={verdict.get('winner','?')} "
                f"(DI {overall.get('doc_intelligence','-')} vs "
                f"agent {overall.get('agent','-')}) -> {md_path.relative_to(BASE_DIR)}"
            )
            roll_up.append({"document": name, **verdict})
        except Exception as exc:  # noqa: BLE001 - report and continue
            failures += 1
            print(f"  ERROR judging {name}: {exc}")

    if roll_up:
        summary_path = OUTPUT_DIR / "verdict-summary.json"
        summary_path.write_text(
            json.dumps(roll_up, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nDone. {len(roll_up)} judged, {failures} failed. "
              f"Summary -> {summary_path.relative_to(BASE_DIR)}")
    else:
        print(f"\nNo verdicts produced ({failures} failed).")


if __name__ == "__main__":
    main()
