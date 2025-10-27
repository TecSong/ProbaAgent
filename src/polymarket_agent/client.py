from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

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
        limit: int = 25,
        offset: int = 0,
        order: Optional[str] = None,
        ascending: Optional[bool] = None,
        id: Optional[Sequence[int]] = None,
        slug: Optional[Sequence[str]] = None,
        clob_token_ids: Optional[Sequence[str]] = None,
        condition_ids: Optional[Sequence[str]] = None,
        market_maker_address: Optional[Sequence[str]] = None,
        liquidity_num_min: Optional[float] = None,
        liquidity_num_max: Optional[float] = None,
        volume_num_min: Optional[float] = None,
        volume_num_max: Optional[float] = None,
        start_date_min: Optional[str] = None,
        start_date_max: Optional[str] = None,
        end_date_min: Optional[str] = None,
        end_date_max: Optional[str] = None,
        tag_id: Optional[int | str] = None,
        related_tags: Optional[bool] = None,
        cyom: Optional[bool] = None,
        uma_resolution_status: Optional[str] = None,
        game_id: Optional[str] = None,
        sports_market_types: Optional[Sequence[str]] = None,
        rewards_min_size: Optional[float] = None,
        question_ids: Optional[Sequence[str]] = None,
        include_tag: Optional[bool] = None,
        closed: Optional[bool] = False,
    ) -> Dict[str, Any]:
        """Fetch markets via Gamma `/markets` using the documented query parameters.

        Every argument maps 1:1 to
        https://docs.polymarket.com/api-reference/markets/list-markets :

        limit:
            Page size (integer >= 0, Gamma caps at 100). Defaults to 25.
        offset:
            Pagination offset (0-based).
        order:
            Field to sort by (e.g. `start_date`, `volume`).
        ascending:
            Boolean flag indicating sort direction (True for ascending).
        id:
            Sequence of numeric market identifiers to include.
        slug:
            Sequence of market slugs to include.
        clob_token_ids:
            Sequence of outcome token ids (CLOB token ids) to filter by.
        condition_ids:
            Sequence of condition ids associated with the markets.
        market_maker_address:
            Sequence of market maker addresses to filter by.
        liquidity_num_min / liquidity_num_max:
            Numeric bounds applied to market liquidity.
        volume_num_min / volume_num_max:
            Numeric bounds applied to traded volume.
        start_date_min / start_date_max:
            ISO-8601 strings bounding market start dates.
        end_date_min / end_date_max:
            ISO-8601 strings bounding market end dates.
        tag_id:
            Tag/category identifier (integer per Gamma docs).
        related_tags:
            When true, include markets from related tags.
        cyom:
            Filter for Create-Your-Own-Market entries.
        uma_resolution_status:
            UMA resolution status string filter.
        game_id:
            Sports game identifier.
        sports_market_types:
            Sequence describing sports market types (per docs).
        rewards_min_size:
            Minimum rewards size filter.
        question_ids:
            Sequence of Polymarket question ids.
        include_tag:
            Include tag metadata in the response when true.
        closed:
            Boolean flag to include closed markets; false for the API default.
        """

        params: Dict[str, Any] = {"limit": limit, "offset": offset}

        def _add_param(key: str, value: Any) -> None:
            if value is None:
                return
            if isinstance(value, bool):
                params[key] = str(value).lower()
                return
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                items = [str(item) for item in value if item is not None and str(item) != ""]
                if items:
                    params[key] = ",".join(items)
                return
            params[key] = value

        _add_param("order", order)
        _add_param("ascending", ascending)
        _add_param("id", id)
        _add_param("slug", slug)
        _add_param("clob_token_ids", clob_token_ids)
        _add_param("condition_ids", condition_ids)
        _add_param("market_maker_address", market_maker_address)
        _add_param("liquidity_num_min", liquidity_num_min)
        _add_param("liquidity_num_max", liquidity_num_max)
        _add_param("volume_num_min", volume_num_min)
        _add_param("volume_num_max", volume_num_max)
        _add_param("start_date_min", start_date_min)
        _add_param("start_date_max", start_date_max)
        _add_param("end_date_min", end_date_min)
        _add_param("end_date_max", end_date_max)
        _add_param("tag_id", tag_id)
        _add_param("related_tags", related_tags)
        _add_param("cyom", cyom)
        _add_param("uma_resolution_status", uma_resolution_status)
        _add_param("game_id", game_id)
        _add_param("sports_market_types", sports_market_types)
        _add_param("rewards_min_size", rewards_min_size)
        _add_param("question_ids", question_ids)
        _add_param("include_tag", include_tag)
        _add_param("closed", closed)

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
