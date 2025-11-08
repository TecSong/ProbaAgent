from __future__ import annotations

import json
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
        scaled = num / 1_000_000_000
        value_text = f"{scaled:.1f}".rstrip("0").rstrip(".")
        rendered = f"${value_text}B"
    elif abs_num >= 1_000_000:
        scaled = num / 1_000_000
        value_text = f"{scaled:.1f}".rstrip("0").rstrip(".")
        rendered = f"${value_text}M"
    elif abs_num >= 1_000:
        scaled = num / 1_000
        value_text = f"{scaled:.1f}".rstrip("0").rstrip(".")
        rendered = f"${value_text}K"
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
    primary_candidates: List[Dict[str, Any]] = []
    fallback_candidates: List[Dict[str, Any]] = []

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

    def _collapse_fragment(text: str) -> str:
        return re.sub(r"[^0-9a-z]+", "", text)

    def _parse_numeric_token(token: str) -> float | None:
        normalized = token.strip().lower()
        if not normalized:
            return None
        normalized = normalized.lstrip("$").replace(",", "")
        match = re.fullmatch(r"(\d+(?:\.\d+)?)([kmb]?)", normalized)
        if not match:
            return None
        base = float(match.group(1))
        suffix = match.group(2)
        multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(suffix, 1)
        return base * multiplier

    def _numeric_variants(value: float) -> set[str]:
        variants: set[str] = set()
        if value is None:
            return variants
        if float(value).is_integer():
            integral = int(round(value))
            variants.add(str(integral))
            variants.add(f"{integral:,}")
        else:
            text = f"{value:.4f}".rstrip("0").rstrip(".")
            variants.add(text)
        for suffix, divisor in (("k", 1_000), ("m", 1_000_000), ("b", 1_000_000_000)):
            scaled = value / divisor
            if scaled < 1:
                continue
            if float(scaled).is_integer():
                scaled_text = str(int(round(scaled)))
            else:
                scaled_text = f"{scaled:.3f}".rstrip("0").rstrip(".")
            variants.add(f"{scaled_text}{suffix}")
        return {variant for variant in variants if variant}

    def _token_matches(token: str, lowered_text: str, collapsed_text: str) -> bool:
        if not token:
            return False
        textual_variants = [token]
        textual_variants.extend(synonym_map.get(token, ()))
        for variant in textual_variants:
            lowered_variant = variant.lower()
            collapsed_variant = _collapse_fragment(lowered_variant)
            if lowered_variant and lowered_variant in lowered_text:
                return True
            if collapsed_variant and collapsed_variant in collapsed_text:
                return True
        numeric_value = _parse_numeric_token(token)
        if numeric_value is None:
            return False
        for rendering in _numeric_variants(numeric_value):
            lowered_rendering = rendering.lower()
            collapsed_rendering = _collapse_fragment(lowered_rendering)
            if lowered_rendering and lowered_rendering in lowered_text:
                return True
            if collapsed_rendering and collapsed_rendering in collapsed_text:
                return True
        return False

    def _match_score(text: Any) -> int:
        if not query_tokens:
            return 0
        lowered = str(text or "").lower()
        if not lowered:
            return 0
        collapsed = _collapse_fragment(lowered)
        matches = 0
        for token in query_tokens:
            if _token_matches(token, lowered, collapsed):
                matches += 1
        return matches

    def _event_summary(entry: Dict[str, Any]) -> str:
        fields: List[str] = []
        for key in ("title", "name", "question", "slug", "ticker", "description"):
            value = entry.get(key)
            if isinstance(value, (str, int, float)):
                fields.append(str(value))
        return " ".join(fields)

    def _market_summary(entry: Dict[str, Any]) -> str:
        fields: List[str] = []
        for key in (
            "question",
            "title",
            "name",
            "ticker",
            "slug",
            "description",
            "groupItemTitle",
            "groupItemThreshold",
        ):
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
        primary_candidates.append(
            {
                "market_id": direct_id,
                "context": {"type": "input"},
                "match_score": len(query_tokens) if query_tokens else 1,
            }
        )

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
        event_title = (
            entry.get("title")
            or entry.get("name")
            or entry.get("question")
            or entry.get("slug")
            or entry.get("ticker")
        )
        event_meta_fields = (
            (("startDate", "start_date", "startDateIso"), "event_start_date"),
            (("endDate", "end_date", "closeDate", "endDateIso"), "event_end_date"),
            (("volume", "volumeNum", "volume_num"), "event_volume"),
            (("liquidity", "liquidity_num", "liquidityNum"), "event_liquidity"),
            (("closed", "isClosed"), "event_closed"),
        )
        for market in markets:
            if isinstance(market, dict) and event_title:
                enriched_market = dict(market)
                enriched_market.setdefault("event_title", event_title)
                for source_keys, target_key in event_meta_fields:
                    if target_key in enriched_market:
                        continue
                    for source_key in source_keys:
                        value = entry.get(source_key)
                        if value not in (None, "", "-", "NaN"):
                            enriched_market[target_key] = value
                            break
                target.append(enriched_market)
            else:
                target.append(market)

    required_full_score = len(query_tokens) if query_tokens else 1

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
            if not isinstance(entry, dict):
                continue
            summary_text = _market_summary(entry)
            if query_tokens:
                score = _match_score(summary_text)
                if score == 0:
                    continue
            else:
                if not str(summary_text).strip():
                    continue
                score = required_full_score
            market_id = _extract_market_id(entry)
            if not market_id or market_id in seen_ids:
                continue
            candidate = {"market_id": market_id, "context": entry, "match_score": score}
            seen_ids.add(market_id)
            if not query_tokens or score >= required_full_score:
                primary_candidates.append(candidate)
            else:
                fallback_candidates.append(candidate)

    candidate_queue: List[Dict[str, Any]] = primary_candidates or fallback_candidates
    if not candidate_queue and search_payload is not None:
        raise NoRelevantMarketError("No relevant markets matched the query.")
    ordered_candidates = [
        entry
        for _, entry in sorted(
            enumerate(candidate_queue),
            key=lambda item: (-item[1].get("match_score", 0), item[0]),
        )
    ]

    selected_detail: Dict[str, Any] | None = None
    selected_candidate: Dict[str, Any] | None = None

    for candidate in ordered_candidates:
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

    context_entry = selected_candidate.get("context") if isinstance(selected_candidate.get("context"), dict) else {}
    context_event = context_entry.get("event") if isinstance(context_entry.get("event"), dict) else None
    detail_event = selected_detail.get("event") if isinstance(selected_detail.get("event"), dict) else None

    value_sources = [selected_detail, market_dict]
    for candidate in (detail_event, context_entry, context_event):
        if isinstance(candidate, dict):
            value_sources.append(candidate)

    def _extract_value(*names: str) -> Any:
        for source in value_sources:
            if not isinstance(source, dict):
                continue
            for name in names:
                if name not in source:
                    continue
                value = source.get(name)
                if value in (None, "", "-", "NaN"):
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                return value
        return None

    def _extract_text(*names: str) -> str | None:
        value = _extract_value(*names)
        if isinstance(value, (str, int, float)):
            text = str(value).strip()
            return text or None
        return None

    title = _extract_text("question", "title", "name", "slug", "ticker")
    status = _extract_text("status", "state")
    start_time = _extract_text("start_date", "startDate", "startDateIso", "event_start_date")
    end_time = _extract_text(
        "end_date",
        "endDate",
        "closes_at",
        "closeDate",
        "endDateIso",
        "event_end_date",
    )
    volume_total = _extract_value(
        "volume",
        "volume_num",
        "volumeNum",
        "volume_number",
        "volumeClob",
        "volume_clob",
        "event_volume",
    )
    volume_24h = _extract_value(
        "volume_24h",
        "volume24h",
        "volume_24hr",
        "volume24hr",
        "volume24",
        "volume24hrClob",
        "volume_24hr_clob",
    )
    liquidity = _extract_value("liquidity", "liquidity_num", "liquidityNum", "liquidityClob", "event_liquidity")
    closed_flag_value = _extract_value("closed", "isClosed", "event_closed")
    event_title = _extract_text("event_title", "eventTitle", "event_name", "event")

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

    def _normalize_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        return None

    def _render_datetime(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if "T" in text:
            date_part, time_part = text.split("T", 1)
            time_part = time_part.rstrip("Z")
            if time_part:
                hhmm = time_part[:5]
                if len(hhmm) == 5 and hhmm[2] == ":":
                    return f"{date_part} {hhmm}"
            return date_part
        return text

    def _parse_sequence(value: Any) -> List[Any] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if text.startswith("[") and text.endswith("]"):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    return parsed
            parts = [piece.strip() for piece in text.split(",") if piece.strip()]
            if parts:
                return parts
        return None

    start_text = _render_datetime(start_time) or "n/a"
    end_text = _render_datetime(end_time) or "n/a"
    closed_flag = _normalize_bool(closed_flag_value)

    volume_total_float = _safe_to_float(volume_total)
    volume_total_text = format_usd(volume_total_float) if volume_total_float is not None else None
    volume_24h_float = _safe_to_float(volume_24h)
    volume_24h_text = format_usd(volume_24h_float) if volume_24h_float is not None else None
    liquidity_float = _safe_to_float(liquidity)
    liquidity_text = format_usd(liquidity_float) if liquidity_float is not None else None

    def _token_priority(entry: Dict[str, Any]) -> tuple[int, str]:
        label = str(entry.get("label") or "").lower()
        if "yes" in label:
            return (0, label)
        if "no" in label:
            return (1, label)
        return (2, label)

    outcome_snippets: List[str] = []
    outcome_labels = _parse_sequence(_extract_value("outcomes", "outcomeLabels")) or []
    outcome_prices = _parse_sequence(_extract_value("outcomePrices", "outcomesPrices")) or []
    for label, price in zip(outcome_labels, outcome_prices):
        label_text = str(label).strip() or "Outcome"
        price_value = _safe_to_float(price)
        price_text = f"{price_value:.2f}" if price_value is not None else str(price).strip()
        if not price_text:
            continue
        outcome_snippets.append(f"{label_text} {price_text}")
        if len(outcome_snippets) >= 3:
            break

    if not outcome_snippets:
        ordered_tokens = sorted(token_entries, key=_token_priority)
        for token_entry in ordered_tokens:
            label = token_entry.get("label") or token_entry.get("name") or "Outcome"
            last_price = token_entry.get("last_price")
            buy_price = token_entry.get("buy_price")
            sell_price = token_entry.get("sell_price")

            price_text = None
            if isinstance(last_price, (int, float)):
                price_text = f"{last_price:.2f}"
            elif isinstance(buy_price, (int, float)) and isinstance(sell_price, (int, float)):
                price_text = f"buy {buy_price:.2f}/sell {sell_price:.2f}"
            elif isinstance(buy_price, (int, float)):
                price_text = f"buy {buy_price:.2f}"
            elif isinstance(sell_price, (int, float)):
                price_text = f"sell {sell_price:.2f}"

            if price_text:
                outcome_snippets.append(f"{label}: {price_text}")
            if len(outcome_snippets) >= 3:
                break

    snapshot_lines: List[str] = []
    market_id = selected_candidate.get("market_id")
    if market_id and title:
        snapshot_lines.append(f"Market {market_id}: {title}")
    elif title:
        snapshot_lines.append(f"Market: {title}")
    elif market_id:
        snapshot_lines.append(f"Market {market_id}")

    if event_title and (not title or event_title != title):
        snapshot_lines.append(f"Event: {event_title}")

    timing_parts = [f"Start: {start_text}", f"End: {end_text}"]
    if status:
        timing_parts.append(f"Status: {status}")
    if closed_flag is not None:
        timing_parts.append(f"Closed: {'Yes' if closed_flag else 'No'}")
    snapshot_lines.append("Timing: " + "; ".join(timing_parts))

    liquidity_display = liquidity_text or "n/a"
    if volume_total_text:
        volume_display = volume_total_text
        if volume_24h_text:
            volume_display += f" (24h {volume_24h_text})"
    elif volume_24h_text:
        volume_display = f"{volume_24h_text} (24h)"
    else:
        volume_display = "n/a"
    snapshot_lines.append(f"Liquidity: {liquidity_display}; Volume: {volume_display}")

    if outcome_snippets:
        snapshot_lines.append("Outcome prices: " + "; ".join(outcome_snippets[:3]))
    else:
        snapshot_lines.append("Outcome prices: n/a")

    return "\n".join(snapshot_lines)


__all__ = ["collect_market_snapshot", "format_usd", "NoRelevantMarketError"]
