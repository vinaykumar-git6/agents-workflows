"""Sequential workflow orchestrator for AWB OCR post-processing.

Chains two executors with a sequential edge:

    OcrExecutor  ──▶  AwbFormatterExecutor (ChatAgent, Microsoft Foundry)

1. OcrExecutor       — runs Azure AI Document Intelligence on the PDF bytes
                       (with retry + circuit breaker) and emits the raw OCR
                       text plus a Markdown rendering.
2. AwbFormatterExecutor — sends the OCR text to a Foundry-hosted chat agent
                       (gpt-5.4) that cleans up and *normalizes* the data into a
                       strict AWB JSON schema, deterministically.

The orchestration returns the normalized JSON (saved as `<awb>.json`) and the
OCR Markdown (saved as `<awb>.md`). The raw OCR result is NOT persisted as JSON.
"""
from __future__ import annotations

import logging

from agent_framework import WorkflowBuilder

from app.executors.formatter_executor import AwbFormatterExecutor
from app.executors.ocr_executor import OcrExecutor
from app.orchestration.agent import create_agent, is_enabled
from app.orchestration.messages import FormattedResult, OcrRequest

logger = logging.getLogger("awb.orchestrator")

__all__ = ["is_enabled", "run_orchestration"]


def _build_workflow():
    agent = create_agent()
    ocr_executor = OcrExecutor(id="ocr_executor")
    formatter = AwbFormatterExecutor(agent=agent)

    return (
        WorkflowBuilder(start_executor=ocr_executor)
        .add_edge(ocr_executor, formatter)
        .build()
    )


async def run_orchestration(pdf_bytes: bytes, source_name: str) -> tuple[str, str]:
    """Run OCR -> AWB-agent sequential workflow.

    Returns (normalized_json_text, ocr_markdown_text).

    A fresh workflow is built per call: the Agent Framework workflow creates
    asyncio primitives (queues/futures) bound to the *current* event loop. The
    consumer invokes this via ``asyncio.run`` per message (a new loop each
    time), so a cached workflow would raise "bound to a different event loop"
    on the second message.
    """
    workflow = _build_workflow()
    run_result = await workflow.run(
        OcrRequest(pdf_bytes=pdf_bytes, source_name=source_name)
    )
    outputs = run_result.get_outputs()
    if not outputs:
        raise RuntimeError("AWB orchestration produced no output.")
    final: FormattedResult = outputs[0]
    return final.json_text, final.markdown
