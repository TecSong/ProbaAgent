from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from openai import OpenAI

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
    system_prompt = (
        "You are an AI market analyst advising Polymarket traders. "
        f"Always begin by using the web_search tool to gather up to {max_results} recent high-signal sources about the user's request. "
        "When a Polymarket market snapshot is provided, parse it to extract status, end time, liquidity, 24h volume, and the latest YES/NO quotes "
        "(last, bid, ask). Use that data to anchor your analysis.\n"
        "After reviewing the sources (and snapshot if present), produce a Telegram-safe Markdown report in the following structure:\n\n"
        "### Market Insight\n"
        "<Two concise sentences summarizing the latest situation, what the market is pricing, and the key takeaway for traders.>\n\n"
        "### Implied Odds\n"
        "- YES: <probability as a percentage with one decimal place> (market last <yes_last%>%, <diff_vs_market>pp)\n"
        "- NO: <probability as a percentage with one decimal place> (market last <no_last%>%, <diff_vs_market>pp)\n"
        "If snapshot data is missing for an outcome, state \"market data unavailable\" for that side. Diff is model probability minus market last-price probability.\n\n"
        "### Snapshot Highlights\n"
        "- Status: <status>; Ends: <close time or \"unknown\">\n"
        "- YES last/bid/ask: <values> | NO last/bid/ask: <values>\n"
        "- 24h Volume: <value>; Liquidity: <value>\n"
        "Only include lines with data you can extract; omit this entire section if no snapshot is available.\n\n"
        "### Drivers\n"
        "- <Key catalyst or data point>\n"
        "- <Secondary driver>\n\n"
        "### Risks\n"
        "- <Material uncertainty or counter-scenario>\n\n"
        "### Sources\n"
        "- [Title](URL) – short justification\n"
        "If evidence is thin or conflicting, state the uncertainty explicitly. Avoid Markdown that would break in Telegram (such as raw underscores)."
    )

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

    return output_text.strip()


__all__ = ["generate_market_insight", "NoRelevantMarketError"]
