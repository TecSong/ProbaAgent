from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import logging
import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OpenOrderParams, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL


LOGGER = logging.getLogger(__name__)
_LOGGER_CONFIGURED = False


def _ensure_logger():
    global _LOGGER_CONFIGURED
    if _LOGGER_CONFIGURED:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    LOGGER.addHandler(handler)
    LOGGER.propagate = False
    _LOGGER_CONFIGURED = True


class PolymarketClientError(RuntimeError):
    """Raised when the Polymarket API returns an error."""


@dataclass
class PolymarketClientConfig:
    host: str
    private_key: str
    chain_id: int = 137
    signature_type: int = 0
    funder: Optional[str] = None
    gamma_base: str = "https://gamma-api.polymarket.com"
    timeout: int = 15
    debug: bool = False


class PolymarketClient:
    """
    Thin wrapper around py-clob-client's ClobClient.

    The implementation follows https://github.com/polymarket/py-clob-client and
    focuses on order management helpers used by the LangChain agent.
    """

    def __init__(self, config: PolymarketClientConfig) -> None:
        self.config = config
        self._client = ClobClient(
            config.host,
            key=config.private_key,
            chain_id=config.chain_id,
            funder=config.funder,
            signature_type=1
        )
        # Create API creds if needed (per py-clob-client README).
        self._client.set_api_creds(self._client.create_or_derive_api_creds())
        self._gamma = requests.Session()
        self._gamma.headers.update({"Accept": "application/json"})
        self._clob_http = requests.Session()
        self._clob_http.headers.update({"Accept": "application/json"})
        self._timeout = config.timeout
        self._debug = config.debug
        if self._debug:
            _ensure_logger()
            LOGGER.setLevel(logging.DEBUG)

    # Public API -----------------------------------------------------------------

    def list_orders(self, market_id: Optional[str] = None) -> List[Dict[str, Any]]:
        params = OpenOrderParams()
        if market_id:
            params.market = market_id
        return self._client.get_orders(params)

    def list_markets(
        self,
        tag_id: Optional[str] = None,
        closed: bool = False,
        limit: int = 25,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Fetch markets via the Gamma endpoint documented at
        https://docs.polymarket.com/developers/gamma-markets-api/fetch-markets-guide.
        """

        params: Dict[str, Any] = {
            "closed": str(closed).lower(),
            "limit": limit,
            "offset": offset,
        }
        if tag_id:
            params["tag_id"] = tag_id

        if self._debug:
            LOGGER.debug("Fetching markets with params: %s", params)
        return self._gamma_request("GET", "/markets", params=params)

    def get_market_detail(self, market_id: str) -> Dict[str, Any]:
        """
        Fetch full metadata for a market ID per
        https://docs.polymarket.com/api-reference/markets/get-market-by-id.
        """

        if self._debug:
            LOGGER.debug("Fetching market detail for %s", market_id)
        return self._gamma_request("GET", f"/markets/{market_id}")

    def get_market_price(self, token_id: str, side: str) -> Dict[str, Any]:
        """
        Fetch executable price using https://docs.polymarket.com/api-reference/pricing/get-market-price.
        """

        normalized = side.strip().upper()
        if normalized not in {"BUY", "SELL"}:
            raise PolymarketClientError("side must be BUY or SELL")

        return self._clob_request(
            "GET",
            "/price",
            params={"token_id": token_id, "side": normalized},
        )

    def create_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float
    ) -> Dict[str, Any]:
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=size,
            side=self._coerce_side(side)
        )
        if self._debug:
            LOGGER.debug(
                "Creating order token_id=%s side=%s size=%s price=%s order_type=%s exp=%s",
                token_id,
                side,
                size,
                price
            )

        signed_order = self._client.create_order(order_args)
        print("signed_order", signed_order)
        try:
            response = self._client.post_order(signed_order)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            raise PolymarketClientError(
                f"Order placement failed: {msg or 'Unknown error'}. Please check your parameters and try again."
            ) from exc

        if self._debug:
            LOGGER.debug("Order response: %s", response)

        if isinstance(response, dict):
            error_msg = (
                response.get("error")
                or response.get("message")
                or response.get("detail")
            )
            status = str(response.get("status", "")).lower()
            if error_msg or status in {"failed", "error", "rejected"}:
                raise PolymarketClientError(
                    f"Order placement failed: {error_msg or response.get('status')}. Please check your parameters and try again."
                )
        return response

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self._client.cancel(order_id)

    # Internal helpers ------------------------------------------------------------

    @staticmethod
    def _coerce_side(side: str):
        normalized = side.strip().lower()
        if normalized in {"buy", "long", "yes"}:
            return BUY
        if normalized in {"sell", "short", "no"}:
            return SELL
        raise PolymarketClientError(f"Unsupported side '{side}'. Use buy/sell.")

    @staticmethod
    def _coerce_order_type(order_type: str) -> OrderType:
        normalized = order_type.strip().upper()
        mapping = {
            "GTC": OrderType.GTC,
            "FOK": OrderType.FOK,
            "IOC": OrderType.IOC,
        }
        try:
            return mapping[normalized]
        except KeyError as exc:  # pragma: no cover - thin guard
            raise PolymarketClientError(
                f"Unsupported order_type '{order_type}'. Options: {', '.join(mapping)}."
            ) from exc

    def _gamma_request(
        self, method: str, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        url = f"{self.config.gamma_base.rstrip('/')}{path}"
        response = self._gamma.request(method, url, params=params, timeout=self._timeout)
        if not response.ok:
            raise PolymarketClientError(
                f"Gamma API error ({response.status_code}): {response.text}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise PolymarketClientError("Malformed Gamma API response") from exc

    def _clob_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.config.host.rstrip('/')}{path}"
        response = self._clob_http.request(
            method, url, params=params, json=json, timeout=self._timeout
        )
        if not response.ok:
            raise PolymarketClientError(
                f"CLOB REST error ({response.status_code}): {response.text}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise PolymarketClientError("Malformed CLOB API response") from exc
