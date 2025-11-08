from __future__ import annotations

from typing import Any

__all__ = [
    "build_application",
    "main",
    "collect_market_snapshot",
    "format_usd",
    "NoRelevantMarketError",
    "generate_market_insight",
]


def __getattr__(name: str) -> Any:
    if name in {"build_application", "main"}:
        from .app import build_application, main

        return {"build_application": build_application, "main": main}[name]
    if name in {"collect_market_snapshot", "format_usd", "NoRelevantMarketError"}:
        from .snapshot import collect_market_snapshot, format_usd, NoRelevantMarketError

        return {
            "collect_market_snapshot": collect_market_snapshot,
            "format_usd": format_usd,
            "NoRelevantMarketError": NoRelevantMarketError,
        }[name]
    if name == "generate_market_insight":
        from .insight import generate_market_insight

        return generate_market_insight
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(__all__)
