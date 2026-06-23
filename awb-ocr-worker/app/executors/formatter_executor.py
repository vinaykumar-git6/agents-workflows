"""Formatter executor: sends OCR text to the deterministic AWB agent and yields
the normalized JSON output."""
from __future__ import annotations

import json
import logging
from typing import Never

from agent_framework import Executor, WorkflowContext, handler

from app.orchestration.agent import AGENT_SEED, AGENT_TEMPERATURE, AGENT_TOP_P, AGENT_INSTRUCTIONS
from app.orchestration.messages import FormattedResult, OcrPayload
from app.orchestration.schema import AwbDocument

logger = logging.getLogger("awb.executor.formatter")


class AwbFormatterExecutor(Executor):
    """Sends OCR text to the deterministic AWB agent and yields normalized JSON."""

    def __init__(self, agent, executor_id: str = "awb_formatter") -> None:
        super().__init__(id=executor_id)
        self._client = agent

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

        # Use OpenAI's structured output API for deterministic JSON responses
        user_content = f"Extract and normalize this AWB data:\n\n{payload.text}"
        logger.info("AGENT -> sending OCR text to agent (%d chars).", len(payload.text))
        logger.debug("AGENT -> request payload:\n%s", user_content)
        try:
            response = self._client.beta.chat.completions.parse(
                model="gpt-5.4",
                temperature=AGENT_TEMPERATURE,
                top_p=AGENT_TOP_P,
                seed=AGENT_SEED,
                messages=[
                    {
                        "role": "system",
                        "content": AGENT_INSTRUCTIONS,
                    },
                    {
                        "role": "user",
                        "content": user_content,
                    },
                ],
                response_format=AwbDocument,
            )

            # Extract the parsed response
            raw_content = response.choices[0].message.content
            logger.info("AGENT <- received response (finish_reason=%s).",
                        response.choices[0].finish_reason)
            logger.debug("AGENT <- raw response content:\n%s", raw_content)
            doc = response.choices[0].message.parsed
            if doc is None:
                logger.warning("Agent returned no structured output; using empty AWB document.")
                doc = AwbDocument()

            # Ensure it's an AwbDocument instance
            if not isinstance(doc, AwbDocument):
                doc = AwbDocument.model_validate(doc)

            json_text = doc.model_dump_json(indent=2)
            logger.debug("AGENT <- normalized JSON:\n%s", json_text)
            await ctx.yield_output(
                FormattedResult(
                    json_text=json_text,
                    markdown=payload.markdown,
                )
            )
        except Exception:
            logger.exception("Failed to format with agent; returning empty document")
            empty = AwbDocument()
            await ctx.yield_output(
                FormattedResult(
                    json_text=empty.model_dump_json(indent=2),
                    markdown=payload.markdown,
                )
            )
