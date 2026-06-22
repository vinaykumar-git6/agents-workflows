"""Foundry chat-agent configuration and factory for AWB normalization.

The agent runs deterministically (low temperature + fixed seed + structured
output) so the same OCR text always yields identical normalized JSON.
"""
from __future__ import annotations

import os

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity.aio import DefaultAzureCredential as AioDefaultAzureCredential

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID") or None

# Determinism: low temperature + fixed seed so the agent output is stable across
# runs for the same OCR input.
AGENT_TEMPERATURE = float(os.getenv("AWB_AGENT_TEMPERATURE", "0"))
AGENT_TOP_P = float(os.getenv("AWB_AGENT_TOP_P", "1"))
AGENT_SEED = int(os.getenv("AWB_AGENT_SEED", "12345"))

AGENT_INSTRUCTIONS = """\
You are an expert air-cargo documentation analyst. You are given the raw OCR text
extracted from a single Air Waybill (AWB). Produce a clean, normalized,
unambiguous structured record that exactly matches the required schema.

Rules:
- Extract values ONLY from the provided OCR text. Never invent or guess data.
- If a field is not present or is unreadable, leave it null (or an empty list).
- NORMALIZE aggressively and consistently:
  * AWB number -> "PREFIX-SERIAL" (3 digits, dash, 8 digits). Also fill awb_prefix
    and awb_serial separately. Strip spaces and stray characters.
  * Names/addresses -> Title Case, collapse repeated whitespace and broken lines
    into a single clean line. Remove OCR artifacts (e.g. stray '|', duplicated
    tokens, hyphenation at line breaks).
  * Dates -> ISO 8601 (YYYY-MM-DD). Interpret common formats (e.g. 18JUN2026).
  * Weights -> numeric only; put the unit in weight_unit as "KG" or "LB".
  * Currency -> ISO 4217 code (e.g. USD, AED, EUR).
  * Airport codes -> uppercase 3-letter IATA codes.
  * Numbers -> remove thousands separators; use a dot as the decimal separator.
- Do not include commentary, explanations, or markdown. Return ONLY the
  structured record.
- Be deterministic: given the same OCR text, always produce identical output.
"""


def is_enabled() -> bool:
    return bool(AZURE_OPENAI_ENDPOINT)


def _credential() -> AioDefaultAzureCredential:
    if AZURE_CLIENT_ID:
        return AioDefaultAzureCredential(managed_identity_client_id=AZURE_CLIENT_ID)
    return AioDefaultAzureCredential()


def create_agent() -> ChatAgent:
    """Build the deterministic AWB normalization chat agent."""
    if not AZURE_OPENAI_ENDPOINT:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT is not configured.")

    chat_client = AzureOpenAIChatClient(
        endpoint=AZURE_OPENAI_ENDPOINT,
        deployment_name=AZURE_OPENAI_DEPLOYMENT,
        api_version=AZURE_OPENAI_API_VERSION,
        credential=_credential(),
    )
    return chat_client.create_agent(
        name="awb-agent",
        instructions=AGENT_INSTRUCTIONS,
    )
