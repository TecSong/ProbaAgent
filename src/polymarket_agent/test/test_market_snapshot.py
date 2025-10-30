from __future__ import annotations

import os
from typing import Any, Dict, List

os.environ.setdefault("POLYMARKET_ALLOW_TELEGRAM_STUBS", "1")

from scripts.telegram_bot import _collect_market_snapshot


class _StubClient:
    def __init__(self, payload: Dict[str, Any], detail_map: Dict[str, Dict[str, Any]]):
        self._payload = payload
        self._detail_map = detail_map
        self.search_queries: List[str] = []
        self.detail_calls: List[str] = []
        self.price_calls: List[tuple[str, str]] = []

    def search_markets_events_profiles(self, query: str) -> Dict[str, Any]:
        self.search_queries.append(query)
        return self._payload

    def get_market_detail(self, market_id: str) -> Dict[str, Any]:
        self.detail_calls.append(market_id)
        return self._detail_map[market_id]

    def get_market_price(self, token_id: str, side: str) -> Any:  # pragma: no cover - should not be used
        self.price_calls.append((token_id, side))
        raise AssertionError("Price lookup should not be invoked in snapshot tests.")


def test_collect_market_snapshot_from_event_markets() -> None:
    payload = {
        "events": [
            {
                "title": "Bitcoin price in October",
                "markets": [
                    {
                        "id": "618949",
                        "question": "Will Bitcoin reach $200k in October?",
                    }
                ],
            }
        ]
    }
    detail_map = {
        "618949": {
            "question": "Will Bitcoin reach $200k in October?",
            "status": "open",
            "end_date": "2025-11-01T00:00:00Z",
            "volume24h": 1000,
            "liquidity": 500,
            "outcomes": [],
        }
    }

    client = _StubClient(payload, detail_map)

    snapshot = _collect_market_snapshot(client, "  bitcoin  ")

    assert snapshot is not None
    assert "Market ID: 618949" in snapshot
    assert "Event: Bitcoin price in October" in snapshot
    assert client.search_queries == ["bitcoin"]
    assert client.detail_calls == ["618949"]
    assert client.price_calls == []


def test_collect_market_snapshot_deduplicates_event_results() -> None:
    payload = {
        "events": [
            {
                "title": "US Presidential Election",
                "markets": [
                    {"marketId": "12345"},
                ],
            }
        ],
        "results": [
            {
                "type": "event",
                "event": {
                    "title": "US Presidential Election",
                    "markets": [
                        {"id": "12345"},
                    ],
                },
            },
            {
                "type": "market",
                "market": {"id": "12345"},
            },
        ],
    }
    detail_map = {
        "12345": {
            "market": {
                "question": "Who will win the 2024 US Presidential Election?",
                "status": "open",
            },
            "tokens": [],
        }
    }

    client = _StubClient(payload, detail_map)

    snapshot = _collect_market_snapshot(client, "election")

    assert snapshot is not None
    assert "Market ID: 12345" in snapshot
    assert len(client.detail_calls) == 1
    assert client.price_calls == []
