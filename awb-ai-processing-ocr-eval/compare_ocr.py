"""Compare OCR results: Azure Document Intelligence vs Foundry agent (gpt-5.4).

For each document that has BOTH outputs in `output/`:

  - <name>.json        : produced by main.py        (Document Intelligence)
  - <name>.agent.json  : produced by agent_ocr.py   (Foundry gpt-5.4 agent)

this script extracts the plain text from each, computes similarity and
coverage metrics, and writes:

  - <name>.compare.md         : per-document side-by-side comparison
  - comparison-summary.json   : machine-readable roll-up of all documents

No Azure calls are made — this works purely on the local JSON files.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def normalize(text: str) -> str:
    """Lowercase and collapse all whitespace for fair comparison."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def words(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def di_text(data: dict) -> str:
    """Extract the full text from a Document Intelligence result."""
    if data.get("content"):
        return data["content"]
    # Fallback: stitch page lines together.
    parts: list[str] = []
    for page in data.get("pages") or []:
        for line in page.get("lines") or []:
            parts.append(line.get("content", ""))
    return "\n".join(parts)


def agent_text(data: dict) -> str:
    """Extract the full text from a Foundry agent result."""
    result = data.get("result", data)
    if result.get("content"):
        return result["content"]
    parts: list[str] = []
    for page in result.get("pages") or []:
        parts.extend(page.get("lines") or [])
    return "\n".join(parts)


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def compare_pair(name: str, di: dict, agent: dict) -> dict:
    """Compute comparison metrics for one document."""
    di_raw = di_text(di)
    ag_raw = agent_text(agent)

    di_norm = normalize(di_raw)
    ag_norm = normalize(ag_raw)

    di_words = words(di_raw)
    ag_words = words(ag_raw)

    seq_ratio = SequenceMatcher(None, di_norm, ag_norm).ratio()
    word_jaccard = jaccard(di_words, ag_words)

    di_set, ag_set = set(di_words), set(ag_words)
    only_di = sorted(di_set - ag_set)
    only_agent = sorted(ag_set - di_set)

    return {
        "document": name,
        "doc_intelligence": {
            "char_count": len(di_raw),
            "word_count": len(di_words),
            "unique_words": len(di_set),
        },
        "agent": {
            "char_count": len(ag_raw),
            "word_count": len(ag_words),
            "unique_words": len(ag_set),
        },
        "similarity": {
            "sequence_ratio": round(seq_ratio, 4),
            "word_jaccard": round(word_jaccard, 4),
        },
        "words_only_in_doc_intelligence": only_di,
        "words_only_in_agent": only_agent,
    }


def write_markdown(name: str, metrics: dict) -> Path:
    di = metrics["doc_intelligence"]
    ag = metrics["agent"]
    sim = metrics["similarity"]

    lines: list[str] = []
    lines.append(f"# OCR Comparison — {name}")
    lines.append("")
    lines.append("| Metric | Document Intelligence | Foundry Agent (gpt-5.4) |")
    lines.append("| --- | ---: | ---: |")
    lines.append(f"| Characters | {di['char_count']} | {ag['char_count']} |")
    lines.append(f"| Words | {di['word_count']} | {ag['word_count']} |")
    lines.append(f"| Unique words | {di['unique_words']} | {ag['unique_words']} |")
    lines.append("")
    lines.append("## Similarity")
    lines.append("")
    lines.append(f"- **Sequence ratio:** {sim['sequence_ratio']:.4f} (1.0 = identical text)")
    lines.append(f"- **Word Jaccard:** {sim['word_jaccard']:.4f} (1.0 = identical word sets)")
    lines.append("")

    only_di = metrics["words_only_in_doc_intelligence"]
    only_ag = metrics["words_only_in_agent"]

    lines.append(f"## Words only in Document Intelligence ({len(only_di)})")
    lines.append("")
    lines.append(", ".join(only_di) if only_di else "_None_")
    lines.append("")
    lines.append(f"## Words only in Agent ({len(only_ag)})")
    lines.append("")
    lines.append(", ".join(only_ag) if only_ag else "_None_")
    lines.append("")

    md_path = OUTPUT_DIR / f"{name}.compare.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def main() -> None:
    if not OUTPUT_DIR.exists():
        print(f"No output folder at {OUTPUT_DIR}. Run main.py and agent_ocr.py first.")
        return

    di_files = {p.stem: p for p in OUTPUT_DIR.glob("*.json") if not p.name.endswith(".agent.json")}
    agent_files = {
        p.name[: -len(".agent.json")]: p for p in OUTPUT_DIR.glob("*.agent.json")
    }

    common = sorted(set(di_files) & set(agent_files))
    if not common:
        print(
            "No documents have both outputs.\n"
            f"  Document Intelligence (*.json): {sorted(di_files) or 'none'}\n"
            f"  Agent (*.agent.json):          {sorted(agent_files) or 'none'}\n"
            "Run main.py and agent_ocr.py on the same PDF first."
        )
        return

    summary: list[dict] = []
    for name in common:
        di = json.loads(di_files[name].read_text(encoding="utf-8"))
        agent = json.loads(agent_files[name].read_text(encoding="utf-8"))

        metrics = compare_pair(name, di, agent)
        md_path = write_markdown(name, metrics)
        summary.append(metrics)

        sim = metrics["similarity"]
        print(
            f"  {name}: sequence={sim['sequence_ratio']:.3f} "
            f"jaccard={sim['word_jaccard']:.3f} -> {md_path.relative_to(BASE_DIR)}"
        )

    summary_path = OUTPUT_DIR / "comparison-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nCompared {len(common)} document(s). Summary -> {summary_path.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
