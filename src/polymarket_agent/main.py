from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List

from dotenv import load_dotenv

from .agent import build_polymarket_agent, run_agent_loop, update_history
from .client import PolymarketClient, PolymarketClientConfig


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_client_from_env() -> PolymarketClient:
    host = os.getenv("POLYMARKET_HOST", "https://clob.polymarket.com")
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    chain_id = int(os.getenv("POLYMARKET_CHAIN_ID", "137"))
    signature_type = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "1"))
    funder = os.getenv("POLYMARKET_FUNDER")
    gamma_base = os.getenv("POLYMARKET_GAMMA_BASE", "https://gamma-api.polymarket.com")
    debug = _env_flag("POLYMARKET_DEBUG")

    if not private_key:
        raise SystemExit("Missing POLYMARKET_PRIVATE_KEY for py-clob-client.")

    cfg = PolymarketClientConfig(
        host=host,
        private_key=private_key,
        chain_id=chain_id,
        signature_type=signature_type,
        funder=funder,
        gamma_base=gamma_base,
        debug=debug,
    )
    return PolymarketClient(cfg)


def interactive_loop(verbose: bool) -> None:
    load_dotenv()
    client = build_client_from_env()
    agent = build_polymarket_agent(client)

    history: List[Dict[str, str]] = []
    print("Polymarket agent ready. Type 'exit' to quit.")
    while True:
        try:
            user_text = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break
        if user_text.lower() in {"exit", "quit"}:
            print("bye")
            break
        if not user_text:
            continue
        result = run_agent_loop(agent, user_text, history)
        output = result.get("output", "")
        if verbose:
            raw = result.get("raw")
            try:
                print(json.dumps(raw, indent=2))  # type: ignore[arg-type]
            except TypeError:
                print(raw)
        print(f"Agent> {output}")
        update_history(history, user_text, output)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Natural language Polymarket order management agent."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print intermediate reasoning traces.",
    )
    args = parser.parse_args()
    interactive_loop(verbose=args.verbose)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        raise
