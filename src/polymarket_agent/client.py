from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from typing import Any, Dict, List, Optional, Sequence, Tuple

import hashlib
import logging
import os
import requests
import threading
import time
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    AssetType,
    BalanceAllowanceParams,
    OpenOrderParams,
    OrderArgs,
    OrderType,
    PartialCreateOrderOptions,
)
from py_clob_client.order_builder.constants import BUY, SELL
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from .user.repository import SupabaseUserRepository, UserRepositoryError
from .constant import (
    MAX_APPROVAL_AMOUNT,
    POLYGON_RPC_URL,
    POLYMARKET_APPROVAL_SPENDERS,
    POLYMARKET_CTF_ADDRESS,
    POLYMARKET_USDC_ADDRESS,
    USDC_DECIMALS,
)
from .test.approve_abi import erc1155_set_approval, erc20_approve


LOGGER = logging.getLogger(__name__)
_LOGGER_CONFIGURED = False


def _load_client_cache_ttl() -> float:
    raw = os.getenv("POLYMARKET_CLIENT_CACHE_TTL")
    if not raw:
        return 900.0
    try:
        value = float(raw)
    except ValueError:
        LOGGER.warning(
            "Invalid POLYMARKET_CLIENT_CACHE_TTL value %r. Falling back to 900 seconds.",
            raw,
        )
        return 900.0
    if value <= 0:
        return 0.0
    return value


_CLIENT_CACHE_TTL_SECONDS = _load_client_cache_ttl()


@dataclass(slots=True)
class _ClobClientCacheEntry:
    client: ClobClient
    expires_at: float


_ClientCacheKey = Tuple[str, str, int, int, str]
_CLIENT_CACHE: Dict[_ClientCacheKey, _ClobClientCacheEntry] = {}
_CLIENT_CACHE_LOCK = threading.Lock()


def _normalize_host(host: str) -> str:
    return host.strip().rstrip("/").lower()


def _client_cache_key(config: PolymarketClientConfig) -> _ClientCacheKey:
    funder = (config.funder or "").strip().lower()
    identity = (config.cache_key or "").strip()
    if not identity:
        identity = f"pk:{hashlib.sha256(config.private_key.encode('utf-8')).hexdigest()}"
    signature_type = config.signature_type if config.signature_type is not None else 0
    return (
        _normalize_host(config.host),
        identity,
        config.chain_id,
        signature_type,
        funder,
    )


def _prune_expired_clients_locked(reference_time: float) -> None:
    expired = [
        cache_key
        for cache_key, entry in _CLIENT_CACHE.items()
        if entry.expires_at <= reference_time
    ]
    for cache_key in expired:
        _CLIENT_CACHE.pop(cache_key, None)


def _instantiate_clob_client(config: PolymarketClientConfig) -> ClobClient:
    kwargs: Dict[str, Any] = {
        "host": config.host,
        "key": config.private_key,
        "chain_id": config.chain_id,
        "signature_type": config.signature_type,
    }
    if config.funder:
        kwargs["funder"] = config.funder
    client = ClobClient(**kwargs)
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def _get_clob_client(config: PolymarketClientConfig) -> ClobClient:
    ttl = _CLIENT_CACHE_TTL_SECONDS
    if ttl <= 0:
        return _instantiate_clob_client(config)

    cache_key = _client_cache_key(config)
    now = time.monotonic()
    with _CLIENT_CACHE_LOCK:
        entry = _CLIENT_CACHE.get(cache_key)
        if entry and entry.expires_at > now:
            entry.expires_at = now + ttl
            return entry.client

    client = _instantiate_clob_client(config)
    updated_now = time.monotonic()
    new_expiry = updated_now + ttl

    with _CLIENT_CACHE_LOCK:
        entry = _CLIENT_CACHE.get(cache_key)
        if entry and entry.expires_at > updated_now:
            entry.expires_at = updated_now + ttl
            return entry.client
        _CLIENT_CACHE[cache_key] = _ClobClientCacheEntry(client=client, expires_at=new_expiry)
        _prune_expired_clients_locked(updated_now)
    return client


_USER_REPOSITORY: Optional[SupabaseUserRepository] = None
_USER_REPOSITORY_LOCK = threading.Lock()
_USER_PRIVATE_KEY_CACHE: Dict[Tuple[str, str], str] = {}
_USER_PRIVATE_KEY_CACHE_LOCK = threading.Lock()


