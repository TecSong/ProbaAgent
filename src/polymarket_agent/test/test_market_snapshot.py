from __future__ import annotations

import os
import pytest
import sys
import types
from typing import Any, Dict, List

os.environ.setdefault("POLYMARKET_ALLOW_TELEGRAM_STUBS", "1")

if "web3" not in sys.modules:
    web3_module = types.ModuleType("web3")

    class _StubWeb3:
        def __init__(self, *args, **kwargs):  # noqa: D401 - simple stub
            pass

        @staticmethod
        def HTTPProvider(*args, **kwargs):
            return object()

        @staticmethod
        def to_checksum_address(value: Any) -> str:
            return str(value)

    web3_module.Web3 = _StubWeb3

    middleware_module = types.ModuleType("web3.middleware")
    middleware_module.ExtraDataToPOAMiddleware = object
    web3_module.middleware = middleware_module

    contract_module = types.ModuleType("web3.contract")

    class _StubContract:  # noqa: D401 - placeholder contract type
        pass

    contract_module.Contract = _StubContract

    sys.modules["web3"] = web3_module
    sys.modules["web3.middleware"] = middleware_module
    sys.modules["web3.contract"] = contract_module

if "supabase" not in sys.modules:
    supabase_module = types.ModuleType("supabase")

    class _StubSupabaseClient:  # noqa: D401 - placeholder client type
        pass

    def _stub_create_client(*args, **kwargs):  # noqa: D401 - placeholder factory
        raise RuntimeError("Supabase client is not available in tests.")

    supabase_module.Client = _StubSupabaseClient
    supabase_module.create_client = _stub_create_client
    sys.modules["supabase"] = supabase_module

from polymarket_agent.telegram.snapshot import NoRelevantMarketError, collect_market_snapshot


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

    snapshot = collect_market_snapshot(client, "  bitcoin  ")

    assert snapshot is not None
    assert "Market 618949: Will Bitcoin reach $200k in October?" in snapshot
    assert "Event: Bitcoin price in October" in snapshot
    assert "Timing: Start: n/a; End: 2025-11-01 00:00; Status: open" in snapshot
    assert "Liquidity: $500; Volume: $1K (24h)" in snapshot
    assert "Outcome prices: n/a" in snapshot
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

    snapshot = collect_market_snapshot(client, "election")

    assert snapshot is not None
    assert "Market 12345:" in snapshot
    assert len(client.detail_calls) == 1
    assert client.price_calls == []


def test_collect_market_snapshot_filters_irrelevant_events() -> None:
    payload = {
        "events": [
            {
                "title": "Weather in Paris",
                "markets": [
                    {"id": "777"},
                ],
            }
        ]
    }
    client = _StubClient(payload, detail_map={})

    with pytest.raises(NoRelevantMarketError):
        collect_market_snapshot(client, "bitcoin price")

    assert client.detail_calls == []


def test_collect_market_snapshot_includes_core_fields() -> None:
    payload = {
        "markets": [
            {
                "id": "555",
                "question": "Will ETH stay above $5k?",
            }
        ]
    }
    detail_map = {
        "555": {
            "market": {
                "question": "Will ETH stay above $5k?",
                "status": "open",
                "startDate": "2025-01-10T08:30:00Z",
                "endDate": "2025-02-01T00:00:00Z",
                "volume": 12_345,
                "liquidity": 6_789,
                "outcomes": ["Yes", "No"],
                "outcomePrices": [0.65, 0.35],
            }
        }
    }

    client = _StubClient(payload, detail_map)

    snapshot = collect_market_snapshot(client, "eth")

    assert snapshot is not None
    assert "Market 555: Will ETH stay above $5k?" in snapshot
    assert "Timing: Start: 2025-01-10 08:30; End: 2025-02-01 00:00; Status: open" in snapshot
    assert "Liquidity: $6.8K; Volume: $12.3K" in snapshot
    assert "Outcome prices: Yes 0.65; No 0.35" in snapshot


def test_collect_market_snapshot_prefers_best_numeric_match() -> None:
    payload = {
        "events": [
            {
                "title": "Bitcoin above ___ on November 7?",
                "markets": [
                    {
                        "id": "600",
                        "question": "Will the price of Bitcoin be above $98,000 on November 7?",
                        "groupItemTitle": "98,000",
                    },
                    {
                        "id": "602",
                        "question": "Will the price of Bitcoin be above $102,000 on November 7?",
                        "groupItemTitle": "102,000",
                    },
                ],
            }
        ]
    }
    detail_map = {
        "600": {
            "market": {
                "question": "Will the price of Bitcoin be above $98,000 on November 7?",
                "status": "closed",
                "endDate": "2025-11-07T17:00:00Z",
                "startDate": "2025-10-31T16:00:00Z",
                "volume": 100_000,
                "liquidity": 4_000,
                "outcomes": ["Yes", "No"],
                "outcomePrices": [1, 0],
            }
        },
        "602": {
            "market": {
                "question": "Will the price of Bitcoin be above $102,000 on November 7?",
                "status": "closed",
                "endDate": "2025-11-07T17:00:00Z",
                "startDate": "2025-10-31T16:05:00Z",
                "volume": 200_000,
                "liquidity": 5_000,
                "outcomes": ["Yes", "No"],
                "outcomePrices": [0.2, 0.8],
            }
        },
    }

    client = _StubClient(payload, detail_map)

    snapshot = collect_market_snapshot(client, "BTC 102k November 7")

    assert snapshot is not None
    assert "Market 602: Will the price of Bitcoin be above $102,000 on November 7?" in snapshot
    assert client.detail_calls[0] == "602"
