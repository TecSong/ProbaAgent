from __future__ import annotations

import pytest
import sys
import types
from typing import Any

if "web3" not in sys.modules:
    web3_module = types.ModuleType("web3")

    class _StubWeb3:
        def __init__(self, *args, **kwargs):  # noqa: D401 - placeholder
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

    class _StubContract:  # noqa: D401 - placeholder
        pass

    contract_module.Contract = _StubContract

    sys.modules["web3"] = web3_module
    sys.modules["web3.middleware"] = middleware_module
    sys.modules["web3.contract"] = contract_module

if "supabase" not in sys.modules:
    supabase_module = types.ModuleType("supabase")

    class _StubSupabaseClient:  # noqa: D401 - placeholder
        pass

    def _stub_create_client(*args, **kwargs):  # noqa: D401 - placeholder
        raise RuntimeError("Supabase client is not available in tests.")

    supabase_module.Client = _StubSupabaseClient
    supabase_module.create_client = _stub_create_client
    sys.modules["supabase"] = supabase_module

from polymarket_agent import client as client_module
from polymarket_agent.client import PolymarketClient, PolymarketClientError
from polymarket_agent.main import build_client_from_env

from dotenv import load_dotenv

load_dotenv()


class _DummyClobClient:
    def __init__(self, *args, **kwargs):  # noqa: D401, ANN001 - test double
        pass

    def set_api_creds(self, creds):  # noqa: D401, ANN001 - test double
        self._creds = creds

    def create_or_derive_api_creds(self):  # noqa: D401
        return {}


def _build_client() -> PolymarketClient:
    return build_client_from_env()


@pytest.fixture(autouse=True)
def _stub_clob_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "ClobClient", _DummyClobClient)


def test_search_invokes_gamma_with_clean_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_gamma_request(self, method: str, path: str, params: dict | None = None):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return {"markets": [], "events": []}

    monkeypatch.setattr(
        client_module.PolymarketClient,
        "_gamma_request",
        fake_gamma_request,
    )

    client = _build_client()

    result = client.search_markets_events_profiles(
        "  Trump  ",
        cache=False,
    )

    assert result == {"markets": [], "events": []}
    assert captured["method"] == "GET"
    assert captured["path"] == "/public-search"
    assert captured["params"] == {
        "q": "Trump",
        "cache": "false",
    }


def test_search_rejects_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client()

    with pytest.raises(PolymarketClientError):
        client.search_markets_events_profiles("   ")


def test_list_trending_events_invokes_events_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_gamma_request(self, method: str, path: str, params: dict | None = None):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return [{"id": "1"}]

    monkeypatch.setattr(
        client_module.PolymarketClient,
        "_gamma_request",
        fake_gamma_request,
    )

    client = _build_client()
    events = client.list_trending_events()

    assert events == [{"id": "1"}]
    assert captured["method"] == "GET"
    assert captured["path"] == "/events"
    assert captured["params"] == {
        "limit": 10,
        "order": "volume24hr",
        "ascending": "false",
        "closed": "false",
        "archived": "false",
        "active": "true",
    }


def test_list_trending_events_extracts_from_dict_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_gamma_request(self, method: str, path: str, params: dict | None = None):
        return {"events": [{"id": "42"}, "ignore"]}

    monkeypatch.setattr(
        client_module.PolymarketClient,
        "_gamma_request",
        fake_gamma_request,
    )

    client = _build_client()
    events = client.list_trending_events(limit=5)

    assert events == [{"id": "42"}]
