from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from polymarket_agent.client import PolymarketClientError

LOGGER = logging.getLogger(__name__)


class NoRelevantMarketError(RuntimeError):
    """Raised when no relevant markets are found for a query."""


def format_usd(value: Any) -> str | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None

    abs_num = abs(num)
    if abs_num >= 1_000_000_000:
        rendered = f"${num / 1_000_000_000:.1f}B"
    elif abs_num >= 1_000_000:
        rendered = f"${num / 1_000_000:.1f}M"
    elif abs_num >= 1_000:
        rendered = f"${num / 1_000:.1f}K"
    else:
        rendered = f"${num:.2f}" if abs_num < 1 else f"${num:,.0f}"

    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def collect_market_snapshot(client: Any, query: str) -> str | None:
    cleaned = query.strip()
    if not cleaned:
        return None

    seen_ids: set[str] = set()
    candidates: List[Dict[str, Any]] = []

    query_tokens = [
        token
        for token in re.split(r"[^0-9a-zA-Z]+", cleaned.lower())
        if token and (len(token) >= 3 or token.isdigit())
    ]
    synonym_map: Dict[str, tuple[str, ...]] = {
        "btc": ("bitcoin",),
        "eth": ("ethereum",),
        "gop": ("republican",),
        "dem": ("democrat", "democratic"),
    }

    def _token_matches(token: str, text: str) -> bool:
        if token in text:
            return True
        for synonym in synonym_map.get(token, ()):
            if synonym in text:
                return True
        return False

    def _matches_query_text(text: str) -> bool:
        if not query_tokens:
            return bool(str(text).strip())
        lowered = str(text).lower()
        if not lowered:
            return False
        return all(_token_matches(token, lowered) for token in query_tokens)

    def _event_summary(entry: Dict[str, Any]) -> str:
        fields: List[str] = []
        for key in ("title", "name", "question", "slug", "ticker", "description"):
            value = entry.get(key)
            if isinstance(value, (str, int, float)):
                fields.append(str(value))
        return " ".join(fields)

    def _market_summary(entry: Dict[str, Any]) -> str:
        fields: List[str] = []
        for key in ("question", "title", "name", "ticker", "slug", "description"):
            value = entry.get(key)
            if isinstance(value, (str, int, float)):
                fields.append(str(value))
        event_hint = entry.get("event_title") or entry.get("event")
        if isinstance(event_hint, (str, int, float)):
            fields.append(str(event_hint))
        return " ".join(fields)

    def _normalize_market_id(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            numeric = int(value)
            return str(numeric)
        text = str(value).strip()
        if not text:
            return None
        if text.lower().startswith("0x"):
            return None
        if not text.isdigit():
            return None
        return text

    direct_id = _normalize_market_id(cleaned) if cleaned.isdigit() else None
    if direct_id:
        seen_ids.add(direct_id)
        candidates.append({"market_id": direct_id, "context": {"type": "input"}})

    try:
        search_payload = client.search_markets_events_profiles(query=cleaned)
    except PolymarketClientError as exc:
        LOGGER.warning("Polymarket search failed for '%s': %s", cleaned, exc)
        search_payload = None
    except Exception:  # noqa: BLE001
        LOGGER.exception("Unexpected error during Polymarket search for '%s'", cleaned)
        search_payload = None

    def _extract_market_id(entry: Any) -> str | None:
        if not isinstance(entry, dict):
            return None
        for key in ("market_id", "marketId", "id"):
            candidate = entry.get(key)
            normalized = _normalize_market_id(candidate)
            if normalized:
                return normalized
        market = entry.get("market")
        if isinstance(market, dict):
            return _extract_market_id(market)
        return None

    def _extend_markets_from_events(entry: Any, target: List[Any]) -> None:
        if not isinstance(entry, dict):
            return
        markets = entry.get("markets")
        if not isinstance(markets, list) or not markets:
            return
        if not _matches_query_text(_event_summary(entry)):
            return
        event_title = (
            entry.get("title")
            or entry.get("name")
            or entry.get("question")
            or entry.get("slug")
            or entry.get("ticker")
        )
        for market in markets:
            if isinstance(market, dict) and event_title:
                enriched_market = dict(market)
                enriched_market.setdefault("event_title", event_title)
                target.append(enriched_market)
            else:
                target.append(market)

    if isinstance(search_payload, dict):
        markets_section: List[Any] = []
        for key in ("markets", "marketResults"):
            value = search_payload.get(key)
            if isinstance(value, list):
                markets_section.extend(value)
        results = search_payload.get("results")
        if isinstance(results, list):
            for entry in results:
                if not isinstance(entry, dict):
                    continue
                entry_type = entry.get("type")
                if entry_type == "market":
                    market_entry = entry.get("market") if isinstance(entry.get("market"), dict) else entry
                    markets_section.append(market_entry)
                elif entry_type == "event":
                    event_entry = entry.get("event") if isinstance(entry.get("event"), dict) else entry
                    _extend_markets_from_events(event_entry, markets_section)
        for key in ("events", "eventResults"):
            events_section = search_payload.get(key)
            if isinstance(events_section, list):
                for event_entry in events_section:
                    _extend_markets_from_events(event_entry, markets_section)

        for entry in markets_section:
            if isinstance(entry, dict) and not _matches_query_text(_market_summary(entry)):
                continue
            market_id = _extract_market_id(entry)
            if not market_id or market_id in seen_ids:
                continue
            seen_ids.add(market_id)
            candidates.append({"market_id": market_id, "context": entry})

    if not candidates and search_payload is not None:
        raise NoRelevantMarketError("No relevant markets matched the query.")

    selected_detail: Dict[str, Any] | None = None
    selected_candidate: Dict[str, Any] | None = None

    for candidate in candidates:
        market_id = candidate.get("market_id")
        if not market_id:
            continue
        try:
            detail = client.get_market_detail(str(market_id))
        except PolymarketClientError as exc:
            LOGGER.warning("Market detail lookup failed for %s: %s", market_id, exc)
            continue
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unexpected error during market detail lookup for %s", market_id)
            continue

        if isinstance(detail, dict) and detail:
            selected_detail = detail
            selected_candidate = candidate
            break

    if not selected_detail or not selected_candidate:
        return None

    def _safe_to_float(value: Any) -> float | None:
        if value in (None, "", "-", "NaN"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _format_percent(value: float | None) -> str | None:
        if value is None:
            return None
        if not 0 <= value <= 1:
            return None
        return f"{value * 100:.1f}%"

    def _extract_price_value(payload: Any) -> float | None:
        if payload is None:
            return None
        if isinstance(payload, (int, float)):
            return float(payload)
        if isinstance(payload, str):
            return _safe_to_float(payload)
        if isinstance(payload, dict):
            for key in ("price", "bestPrice", "value"):
                candidate = payload.get(key)
                price = _safe_to_float(candidate)
                if price is not None:
                    return price
            for key in ("data", "result"):
                nested = payload.get(key)
                nested_price = _extract_price_value(nested)
                if nested_price is not None:
                    return nested_price
        return None

    market_section = selected_detail.get("market")
    market_dict = market_section if isinstance(market_section, dict) else {}

    title = (
        selected_detail.get("question")
        or selected_detail.get("title")
        or market_dict.get("question")
        or market_dict.get("title")
    )

    status = (
        selected_detail.get("status")
        or market_dict.get("status")
        or market_dict.get("state")
    )

    close_time = (
        selected_detail.get("end_date")
        or selected_detail.get("closes_at")
        or market_dict.get("end_date")
        or market_dict.get("closeDate")
    )

    volume_24h = (
        selected_detail.get("volume_24h")
        or selected_detail.get("volume24h")
        or selected_detail.get("volume_24hr")
        or market_dict.get("volume_24h")
        or market_dict.get("volume24h")
        or market_dict.get("volume_24hr")
    )

    liquidity = (
        selected_detail.get("liquidity")
        or selected_detail.get("liquidity_num")
        or market_dict.get("liquidity")
        or market_dict.get("liquidity_num")
    )

    token_snapshots: Dict[str, Dict[str, Any]] = {}

    def _register_token(token_id: Any, **kwargs: Any) -> None:
        if not token_id:
            return
        token_text = str(token_id).strip()
        if not token_text:
            return
        entry = token_snapshots.setdefault(token_text, {"token_id": token_text})
        for key, value in kwargs.items():
            if value is None:
                continue
            if key not in entry or entry[key] in (None, ""):
                entry[key] = value

    outcome_sources = [
        selected_detail.get("outcomes"),
        selected_detail.get("tokens"),
        selected_detail.get("outcomesDetailed"),
        market_dict.get("outcomes"),
        market_dict.get("tokens"),
        market_dict.get("outcomesDetailed"),
    ]

    for source in outcome_sources:
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            token_id = (
                item.get("token_id")
                or item.get("tokenId")
                or item.get("tokenID")
                or item.get("clob_token_id")
                or item.get("clobTokenId")
            )
            name = item.get("name") or item.get("title") or item.get("outcome") or item.get("ticker")
            if isinstance(item.get("outcome"), dict):
                outcome_dict = item["outcome"]
                token_id = token_id or outcome_dict.get("tokenId") or outcome_dict.get("token_id")
                name = name or outcome_dict.get("name") or outcome_dict.get("title")
            last_price = _safe_to_float(
                item.get("last_price")
                or item.get("lastPrice")
                or item.get("price")
                or item.get("recentPrice")
            )
            best_bid = _safe_to_float(
                item.get("best_bid")
                or item.get("bid_price")
                or item.get("bestBid")
                or item.get("bidPrice")
                or item.get("bid")
            )
            best_ask = _safe_to_float(
                item.get("best_ask")
                or item.get("ask_price")
                or item.get("bestAsk")
                or item.get("askPrice")
                or item.get("ask")
            )
            _register_token(
                token_id,
                label=name,
                last_price=last_price,
                best_bid=best_bid,
                best_ask=best_ask,
            )

    clob_candidates = (
        selected_detail.get("clob_token_ids")
        or selected_detail.get("clobTokenIds")
        or market_dict.get("clob_token_ids")
        or market_dict.get("clobTokenIds")
    )
    if isinstance(clob_candidates, (list, tuple)):
        for token_id in clob_candidates:
            _register_token(token_id)

    for key, label in (
        ("token_yes", "YES token"),
        ("token_no", "NO token"),
        ("tokenIdYes", "YES token"),
        ("tokenIdNo", "NO token"),
    ):
        _register_token(selected_detail.get(key), label=label)
        _register_token(market_dict.get(key), label=label)

    token_entries = list(token_snapshots.values())
    for token_entry in token_entries[:4]:
        token_id = token_entry.get("token_id")
        if not token_id:
            continue
        for side in ("BUY", "SELL"):
            try:
                price_payload = client.get_market_price(token_id, side)
            except PolymarketClientError as exc:
                LOGGER.debug(
                    "Price lookup failed for token %s side %s: %s",
                    token_id,
                    side,
                    exc,
                )
                continue
            except Exception:  # noqa: BLE001
                LOGGER.exception(
                    "Unexpected error during price lookup for %s side %s",
                    token_id,
                    side,
                )
                continue

            price_value = _extract_price_value(price_payload)
            if price_value is not None:
                token_entry[f"{side.lower()}_price"] = price_value

    for token_entry in token_entries:
        if ("buy_price" not in token_entry or token_entry.get("buy_price") is None) and isinstance(
            token_entry.get("best_ask"), (int, float)
        ):
            token_entry["buy_price"] = token_entry.get("best_ask")
        if ("sell_price" not in token_entry or token_entry.get("sell_price") is None) and isinstance(
            token_entry.get("best_bid"), (int, float)
        ):
            token_entry["sell_price"] = token_entry.get("best_bid")

    snapshot_lines: List[str] = []
    market_id = selected_candidate.get("market_id")
    if market_id:
        snapshot_lines.append(f"Market ID: {market_id}")
    if title:
        snapshot_lines.append(f"Title: {title}")

    if status or close_time:
        if close_time:
            snapshot_lines.append(f"Status: {status or 'unknown'}; Ends: {close_time}")
        else:
            snapshot_lines.append(f"Status: {status}")

    volume_float = _safe_to_float(volume_24h)
    if volume_float is not None:
        formatted_volume = format_usd(volume_float)
        if formatted_volume:
            snapshot_lines.append(f"24h Volume: {formatted_volume}")

    liquidity_float = _safe_to_float(liquidity)
    if liquidity_float is not None:
        formatted_liquidity = format_usd(liquidity_float)
        if formatted_liquidity:
            snapshot_lines.append(f"Liquidity: {formatted_liquidity}")

    context_entry = selected_candidate.get("context")
    if isinstance(context_entry, dict):
        event_title = context_entry.get("event_title") or context_entry.get("event")
        if event_title:
            snapshot_lines.append(f"Event: {event_title}")

    token_lines: List[str] = []
    for token_entry in token_entries[:4]:
        token_id = token_entry.get("token_id")
        label = token_entry.get("label") or "Outcome"
        last_price = token_entry.get("last_price")
        buy_price = token_entry.get("buy_price")
        sell_price = token_entry.get("sell_price")

        components: List[str] = []
        if isinstance(last_price, (int, float)):
            percent = _format_percent(last_price)
            components.append(f"last {last_price:.3f} ({percent})" if percent else f"last {last_price:.3f}")
        if isinstance(buy_price, (int, float)):
            percent = _format_percent(buy_price)
            components.append(f"buy {buy_price:.3f} ({percent})" if percent else f"buy {buy_price:.3f}")
        if isinstance(sell_price, (int, float)):
            percent = _format_percent(sell_price)
            components.append(f"sell {sell_price:.3f} ({percent})" if percent else f"sell {sell_price:.3f}")

        if components:
            display_id = token_id if not token_id or len(token_id) <= 12 else f"{token_id[:6]}…{token_id[-4:]}"
            token_lines.append(f"- {label}: {', '.join(components)} [token {display_id}]")

    if token_lines:
        snapshot_lines.append("Outcome Quotes:")
        snapshot_lines.extend(token_lines)

    if not snapshot_lines:
        return None

    return "\n".join(snapshot_lines)


__all__ = ["collect_market_snapshot", "format_usd", "NoRelevantMarketError"]
