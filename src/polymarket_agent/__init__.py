"""Polymarket agent public API with lazy imports to avoid heavy dependencies."""

from __future__ import annotations

from typing import Any

__all__ = ["build_polymarket_agent", "PolymarketClient", "PolymarketClientError"]


def __getattr__(name: str) -> Any:
    if name == "build_polymarket_agent":
        from .agent import build_polymarket_agent as builder

        return builder
    if name in {"PolymarketClient", "PolymarketClientError"}:
        from .client import PolymarketClient, PolymarketClientError  # noqa: WPS433 - lazy import

        return {"PolymarketClient": PolymarketClient, "PolymarketClientError": PolymarketClientError}[name]
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(__all__)
