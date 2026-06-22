"""Formatter executor: sends OCR text to the deterministic AWB agent and yields
the normalized JSON output."""
from __future__ import annotations

import logging
from typing import Never

from agent_framework import Executor, WorkflowContext, handler

from app.orchestration.agent import AGENT_SEED, AGENT_TEMPERATURE, AGENT_TOP_P
from app.orchestration.messages import FormattedResult, OcrPayload
from app.orchestration.schema import AwbDocument

logger = logging.getLogger("awb.executor.formatter")


class AwbFormatterExecutor(Executor):
    """Sends OCR text to the deterministic AWB agent and yields normalized JSON."""

    def __init__(self, agent, executor_id: str = "awb_formatter") -> None:
        super().__init__(id=executor_id)
        self._agent = agent

    @handler
    async def run(
        self, payload: OcrPayload, ctx: WorkflowContext[Never, FormattedResult]
    ) -> None:
        if not payload.text.strip():
            logger.warning("Empty OCR text; emitting empty AWB document.")
            empty = AwbDocument()
            await ctx.yield_output(
                FormattedResult(
                    json_text=empty.model_dump_json(indent=2),
                    markdown=payload.markdown,
                )
            )
            return

        response = await self._agent.run(
            payload.text,
            response_format=AwbDocument,
            temperature=AGENT_TEMPERATURE,
            top_p=AGENT_TOP_P,
            seed=AGENT_SEED,
        )
        doc = response.value if response.value is not None else AwbDocument()
        if not isinstance(doc, AwbDocument):
            doc = AwbDocument.model_validate(doc)

        await ctx.yield_output(
            FormattedResult(
                json_text=doc.model_dump_json(indent=2),
                markdown=payload.markdown,
            )
        )
