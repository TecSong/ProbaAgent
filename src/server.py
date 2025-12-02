from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

from polymarket_agent.agent import (
    build_polymarket_agent,
    run_agent_loop,
    update_history,
)
from polymarket_agent.main import build_client_from_env

load_dotenv()

LOGGER = logging.getLogger("polymarket_chatbot")


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _create_agent() -> Any:
    client = build_client_from_env()
    return build_polymarket_agent(client)


def _sanitize_history(candidate: Any) -> List[Dict[str, str]]:
    history: List[Dict[str, str]] = []
    if not isinstance(candidate, list):
        return history
    for item in candidate:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant", "system"}:
            continue
        if not isinstance(content, str):
            continue
        history.append({"role": role, "content": content})
    return history


def _wallet_context_prompt(context: Any) -> str | None:
    if not isinstance(context, dict):
        return None

    is_connected = bool(context.get("isConnected") and context.get("address"))
    if not is_connected:
        return "Wallet context: user is not connected to a wallet."

    address = context.get("address") or ""
    chain_id = context.get("chainId") or context.get("networkChainId")
    network = context.get("networkName")
    balance_wei = context.get("balanceWei")
    balance_eth = context.get("balanceEth")

    parts = ["Wallet context: user is connected.", f"Address: {address}."]
    if chain_id:
        parts.append(f"Chain ID: {chain_id}.")
    if network:
        parts.append(f"Network: {network}.")
    if balance_eth:
        parts.append(f"Balance (ETH): {balance_eth}.")
    elif balance_wei:
        parts.append(f"Balance (wei): {balance_wei}.")

    return " ".join(parts)


def create_app() -> Flask:
    app = Flask(__name__)
    allowed_origin = os.getenv("FRONTEND_ORIGIN", "*")
    CORS(app, resources={r"/api/*": {"origins": allowed_origin}})

    agent_holder: Dict[str, Any] = {"agent": None}
    include_trace = _env_flag("CHATBOT_INCLUDE_TRACE")

    @app.get("/health")
    def health_check():
        return jsonify({"status": "ok"})

    @app.post("/api/chat")
    def chat_endpoint():
        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message") or "").strip()
        if not message:
            return jsonify({"error": "message is required"}), 400

        history = _sanitize_history(payload.get("history"))
        wallet_prompt = _wallet_context_prompt(
            payload.get("walletContext") or payload.get("wallet_context")
        )
        agent_history = list(history)
        if wallet_prompt:
            agent_history.append({"role": "system", "content": wallet_prompt})
        try:
            if agent_holder["agent"] is None:
                agent_holder["agent"] = _create_agent()
            agent = agent_holder["agent"]
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Unable to initialize Polymarket agent")
            return (
                jsonify(
                    {
                        "error": "Server configuration error. Check environment variables.",
                        "detail": str(exc),
                    }
                ),
                500,
            )

        try:
            result = run_agent_loop(agent, message, agent_history)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Agent execution failed")
            return (
                jsonify({"error": "Unable to process request. See server logs.", "detail": str(exc)}),
                500,
            )

        reply = result.get("output") or ""
        update_history(history, message, reply)
        response = {"reply": reply, "history": history}
        if include_trace:
            response["raw"] = result.get("raw")
        return jsonify(response)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=_env_flag("FLASK_DEBUG"))
