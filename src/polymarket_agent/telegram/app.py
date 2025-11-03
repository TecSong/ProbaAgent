"""Telegram bot application wiring for the Polymarket agent."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from dotenv import load_dotenv

from polymarket_agent.agent import build_polymarket_agent, run_agent_loop, update_history
from polymarket_agent.client import PolymarketClientError
from polymarket_agent.main import build_client_from_env
from polymarket_agent.prompt import MAX_RESULTS
from polymarket_agent.user import (
    TelegramUserInfo,
    UserService,
    UserServiceError,
    WalletBalanceError,
    get_wallet_balances,
)

from .dependencies import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageHandler,
    Update,
    ChatAction,
    ParseMode,
    filters,
)
from .insight import generate_market_insight, NoRelevantMarketError
from .snapshot import collect_market_snapshot, format_usd
from scripts.test_tg_text_format import (
    MARKDOWN_SAMPLE,
    format_markdown_v2_diagnostics,
)

load_dotenv()

LOGGER = logging.getLogger(__name__)


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


def _collect_market_snapshot(client: Any, query: str) -> str | None:
    return collect_market_snapshot(client, query)


def build_application() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN in environment.")

    allowed_ids = _parse_allowed_ids(os.getenv("TELEGRAM_ALLOWED_USER_IDS"))
    client = build_client_from_env()
    agent = build_polymarket_agent(client)
    try:
        user_service = UserService.from_env()
    except UserServiceError as exc:
        raise SystemExit(f"Unable to initialize Supabase user service: {exc}") from exc
    histories: Dict[int, List[Dict[str, str]]] = {}
    search_sessions: Dict[int, Dict[str, Any]] = {}
    insight_sessions: Dict[int, Dict[str, Any]] = {}

    def _generate_market_insight(query: str, max_results: int = MAX_RESULTS) -> str:
        return generate_market_insight(client, query, max_results=max_results)

    def _is_authorized(user_id: int | None) -> bool:
        if not allowed_ids:
            return True
        if user_id is None:
            return False
        return user_id in allowed_ids

    async def _reject(update: Update):
        if update.effective_message:
            await update.effective_message.reply_text("You are not authorized to use this bot.")

    def _extract_telegram_user_info(update: Update) -> TelegramUserInfo | None:
        user = update.effective_user
        if not user:
            return None
        return TelegramUserInfo(
            telegram_id=user.id,
            username=getattr(user, "username", None),
            first_name=getattr(user, "first_name", None),
            last_name=getattr(user, "last_name", None),
        )

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
        user_id = update.effective_user.id if update.effective_user else None
        if not _is_authorized(user_id):
            await _reject(update)
            return
        info = _extract_telegram_user_info(update)
        if info is not None:
            try:
                user_service.ensure_telegram_user(info)
            except UserServiceError as exc:
                LOGGER.warning(
                    "Unable to prepare wallet for Telegram user %s: %s",
                    info.telegram_id,
                    exc,
                )
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
            liquidity = format_usd(event.get("liquidity") or event.get("liquidityClob"))
            if liquidity:
                details.append(f"Liquidity {liquidity}")
            volume = format_usd(event.get("volume24hr") or event.get("volume"))
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
                        lines.append(f"      • Market: [{market_title}]({market_url})")
                    else:
                        lines.append(f"      • Market: {market_title}")

            lines.append("")

            key = str(idx)
            event_map[key] = raw_title_str
            keyboard_rows.append(
                [InlineKeyboardButton(f"make insights for #{idx}", callback_data=f"insight:{key}")]
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
            "/wallet – view your wallet address and balances\n"
            "/insight <market or event title> – fetch AI insights using web search\n"
            "/search <keywords> – browse related Polymarket markets or events\n"
            "/debugmarkdown [text] – inspect Markdown V2 formatting (defaults to sample)\n"
            "Otherwise, just send messages describing what you want to do on Polymarket."
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
        message = update.message
        if message is None:
            return
        user_id = update.effective_user.id if update.effective_user else None
        if not _is_authorized(user_id):
            await _reject(update)
            return
        info = _extract_telegram_user_info(update)
        if info is None:
            await message.reply_text(
                "_Error:_ Unable to identify your Telegram user.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        try:
            record = user_service.ensure_telegram_user(info)
        except UserServiceError:
            LOGGER.exception("Fetching wallet for user %s failed", info.telegram_id)
            await message.reply_text(
                "_Error:_ Wallet service is temporarily unavailable.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        try:
            balances = get_wallet_balances(record.wallet_address)
        except WalletBalanceError as exc:
            LOGGER.warning(
                "Balance fetch failed for wallet %s: %s",
                record.wallet_address,
                exc,
            )
            balances = None

        lines = [
            "💼 *Wallet information*",
            "",
            f"Address: `{record.wallet_address}`",
        ]

        if balances is not None:
            lines.extend(
                [
                    "",
                    f"*USDC.e balance:* {balances.format_usdc()}",
                    f"*POL balance:* {balances.format_pol()}",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "_Balances temporarily unavailable._",
                ]
            )

        await message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )

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
            prompt = await message.reply_text(
                "🧠 *Insight Help*\nReply with an event or market to generate an AI insight.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=ForceReply(selective=True, input_field_placeholder="eg: Trump"),
            )
            chat_id = update.effective_chat.id if update.effective_chat else None
            if chat_id is not None:
                insight_sessions[chat_id] = {"prompt_id": prompt.message_id}
            return

        await message.chat.send_action(action=ChatAction.TYPING)
        thinking_msg = await message.reply_text(
            "🧠 *Analyzing...*",
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            insight_text = _generate_market_insight(query)
        except NoRelevantMarketError:
            await thinking_msg.edit_text(
                "No related events or markets were found. Please try different keywords.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Insight generation failed")
            await thinking_msg.edit_text(
                "_Error:_ Unable to generate insight right now. Please try again later.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await thinking_msg.edit_text(insight_text, parse_mode=ParseMode.MARKDOWN)

    async def debug_markdown(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
        message = update.message
        if message is None:
            return

        user_id = update.effective_user.id if update.effective_user else None
        if not _is_authorized(user_id):
            await _reject(update)
            return

        raw_text = " ".join(context.args).strip() if context.args else ""
        if not raw_text and message.reply_to_message:
            reply_source = message.reply_to_message
            raw_text = (reply_source.text or reply_source.caption or "").strip()

        if not raw_text:
            raw_text = MARKDOWN_SAMPLE

        await message.reply_text(
            raw_text,
            parse_mode=ParseMode.MARKDOWN,
            # disable_web_page_preview=True,
        )

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
                reply_markup=ForceReply(selective=True, input_field_placeholder="eg: Trump"),
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

        insight_session = insight_sessions.get(chat_id)
        if insight_session and message.reply_to_message:
            prompt_id = insight_session.get("prompt_id")
            if prompt_id and message.reply_to_message.message_id == prompt_id:
                insight_sessions.pop(chat_id, None)
                if not text:
                    await message.reply_text(
                        "Please provide an event or market to analyze.",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    return
                original_args = getattr(context, "args", None)
                context.args = text.split()
                try:
                    await insight(update, context)
                finally:
                    context.args = original_args
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
    application.add_handler(CommandHandler("wallet", wallet))
    application.add_handler(CommandHandler("insight", insight))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("debugmarkdown", debug_markdown))
    application.add_handler(CallbackQueryHandler(event_insight_callback, pattern=r"^insight:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return application


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    application = build_application()
    LOGGER.info("Starting Telegram bot...")
    application.run_polling()


if __name__ == "__main__":
    main()
