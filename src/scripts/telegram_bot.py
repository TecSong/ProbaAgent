"""Telegram bot bridge for the Polymarket LangChain agent."""

from __future__ import annotations

import logging
import os
from typing import Dict, List

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from polymarket_agent.agent import build_polymarket_agent, run_agent_loop, update_history
from polymarket_agent.main import build_client_from_env

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


def _build_application() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN in environment.")

    allowed_ids = _parse_allowed_ids(os.getenv("TELEGRAM_ALLOWED_USER_IDS"))
    client = build_client_from_env()
    agent = build_polymarket_agent(client)
    histories: Dict[int, List[Dict[str, str]]] = {}

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
            "Send me natural-language questions like 'List my open orders' or 'Place a buy order at 0.42'."
        )
        await update.message.reply_text(msg)

    async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
        user_id = update.effective_user.id if update.effective_user else None
        if not _is_authorized(user_id):
            await _reject(update)
            return
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id is not None:
            histories.pop(chat_id, None)
        await update.message.reply_text("Conversation history cleared.")

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
        user_id = update.effective_user.id if update.effective_user else None
        if not _is_authorized(user_id):
            await _reject(update)
            return
        help_text = (
            "Commands:\n"
            "/start – brief intro\n"
            "/reset – clear conversation history\n"
            "Otherwise, just send messages describing what you want to do on Polymarket."
        )
        await update.message.reply_text(help_text)

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

        history = histories.setdefault(chat_id, [])
        await message.chat.send_action(action=ChatAction.TYPING)
        msg = await update.message.reply_text("🤔 Thinking...")

        # response_iter = agent.stream_response(text) 
        # text = ""
        # async for chunk in response_iter:
        #     text += chunk
        #     await msg.edit_text(text)
        try:
            result = run_agent_loop(agent, text, history)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Agent invocation failed")
            await message.reply_text(
                "Something went wrong while contacting Polymarket. Please try again later."
            )
            return

        reply = result.get("output") or "(No response)"
        update_history(history, text, reply)
        await msg.edit_text(reply)

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return application


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    application = _build_application()
    LOGGER.info("Starting Telegram bot...")
    application.run_polling()


if __name__ == "__main__":
    main()
