from __future__ import annotations

from typing import Any, Dict, List, Sequence

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from .client import PolymarketClient
from .tools import build_polymarket_tools

# Mirrors https://docs.langchain.com/oss/python/langchain/agents guidance.
SYSTEM_INSTRUCTIONS = (
    "You are a Polymarket trading assistant. "
    "Reason about the user's intent, call tools when necessary, and report order ids, "
    "prices, and statuses in plain language."
)


def build_polymarket_agent(
    client: PolymarketClient,
    model: str = "gpt-4o-mini",
    temperature: float = 0.0,
    system_prompt: str = SYSTEM_INSTRUCTIONS,
):
    tools = build_polymarket_tools(client)
    llm = ChatOpenAI(model=model, temperature=temperature)
    return create_agent(model=llm, tools=tools, system_prompt=system_prompt)


def update_history(history: List[Dict[str, str]], user_text: str, agent_output: str) -> None:
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": agent_output})


def run_agent_loop(
    agent: Any,
    user_text: str,
    history: Sequence[Dict[str, str]] | None = None,
) -> dict:
    messages: List[Any] = list(history or [])
    messages.append({"role": "user", "content": user_text})
    result = agent.invoke({"messages": messages})

    output = ""
    if isinstance(result, dict):
        agent_messages = result.get("messages")
        if agent_messages:
            last_msg = agent_messages[-1]
            if isinstance(last_msg, BaseMessage):
                output = last_msg.content
            elif isinstance(last_msg, dict):
                output = last_msg.get("content", "")
        else:
            output = result.get("output", "")
    else:
        output = str(result)

    return {"output": output, "raw": result}
