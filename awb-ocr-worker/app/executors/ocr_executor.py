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
        logger.info("OCR -> starting for %s (%d bytes).", request.source_name, len(request.pdf_bytes))
        result = ocr.run_ocr(request.pdf_bytes)  # retry + circuit breaker inside
        text = result.content or ""
        markdown = ocr.build_markdown(request.source_name, result)
        logger.info("OCR <- completed for %s (%d chars).", request.source_name, len(text))
        logger.debug("OCR <- extracted text for %s:\n%s", request.source_name, text)
        await ctx.send_message(OcrPayload(text=text, markdown=markdown))
