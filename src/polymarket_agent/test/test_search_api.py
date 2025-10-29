from __future__ import annotations

import pytest

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
