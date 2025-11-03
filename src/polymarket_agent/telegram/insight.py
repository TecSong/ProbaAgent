from __future__ import annotations

import re
import logging
import os
from typing import Any, Dict, List

from openai import OpenAI

from polymarket_agent.prompt import SYSTEM_PROMPT_STR

from .snapshot import NoRelevantMarketError, collect_market_snapshot

LOGGER = logging.getLogger(__name__)

_OPENAI_WEB_SEARCH_MODEL = os.getenv("OPENAI_WEB_SEARCH_MODEL", "gpt-4.1-mini")
_openai_client: OpenAI | None = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


def generate_market_insight(client: Any, query: str, max_results: int = 6) -> str:
    system_prompt = SYSTEM_PROMPT_STR

    user_prompt = (
        "Target market or event: {query}\n"
        "Estimate odds from the perspective of a Polymarket YES contract. Ensure YES and NO sum to 100%."
    ).format(query=query)

    snapshot_text = collect_market_snapshot(client, query)
    if snapshot_text:
        user_prompt += "\n\nPolymarket internal data snapshot:\n" + snapshot_text

    try:
        response = _get_openai_client().responses.create(
            model=_OPENAI_WEB_SEARCH_MODEL,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_prompt}],
                },
            ],
            tools=[{"type": "web_search"}],
        )
    except NoRelevantMarketError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"OpenAI insight request failed: {exc}") from exc

    output_text = getattr(response, "output_text", None)
    if not output_text:
        chunks: List[str] = []
        try:
            for item in getattr(response, "output", []) or []:
                for content in getattr(item, "content", []) or []:
                    text = getattr(content, "text", None)
                    if text:
                        chunks.append(text)
        except Exception:  # pragma: no cover - defensive fallback
            chunks = []
        if chunks:
            output_text = "".join(chunks)

    if not output_text:
        raise RuntimeError("OpenAI insight response was empty.")

    normalized = output_text.strip()
    normalized = re.sub(r"(?m)^(?P<indent>\s*)-\s+", r"\g<indent>• ", normalized)
    return normalized


__all__ = ["generate_market_insight", "NoRelevantMarketError"]