def _get_user_repository() -> SupabaseUserRepository:
    global _USER_REPOSITORY
    repo = _USER_REPOSITORY
    if repo is not None:
        return repo
    with _USER_REPOSITORY_LOCK:
        repo = _USER_REPOSITORY
        if repo is not None:
            return repo
        _USER_REPOSITORY = SupabaseUserRepository.from_env()
        return _USER_REPOSITORY


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
    signature_type: int = 1
    funder: Optional[str] = None
    gamma_base: str = "https://gamma-api.polymarket.com"
    data_api_base: str = "https://data-api.polymarket.com"
    timeout: int = 15
    debug: bool = False
    cache_key: Optional[str] = None


@dataclass(frozen=True)
class BalanceAllowanceResult:
    balance: int
    allowances: Dict[str, int]


class PolymarketClient:
    """
    Thin wrapper around py-clob-client's ClobClient.

    The implementation follows https://github.com/polymarket/py-clob-client and
    focuses on order management helpers used by the LangChain agent.
    """

    def __init__(self, config: PolymarketClientConfig) -> None:
        self.config = config
        self._client = _get_clob_client(config)
        try:
            self._wallet_address = Web3.to_checksum_address(self._client.get_address())
        except Exception:  # noqa: BLE001 - fallback to derived address
            self._wallet_address = ""
        self._gamma = requests.Session()
        self._gamma.headers.update({"Accept": "application/json"})
        self._data_api = requests.Session()
        self._data_api.headers.update({"Accept": "application/json"})
        self._clob_http = requests.Session()
        self._clob_http.headers.update({"Accept": "application/json"})
        self._timeout = config.timeout
        self._debug = config.debug
        if self._debug:
            _ensure_logger()
            LOGGER.setLevel(logging.DEBUG)

    def _ensure_user_client(
        self, platform: Optional[str], platform_user_id: Optional[str]
    ) -> None:
        if platform is None and platform_user_id is None:
            return
        if platform is None or platform_user_id is None:
            raise PolymarketClientError(
                "platform and platform_id must both be provided when overriding credentials."
            )
        platform_str = str(platform)
        platform_user_str = str(platform_user_id)
        if not platform_str.strip() or not platform_user_str.strip():
            raise PolymarketClientError(
                "platform and platform_id must be non-empty strings."
            )
        private_key = self._resolve_user_private_key(platform_str, platform_user_str)
        desired_cache_key = (
            f"user:{platform_str.strip().lower()}:{platform_user_str.strip()}"
        )
        if (
            self.config.private_key == private_key
            and self.config.cache_key == desired_cache_key
        ):
            return
        self.config.private_key = private_key
        self.config.cache_key = desired_cache_key
        self._client = _get_clob_client(self.config)
        self._wallet_address = ""

    def _resolve_user_private_key(
        self, platform: str, platform_user_id: str
    ) -> str:
        platform_value = str(platform).strip()
        platform_user_value = str(platform_user_id).strip()
        if not platform_value or not platform_user_value:
            raise PolymarketClientError(
                "platform and platform_id must be non-empty strings."
            )
        cache_key = (platform_value.lower(), platform_user_value)
        with _USER_PRIVATE_KEY_CACHE_LOCK:
            cached = _USER_PRIVATE_KEY_CACHE.get(cache_key)
            if cached:
                return cached
        try:
            repository = _get_user_repository()
        except UserRepositoryError as exc:
            raise PolymarketClientError(
                f"Unable to initialize Supabase repository: {exc}"
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise PolymarketClientError(
                "Unexpected error while initializing Supabase repository."
            ) from exc
        try:
            record = repository.fetch_user(platform_value, platform_user_value)
        except UserRepositoryError as exc:
            raise PolymarketClientError(
                f"Failed to fetch user credentials for {platform_value}:{platform_user_value}: {exc}"
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise PolymarketClientError(
                f"Unexpected Supabase error while fetching {platform_value}:{platform_user_value}."
            ) from exc
        if not record:
            raise PolymarketClientError(
                f"User {platform_value}:{platform_user_value} not found in Supabase."
            )
        private_key = str(record.get("wallet_private_key") or "").strip()
        if not private_key:
            raise PolymarketClientError(
                f"User {platform_value}:{platform_user_value} is missing wallet_private_key."
            )
        with _USER_PRIVATE_KEY_CACHE_LOCK:
            _USER_PRIVATE_KEY_CACHE[cache_key] = private_key
        return private_key

    @property
    def wallet_address(self) -> str:
        if self._wallet_address:
            return self._wallet_address
        try:
            self._wallet_address = Web3.to_checksum_address(self._client.get_address())
        except Exception as exc:  # noqa: BLE001
            raise PolymarketClientError("Unable to determine wallet address.") from exc
        return self._wallet_address

    def _format_usdc(self, amount: int) -> str:
        scaled = Decimal(amount) / (Decimal(10) ** USDC_DECIMALS)
        text = f"{scaled:.6f}".rstrip("0").rstrip(".")
        return text or "0"

    def _calculate_required_collateral(
        self, normalized_side: str, size: float, price: float
    ) -> int:
        dec_size = Decimal(str(size))
        dec_price = Decimal(str(price))
        if dec_size <= 0:
            return 0
        if dec_price < 0 or dec_price > 1:
            raise PolymarketClientError("price must be between 0 and 1.")

        if normalized_side == BUY:
            required = dec_size * dec_price
        elif normalized_side == SELL:
            required = dec_size * (Decimal("1") - dec_price)
        else:  # pragma: no cover - guard for unexpected sides
            raise PolymarketClientError(f"Unsupported side '{normalized_side}'.")

        if required <= 0:
            return 0

        base_units = (required * (Decimal(10) ** USDC_DECIMALS)).quantize(
            Decimal("1"), rounding=ROUND_CEILING
        )
        return int(base_units)

    def _allowance_insufficient(
        self, allowances: Dict[str, int], required: int
    ) -> List[str]:
        missing: List[str] = []
        for spender in POLYMARKET_APPROVAL_SPENDERS:
            checksum = Web3.to_checksum_address(spender)
            allowance = allowances.get(checksum, 0)
            if allowance < required:
                missing.append(checksum)
        return missing

    def _ensure_balance_and_allowance(self, required_collateral: int) -> None:
        balance_info = self.check_balance_and_allowance(
            signature_type=self.config.signature_type
        )

        if balance_info.balance < required_collateral:
            needed = self._format_usdc(required_collateral)
            available = self._format_usdc(balance_info.balance)
            try:
                wallet_addr = self.wallet_address
            except PolymarketClientError:
                wallet_addr = "your trading wallet"
            raise PolymarketClientError(
                "Insufficient collateral to place the order. "
                f"Required ≈ {needed} USDC, available ≈ {available} USDC. "
                f"Please deposit USDC (token contract {POLYMARKET_USDC_ADDRESS}) to wallet {wallet_addr}."
            )

        missing_allowances = self._allowance_insufficient(
            balance_info.allowances, required_collateral or 1
        )
        if not missing_allowances:
            return

        if self._debug:
            LOGGER.debug(
                "Missing allowances detected for spenders: %s", missing_allowances
            )
        self.initialize_wallet_approvals()
        refreshed = self.check_balance_and_allowance(
            signature_type=self.config.signature_type
        )
        missing_after_refresh = self._allowance_insufficient(
            refreshed.allowances, required_collateral or 1
        )
        if missing_after_refresh:
            joined = ", ".join(missing_after_refresh)
            raise PolymarketClientError(
                f"Allowance initialization failed for spenders: {joined}. "
                "Please retry once the transactions confirm."
            )

    # Public API -----------------------------------------------------------------

    def list_orders(
        self,
        market_id: Optional[str] = None,
        platform: Optional[str] = None,
        platform_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_user_client(platform, platform_id)
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

    def search_markets_events_profiles(
        self,
        query: str,
        cache: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Search Polymarket markets, events, and profiles via the Gamma `/search` endpoint."""

        cleaned = query.strip()
        if not cleaned:
            raise PolymarketClientError("query must be a non-empty string")

        params: Dict[str, Any] = {"q": cleaned}

        if cache is not None:
            params["cache"] = "true" if cache else "false"

        if self._debug:
            LOGGER.debug("Gamma search params: %s", params)

        return self._gamma_request("GET", "/public-search", params=params)

    def list_trending_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the most active Polymarket events ordered by recent volume."""

        normalized_limit = max(1, min(int(limit or 1), 25))
        params: Dict[str, Any] = {
            "limit": normalized_limit,
            "order": "volume24hr",
            "ascending": "false",
            "closed": "false",
            "archived": "false",
            "active": "true",
        }

        payload = self._gamma_request("GET", "/events", params=params)

        events: Any
        if isinstance(payload, list):
            events = payload
        elif isinstance(payload, dict):
            events = payload.get("events") or payload.get("data") or payload.get("results")
        else:
            events = None

        if not isinstance(events, list):
            raise PolymarketClientError("Malformed events response from Gamma API.")

        return [event for event in events if isinstance(event, dict)]

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

    def list_positions(
        self,
        wallet_address: Optional[str] = None,
        platform: Optional[str] = None,
        platform_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch current Polymarket positions for a wallet via the public data API.
        """

        if wallet_address is None:
            self._ensure_user_client(platform, platform_id)
            wallet_address = self.wallet_address
        elif platform is not None or platform_id is not None:
            self._ensure_user_client(platform, platform_id)

        address = str(wallet_address or "").strip()
        if not address:
            raise PolymarketClientError("wallet_address must be a non-empty string.")

        payload = self._data_api_request("GET", "/positions", params={"user": address})
        if isinstance(payload, list):
            for position in payload:
                position["token_id"] = position.get("asset")
                position.pop("asset")
            return payload
        raise PolymarketClientError("Malformed positions response from Polymarket data API.")

    def create_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
        platform: Optional[str] = None,
        platform_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._ensure_user_client(platform, platform_id)
        normalized_side = self._coerce_side(side)
        required_collateral = self._calculate_required_collateral(
            normalized_side, size, price
        )
        if normalized_side == BUY:
            self._ensure_balance_and_allowance(required_collateral)

        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=size,
            side=normalized_side
        )
        if self._debug:
            LOGGER.debug(
                "Creating order token_id=%s side=%s size=%s price=%s order_type=%s exp=%s",
                token_id,
                side,
                size,
                price
            )
        options = PartialCreateOrderOptions(neg_risk=True)
        signed_order = self._client.create_order(order_args, options=options)
        LOGGER.debug("signed_order: %s", signed_order)
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

    def cancel_order(
        self,
        order_id: str,
        platform: Optional[str] = None,
        platform_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._ensure_user_client(platform, platform_id)
        return self._client.cancel(order_id)

    def check_balance_and_allowance(
        self,
        asset_type: AssetType = AssetType.COLLATERAL,
        token_id: Optional[str] = None,
        signature_type: int = -1,
    ) -> BalanceAllowanceResult:
        """
        Fetch wallet balances and allowances from the CLOB API.

        Mirrors the ad-hoc helper in ``test_update_balance_allowance`` while providing
        guardrails and a reusable interface for the agent runtime.
        """

        params_kwargs: Dict[str, Any] = {
            "asset_type": asset_type,
            "signature_type": signature_type,
        }

        if asset_type == AssetType.CONDITIONAL:
            if not token_id:
                raise PolymarketClientError(
                    "token_id is required when checking CONDITIONAL asset allowances."
                )
            params_kwargs["token_id"] = token_id
        elif token_id:
            raise PolymarketClientError(
                "token_id is only supported with AssetType.CONDITIONAL."
            )

        try:
            raw_response = self._client.get_balance_allowance(
                params=BalanceAllowanceParams(**params_kwargs)
            )
        except Exception as exc:  # noqa: BLE001
            raise PolymarketClientError(
                f"Failed to fetch balance/allowance for asset_type={asset_type}."
            ) from exc

        if not isinstance(raw_response, dict):
            raise PolymarketClientError("Unexpected balance/allowance payload type.")

        if self._debug:
            LOGGER.debug("Balance/allowance response: %s", raw_response)

        try:
            balance_value = int(raw_response["balance"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PolymarketClientError("Malformed balance value in response.") from exc

        raw_allowances = raw_response.get("allowances", {}) or {}
        if not isinstance(raw_allowances, dict):
            raise PolymarketClientError("Malformed allowances in response.")

        try:
            allowance_map = {
                Web3.to_checksum_address(address): int(amount)
                for address, amount in raw_allowances.items()
            }
        except ValueError as exc:  # includes invalid address or amount parsing
            raise PolymarketClientError("Malformed allowance entry in response.") from exc

        return BalanceAllowanceResult(balance=balance_value, allowances=allowance_map)

    def initialize_wallet_approvals(
        self,
        rpc_url: Optional[str] = None,
        spenders: Optional[Sequence[str]] = None,
        wait_timeout: int = 600,
    ) -> List[Any]:
        """
        Ensure the trading wallet has unlimited approvals for the core Polymarket
        exchange contracts the agent interacts with.

        Parameters
        ----------
        rpc_url:
            Optional override for the Polygon RPC endpoint. Defaults to
            ``POLYGON_RPC_URL`` when omitted.
        spenders:
            Custom iterable of spender addresses to approve. Falls back to
            ``POLYMARKET_APPROVAL_SPENDERS``.
        wait_timeout:
            Seconds to wait for each transaction receipt. Matches the behaviour
            from the integration test helper.
        """

        rpc_endpoint = (rpc_url or POLYGON_RPC_URL).strip()
        if not rpc_endpoint:
            raise PolymarketClientError("rpc_url must be a non-empty string")

        web3 = Web3(Web3.HTTPProvider(rpc_endpoint))
        web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        approvals = list(spenders or POLYMARKET_APPROVAL_SPENDERS)
        if not approvals:
            return []

        account = web3.eth.account.from_key(self.config.private_key)
        usdc_contract = web3.eth.contract(
            address=Web3.to_checksum_address(POLYMARKET_USDC_ADDRESS),
            abi=erc20_approve,
        )
        ctf_contract = web3.eth.contract(
            address=Web3.to_checksum_address(POLYMARKET_CTF_ADDRESS),
            abi=erc1155_set_approval,
        )

        nonce = web3.eth.get_transaction_count(account.address)
        receipts: List[Any] = []

        for spender in approvals:
            checksum_spender = Web3.to_checksum_address(spender)
            if self._debug:
                LOGGER.debug("Approving spender %s", checksum_spender)

            try:
                usdc_tx = usdc_contract.functions.approve(
                    checksum_spender, MAX_APPROVAL_AMOUNT
                ).build_transaction(
                    {
                        "chainId": self.config.chain_id,
                        "from": account.address,
                        "nonce": nonce,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - propagate with context
                raise PolymarketClientError(
                    f"Failed to build USDC approval transaction for {checksum_spender}"
                ) from exc

            signed_usdc = web3.eth.account.sign_transaction(
                usdc_tx, private_key=self.config.private_key
            )
            try:
                usdc_hash = web3.eth.send_raw_transaction(
                    signed_usdc.raw_transaction
                )
                receipts.append(
                    web3.eth.wait_for_transaction_receipt(usdc_hash, wait_timeout)
                )
            except Exception as exc:  # noqa: BLE001 - propagate with context
                raise PolymarketClientError(
                    f"Failed to submit USDC approval for {checksum_spender}"
                ) from exc
            nonce += 1

            try:
                ctf_tx = ctf_contract.functions.setApprovalForAll(
                    checksum_spender, True
                ).build_transaction(
                    {
                        "chainId": self.config.chain_id,
                        "from": account.address,
                        "nonce": nonce,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - propagate with context
                raise PolymarketClientError(
                    f"Failed to build CTF approval transaction for {checksum_spender}"
                ) from exc

            signed_ctf = web3.eth.account.sign_transaction(
                ctf_tx, private_key=self.config.private_key
            )
            try:
                ctf_hash = web3.eth.send_raw_transaction(
                    signed_ctf.raw_transaction
                )
                receipts.append(
                    web3.eth.wait_for_transaction_receipt(ctf_hash, wait_timeout)
                )
            except Exception as exc:  # noqa: BLE001 - propagate with context
                raise PolymarketClientError(
                    f"Failed to submit CTF approval for {checksum_spender}"
                ) from exc
            nonce += 1

        return receipts

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

    def _data_api_request(
        self, method: str, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        url = f"{self.config.data_api_base.rstrip('/')}{path}"
        response = self._data_api.request(method, url, params=params, timeout=self._timeout)
        if not response.ok:
            raise PolymarketClientError(
                f"Data API error ({response.status_code}): {response.text}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise PolymarketClientError("Malformed data API response") from exc
