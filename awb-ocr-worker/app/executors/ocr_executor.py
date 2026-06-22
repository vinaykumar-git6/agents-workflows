"""OCR executor: runs Document Intelligence and emits text + Markdown."""
from __future__ import annotations

import logging

from agent_framework import Executor, WorkflowContext, handler

from app.orchestration.messages import OcrPayload, OcrRequest
from app.services import ocr

logger = logging.getLogger("awb.executor.ocr")


class OcrExecutor(Executor):
    """Runs Document Intelligence OCR (retry + circuit breaker) and emits the
    raw text plus a Markdown rendering for the downstream formatter."""

    @handler
    async def run(self, request: OcrRequest, ctx: WorkflowContext[OcrPayload]) -> None:
        result = ocr.run_ocr(request.pdf_bytes)  # retry + circuit breaker inside
        text = result.content or ""
        markdown = ocr.build_markdown(request.source_name, result)
        logger.info("OCR completed for %s (%d chars).", request.source_name, len(text))
        await ctx.send_message(OcrPayload(text=text, markdown=markdown))
