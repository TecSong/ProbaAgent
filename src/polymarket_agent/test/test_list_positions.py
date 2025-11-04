from __future__ import annotations

from typing import Dict, List, Optional

import pytest

from polymarket_agent import client as client_module
from polymarket_agent.client import (
    PolymarketClient,
    PolymarketClientConfig,
    PolymarketClientError,
)
from polymarket_agent.tools import build_polymarket_tools


class _DummyClobClient:
    """Minimal py-clob-client stub used for tests."""

    def __init__(self, address: str = "0x000000000000000000000000000000000000dEaD") -> None:
        self._address = address

    def get_address(self) -> str:
        return self._address


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> PolymarketClient:
    """Return a PolymarketClient instance backed by a dummy CLOB client."""

    monkeypatch.setattr(
        client_module,
        "_get_clob_client",
        lambda config: _DummyClobClient(),
    )

    config = PolymarketClientConfig(
        host="https://clob.polymarket.com",
        private_key="0x1",
        chain_id=137,
    )
    return PolymarketClient(config)


def test_list_positions_with_explicit_wallet(monkeypatch: pytest.MonkeyPatch, client: PolymarketClient) -> None:
    captured: Dict[str, object] = {}

    def fake_data_api(self, method: str, path: str, params: Dict[str, str] | None = None):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return [{"position_id": "1"}]

    monkeypatch.setattr(client_module.PolymarketClient, "_data_api_request", fake_data_api)

    result = client.list_positions(" 0xabc123 ")

    assert result == [{"position_id": "1"}]
    assert captured == {
        "method": "GET",
        "path": "/positions",
        "params": {"user": "0xabc123"},
    }


def test_list_positions_requires_platform_when_wallet_missing(client: PolymarketClient) -> None:
    with pytest.raises(PolymarketClientError):
        client.list_positions(wallet_address=None)


def test_list_positions_uses_platform_context(monkeypatch: pytest.MonkeyPatch, client: PolymarketClient) -> None:
    calls: List[tuple[Optional[str], Optional[str]]] = []

    def fake_ensure(self, platform: Optional[str], platform_id: Optional[str]) -> None:
        calls.append((platform, platform_id))
        self._wallet_address = "0x1234567890abcdef1234567890abcdef12345678"

    def fake_data_api(self, method: str, path: str, params: Dict[str, str] | None = None):
        return params

    monkeypatch.setattr(client_module.PolymarketClient, "_ensure_user_client", fake_ensure)
    monkeypatch.setattr(client_module.PolymarketClient, "_data_api_request", fake_data_api)

    result = client.list_positions(platform="telegram", platform_id="42")

    assert calls == [("telegram", "42")]
    assert result == {"user": "0x1234567890abcdef1234567890abcdef12345678"}


def test_positions_tool_returns_positions(monkeypatch: pytest.MonkeyPatch, client: PolymarketClient) -> None:
    sample = [
        {
            "asset": "TOKEN_A",
            "oppositeAsset": "TOKEN_B",
            "other": 1,
        }
    ]

    def fake_list_positions(
        self,
        wallet_address=None,
        platform=None,
        platform_id=None,
    ):
        assert platform == "telegram"
        assert platform_id == "99"
        return sample

    monkeypatch.setattr(client_module.PolymarketClient, "list_positions", fake_list_positions, raising=False)

    tools = build_polymarket_tools(
        client,
        default_platform="telegram",
        default_platform_id="99",
    )

    positions_tool = next(t for t in tools if t.name == "list_polymarket_positions")
    output = positions_tool.func()

    assert output == sample
