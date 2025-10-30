"""Telegram bot bridge for the Polymarket LangChain agent."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI
try:
    from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
    from telegram.constants import ChatAction, ParseMode
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
except ModuleNotFoundError:
    if os.getenv("POLYMARKET_ALLOW_TELEGRAM_STUBS") != "1":
        raise

    from types import SimpleNamespace

    class _StubForceReply:
        def __init__(self, *args, **kwargs):
            pass

    class _StubInlineKeyboardButton:
        def __init__(self, *args, **kwargs):
            pass

    class _StubInlineKeyboardMarkup:
        def __init__(self, *args, **kwargs):
            pass

    class _StubMessage:
        pass

    class _StubUpdate:
        pass

    class _StubApplication:
        @classmethod
        def builder(cls):
            class _Builder:
                def token(self, *args, **kwargs):
                    return self

                def build(self):
                    return _StubApplication()

            return _Builder()

        def add_handler(self, *args, **kwargs):
            return None

        def run_polling(self):
            raise RuntimeError("Telegram functionality is not available in stub mode.")

    class _StubHandler:
        def __init__(self, *args, **kwargs):
            pass

    class _StubFiltersOperand:
        def __init__(self, name: str):
            self._name = name

        def __and__(self, other):
            return self

        def __rand__(self, other):
            return self

        def __invert__(self):
            return self

    class _StubContextTypes:
        DEFAULT_TYPE = object

    ForceReply = _StubForceReply
    InlineKeyboardButton = _StubInlineKeyboardButton
    InlineKeyboardMarkup = _StubInlineKeyboardMarkup
    Message = _StubMessage
    Update = _StubUpdate
    Application = _StubApplication
    CallbackQueryHandler = _StubHandler
    CommandHandler = _StubHandler
    MessageHandler = _StubHandler
    ContextTypes = _StubContextTypes
    filters = SimpleNamespace(
        TEXT=_StubFiltersOperand("TEXT"),
        COMMAND=_StubFiltersOperand("COMMAND"),
    )
    ChatAction = SimpleNamespace(TYPING="typing")
    ParseMode = SimpleNamespace(MARKDOWN="markdown")

from polymarket_agent.agent import build_polymarket_agent, run_agent_loop, update_history
from polymarket_agent.client import PolymarketClientError
from polymarket_agent.main import build_client_from_env

load_dotenv()

LOGGER = logging.getLogger(__name__)


_OPENAI_WEB_SEARCH_MODEL = os.getenv("OPENAI_WEB_SEARCH_MODEL", "gpt-4.1-mini")
_openai_client: OpenAI | None = None


def _parse_allowed_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    allowed: set[int] = set()
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            allowed.add(int(piece))
        except ValueError:
            LOGGER.warning("Skipping invalid TELEGRAM_ALLOWED_USER_IDS entry: %s", piece)
    return allowed


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


def _format_usd(value: Any) -> str | None:
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


def _collect_market_snapshot(client: Any, query: str) -> str | None:
    cleaned = query.strip()
    if not cleaned:
        return None

    seen_ids: set[str] = set()
    candidates: List[Dict[str, Any]] = []

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
        if isinstance(markets, list):
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
            market_id = _extract_market_id(entry)
            if not market_id or market_id in seen_ids:
                continue
            seen_ids.add(market_id)
            candidates.append({"market_id": market_id, "context": entry})

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
        formatted_volume = _format_usd(volume_float)
        if formatted_volume:
            snapshot_lines.append(f"24h Volume: {formatted_volume}")

    liquidity_float = _safe_to_float(liquidity)
    if liquidity_float is not None:
        formatted_liquidity = _format_usd(liquidity_float)
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


def _build_application() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN in environment.")

    allowed_ids = _parse_allowed_ids(os.getenv("TELEGRAM_ALLOWED_USER_IDS"))
    client = build_client_from_env()
    agent = build_polymarket_agent(client)
    histories: Dict[int, List[Dict[str, str]]] = {}
    search_sessions: Dict[int, Dict[str, Any]] = {}

    def _generate_market_insight(query: str, max_results: int = 6) -> str:
        system_prompt = (
            "You are an AI market analyst advising Polymarket traders. "
            f"Always begin by using the web_search tool to gather up to {max_results} recent high-signal sources about the user's request. "
            "When a Polymarket market snapshot is provided, parse it to extract status, end time, liquidity, 24h volume, and the latest YES/NO quotes "
            "(last, bid, ask). Use that data to anchor your analysis.\n"
            "After reviewing the sources (and snapshot if present), produce a Telegram-safe Markdown report in the following structure:\n\n"
            "### Market Insight\n"
            "<Two concise sentences summarizing the latest situation, what the market is pricing, and the key takeaway for traders.>\n\n"
            "### Implied Odds\n"
            "- YES: <probability as a percentage with one decimal place> (market last <yes_last%>%, <diff_vs_market>pp)\n"
            "- NO: <probability as a percentage with one decimal place> (market last <no_last%>%, <diff_vs_market>pp)\n"
            "If snapshot data is missing for an outcome, state \"market data unavailable\" for that side. Diff is model probability minus market last-price probability.\n\n"
            "### Snapshot Highlights\n"
            "- Status: <status>; Ends: <close time or \"unknown\">\n"
            "- YES last/bid/ask: <values> | NO last/bid/ask: <values>\n"
            "- 24h Volume: <value>; Liquidity: <value>\n"
            "Only include lines with data you can extract; omit this entire section if no snapshot is available.\n\n"
            "### Drivers\n"
            "- <Key catalyst or data point>\n"
            "- <Secondary driver>\n\n"
            "### Risks\n"
            "- <Material uncertainty or counter-scenario>\n\n"
            "### Sources\n"
            "- [Title](URL) – short justification\n"
            "If evidence is thin or conflicting, state the uncertainty explicitly. Avoid Markdown that would break in Telegram (such as raw underscores)."
        )

        user_prompt = (
            "Target market or event: {query}\n"
            "Estimate odds from the perspective of a Polymarket YES contract. Ensure YES and NO sum to 100%."
        ).format(query=query)

        snapshot_text = _collect_market_snapshot(client, query)
        if snapshot_text:
            user_prompt += "\n\nPolymarket internal data snapshot:\n" + snapshot_text

        try:
            response = _get_openai_client().responses.create(
                model=_OPENAI_WEB_SEARCH_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_prompt}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": user_prompt}],
                    },
                ],
                tools=[{"type": "web_search"}],
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OpenAI insight request failed: {exc}") from exc

        output_text = getattr(response, "output_text", None)
        if not output_text:
            chunks: List[str] = []
            try:
                for item in getattr(response, "output", []) or []:
                    for content in getattr(item, "content", []) or []:
                        text = getattr(content, "text", None)
                        if text:
                            chunks.append(text)
            except Exception:  # pragma: no cover - defensive fallback
                chunks = []
            if chunks:
                output_text = "".join(chunks)

        if not output_text:
            raise RuntimeError("OpenAI insight response was empty.")

        return output_text.strip()

    def _is_authorized(user_id: int | None) -> bool:
        if not allowed_ids:
            return True
        if user_id is None:
            return False
        return user_id in allowed_ids

    async def _reject(update: Update):
        if update.effective_message:
            await update.effective_message.reply_text("You are not authorized to use this bot.")

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
        user_id = update.effective_user.id if update.effective_user else None
        if not _is_authorized(user_id):
            await _reject(update)
            return
        msg = (
            "Hi! I'm the Polymarket trading assistant. "
            "Ask for trade actions in natural language, or use /insight <market or event> for fresh AI intel."
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
        user_id = update.effective_user.id if update.effective_user else None
        if not _is_authorized(user_id):
            await _reject(update)
            return
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id is not None:
            histories.pop(chat_id, None)
        await update.message.reply_text("Conversation history cleared.", parse_mode=ParseMode.MARKDOWN)

    def _sanitize(text: str) -> str:
        return (
            text.replace("[", "(")
            .replace("]", ")")
            .replace("_", " ")
            .replace("*", "")
            .strip()
        )

    def _truncate(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: max(limit - 1, 0)] + "…"

    async def _send_search_results(message: Message, query: str) -> None:
        await message.chat.send_action(action=ChatAction.TYPING)

        try:
            response = client.search_markets_events_profiles(query=query)
        except PolymarketClientError as exc:
            LOGGER.exception("Catalog search failed")
            detail = str(exc)
            if "401" in detail or "invalid token" in detail.lower():
                hint = (
                    "_Error:_ Polymarket Gamma rejected the request (unauthorized). "
                    "Please refresh your cookies/token in the backend environment."
                )
            else:
                hint = "_Error:_ Unable to contact Polymarket catalog."
            await message.reply_text(hint, parse_mode=ParseMode.MARKDOWN)
            return
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Catalog search failed")
            await message.reply_text(
                "_Error:_ Unable to contact Polymarket catalog.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        events = response.get("events") or []

        if not events:
            await message.reply_text(
                f"🔍 *Search results for:* {_sanitize(query)}\n\n_No events found._",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False,
            )
            return

        total = len(events)
        lines: List[str] = [
            f"🔍 *Search results for:* {_sanitize(query)}",
            f"Found {total} event{'s' if total != 1 else ''} (showing top {min(total, 3)}).",
            "",
            "*Events:*",
        ]

        keyboard_rows: List[List[InlineKeyboardButton]] = []
        event_map: Dict[str, str] = {}

        for idx, event in enumerate(events[:3], start=1):
            raw_title = (
                event.get("title")
                or event.get("name")
                or event.get("question")
                or event.get("slug")
                or event.get("ticker")
                or "Untitled event"
            )
            raw_title_str = str(raw_title).strip() or "Untitled event"
            title_display = _sanitize(raw_title_str)
            slug = event.get("slug") or event.get("ticker") or ""
            event_url = f"https://polymarket.com/event/{slug}" if slug else None

            header = f"*Event #{idx}:*"
            if event_url:
                header += f" [{title_display}]({event_url})"
            else:
                header += f" {title_display}"
            lines.append(header)

            details: List[str] = []
            liquidity = _format_usd(event.get("liquidity") or event.get("liquidityClob"))
            if liquidity:
                details.append(f"Liquidity {liquidity}")
            volume = _format_usd(event.get("volume24hr") or event.get("volume"))
            if volume:
                details.append(f"24h vol {volume}")
            markets_count = len(event.get("markets") or [])
            if markets_count:
                details.append(f"Markets {markets_count}")
            if details:
                lines.append("   " + " • ".join(details))

            description = event.get("description")
            if description:
                sanitized_desc = _truncate(_sanitize(str(description)), 220)
                lines.append(f"   {sanitized_desc}")

            nested_markets = event.get("markets") or []
            if nested_markets:
                for market in nested_markets[:3]:
                    market_title_raw = (
                        market.get("question")
                        or market.get("title")
                        or "Untitled market"
                    )
                    market_title = _truncate(_sanitize(str(market_title_raw)), 60)
                    market_slug = market.get("slug") or ""
                    market_url = f"https://polymarket.com/market/{market_slug}" if market_slug else None
                    if market_url:
                        lines.append(f"      • [{market_title}]({market_url})")
                    else:
                        lines.append(f"      • {market_title}")

            lines.append("")

            key = str(idx)
            event_map[key] = raw_title_str
            keyboard_rows.append(
                [InlineKeyboardButton(f"insight #{idx}", callback_data=f"insight:{key}")]
            )

        chat_id = message.chat_id if message.chat else None
        if chat_id is not None:
            search_sessions[chat_id] = {"event_insights": event_map}

        await message.reply_text(
            "\n".join(line for line in lines if line is not None),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
            reply_markup=InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None,
        )

    async def event_insight_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG001
        query = update.callback_query
        if query is None:
            return

        user_id = query.from_user.id if query.from_user else None
        if not _is_authorized(user_id):
            await query.answer("Not authorized", show_alert=True)
            return

        message_obj = query.message
        chat = message_obj.chat if message_obj else None
        if chat is None:
            await query.answer()
            return

        data = query.data or ""
        key = data.split(":", 1)[1] if data.startswith("insight:") else ""
        session = search_sessions.get(chat.id) or {}
        event_title = None
        insights_map = session.get("event_insights") if isinstance(session, dict) else None
        if isinstance(insights_map, dict):
            event_title = insights_map.get(key)

        if not event_title:
            await query.answer("Search results expired. Run /search again.", show_alert=True)
            return

        await query.answer("Generating insight…", show_alert=False)
        await chat.send_action(action=ChatAction.TYPING)

        try:
            insight_text = _generate_market_insight(event_title)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Inline insight generation failed")
            await chat.send_message(
                "_Error:_ Unable to generate insight right now. Please try again later.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        title_display = _sanitize(str(event_title))
        await chat.send_message(
            f"🧠 *Insight for:* {title_display}\n\n{insight_text}",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
        )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
        user_id = update.effective_user.id if update.effective_user else None
        if not _is_authorized(user_id):
            await _reject(update)
            return
        help_text = (
            "Commands:\n"
            "/start – brief intro\n"
            "/reset – clear conversation history\n"
            "/insight <market or event title> – fetch AI insights using web search\n"
            "/search <keywords> – browse related Polymarket markets or events\n"
            "Otherwise, just send messages describing what you want to do on Polymarket."
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def insight(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
        message = update.message
        if message is None:
            return
        user_id = update.effective_user.id if update.effective_user else None
        if not _is_authorized(user_id):
            await _reject(update)
            return

        query = " ".join(context.args).strip() if context.args else ""
        if not query:
            await message.reply_text(
                "Usage: /insight <event title or market id>",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await message.chat.send_action(action=ChatAction.TYPING)
        thinking_msg = await message.reply_text(
            "🧠 *Analyzing recent intel...*",
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            insight_text = _generate_market_insight(query)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Insight generation failed")
            await thinking_msg.edit_text(
                "_Error:_ Unable to generate insight right now. Please try again later.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await thinking_msg.edit_text(insight_text, parse_mode=ParseMode.MARKDOWN)

    async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
        message = update.message
        if message is None:
            return
        user_id = update.effective_user.id if update.effective_user else None
        if not _is_authorized(user_id):
            await _reject(update)
            return

        query = " ".join(context.args).strip() if context.args else ""
        if not query:
            prompt = await message.reply_text(
                "🧭 *Search Help*\nReply with keywords to search Polymarket markets and events.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=ForceReply(selective=True, input_field_placeholder="例如：US election"),
            )
            search_sessions[update.effective_chat.id] = {"prompt_id": prompt.message_id}
            return

        await _send_search_results(message, query)

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
        message = update.message
        if message is None:
            return
        user_id = update.effective_user.id if update.effective_user else None
        if not _is_authorized(user_id):
            await _reject(update)
            return

        text = (message.text or "").strip()
        if not text:
            return

        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id is None:
            return

        session = search_sessions.get(chat_id)
        if session and message.reply_to_message:
            prompt_id = session.get("prompt_id")
            if prompt_id and message.reply_to_message.message_id == prompt_id:
                search_sessions.pop(chat_id, None)
                if not text:
                    await message.reply_text(
                        "Please provide some keywords to search.",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    return
                original_args = getattr(context, "args", None)
                context.args = text.split()
                try:
                    await search_command(update, context)
                finally:
                    context.args = original_args
                return

        history = histories.setdefault(chat_id, [])
        await message.chat.send_action(action=ChatAction.TYPING)
        msg = await update.message.reply_text("🤔 *Thinking...*", parse_mode=ParseMode.MARKDOWN)

        # response_iter = agent.stream_response(text) 
        # text = ""
        # async for chunk in response_iter:
        #     text += chunk
        #     await msg.edit_text(text)
        try:
            result = run_agent_loop(agent, text, history)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Agent invocation failed")
            await msg.edit_text(
                "_Error:_ Something went wrong while contacting Polymarket. Please try again later.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        reply = result.get("output") or "(No response)"
        update_history(history, text, reply)
        await msg.edit_text(reply, parse_mode=ParseMode.MARKDOWN)

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("insight", insight))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CallbackQueryHandler(event_insight_callback, pattern=r"^insight:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return application


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    application = _build_application()
    LOGGER.info("Starting Telegram bot...")
    application.run_polling()


if __name__ == "__main__":
    main()
