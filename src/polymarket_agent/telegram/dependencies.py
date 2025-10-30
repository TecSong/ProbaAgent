from __future__ import annotations

import os
from types import SimpleNamespace

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

__all__ = [
    "Application",
    "CallbackQueryHandler",
    "CommandHandler",
    "ContextTypes",
    "ForceReply",
    "InlineKeyboardButton",
    "InlineKeyboardMarkup",
    "Message",
    "MessageHandler",
    "Update",
    "ChatAction",
    "ParseMode",
    "filters",
]
