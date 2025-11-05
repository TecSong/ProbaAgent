# ProbaAgent

LangChain agent that speaks natural language to the Polymarket CLOB API. The project wraps the official [`py-clob-client`](https://github.com/polymarket/py-clob-client) SDK, exposes it through structured LangChain tools, and ships both a command-line experience and a full-stack Flask + React chatbot.

## Highlights

- **End-to-end workflow** – inspect open orders, list markets, fetch quotes, submit or cancel trades.
- **Production-friendly API** – Flask server with CORS and history management at `/api/chat`.
- **Modern UI** – Vite + React single-page app with optimistic updates and status feedback.
- **Telegram bot** – optional Bot API bridge so users can chat from mobile/desktop Telegram clients.
- **Configurable** – all credentials and runtime knobs live in `.env`.

## Prerequisites

- Python 3.11+
- Node.js 18+ (for the React frontend)
- Polymarket wallet/private key and OpenAI API key

## Backend Quickstart (CLI or API)

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
2. **Configure environment variables**  
   Copy `.env.example` to `.env` and fill in:
   - `OPENAI_API_KEY` – model used by LangChain (defaults to `gpt-4o-mini`).
   - `POLYMARKET_HOST` – CLOB endpoint (default `https://clob.polymarket.com`).
   - `POLYMARKET_CHAIN_ID` / `POLYMARKET_SIGNATURE_TYPE` – Polygon mainnet uses `137` / `0`.
   - `POLYMARKET_PRIVATE_KEY` – private key for signing orders (store securely!).
   - `POLYMARKET_FUNDER` – optional for EOAs; required for Magic/funder setups.
   - `POLYMARKET_GAMMA_BASE` – Gamma Markets API base (default `https://gamma-api.polymarket.com`).
   - `POLYMARKET_DEBUG` – set to `true`/`1` to log payloads and HTTP traces.
3. **Run the interactive CLI**
   ```bash
   python -m polymarket_agent.main --verbose
   ```
   Enter prompts such as “List my open orders for market xyz” or “Place a buy order on token abc at 0.42”.

## Flask + React Chatbot

### 1. Start the Flask backend

```bash
# Optional but recommended: use a virtualenv
export FRONTEND_ORIGIN=http://localhost:5173
python -m flask --app src.server run --port 8000
```

Useful environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `8000` | Overrides the listening port when running `src.server`. |
| `FRONTEND_ORIGIN` | `*` | CORS allowlist for `/api/*`. Set to your Vite dev server or production domain. |
| `FLASK_DEBUG` | `false` | Enables Flask debug + live reload. |
| `CHATBOT_INCLUDE_TRACE` | `false` | Adds the LangChain `raw` payload to `/api/chat` responses for debugging. |

### 2. Launch the React frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server runs on `http://localhost:5173` and proxies `/api/*` to `http://localhost:8000`. For production builds, configure `VITE_API_BASE` to point at the deployed API (e.g., `/api` behind a reverse proxy) and run `npm run build`.

### 3. Chat in the browser

Visit http://localhost:5173 to talk to the agent. Each message sends the accumulated history to `/api/chat`, which invokes the LangChain agent and returns the updated transcript plus the latest reply.

## Telegram Bot

1. **Set credentials** – add the following keys to `.env`:
   - `TELEGRAM_BOT_TOKEN` – token obtained from @BotFather.
   - `TELEGRAM_ALLOWED_USER_IDS` – optional comma-separated list of numeric user IDs allowed to chat with the bot. Leave blank to allow everyone.
2. **Run the bot**
   ```bash
   python src/scripts/telegram_bot.py
   ```
   The process keeps a conversation history per chat ID and relays every incoming message to the LangChain agent. Use `/reset` to clear the history or `/help` for available commands.

### Docker Deployment

1. **Build the image**
   ```bash
   docker build -t polymarket-telegram-bot .
   ```
2. **Run with Compose** – ensure your `.env` contains the Telegram and Polymarket credentials, then launch:
   ```bash
   docker compose -f docker-compose.telegram.yml up -d
   ```
3. **Inspect logs** – confirm the bot connected successfully:
   ```bash
   docker compose -f docker-compose.telegram.yml logs -f
   ```

## Project Structure

- `polymarket_agent/client.py` – thin wrapper around `py-clob-client` + Gamma `/markets`.
- `polymarket_agent/tools.py` – converts client methods into LangChain `StructuredTool`s.
- `polymarket_agent/agent.py` – builds the agent via `langchain.agents.create_agent`.
- `polymarket_agent/main.py` – simple CLI loop maintaining conversational history.
- `src/server.py` – Flask service exposing `/health` and `/api/chat`.
- `src/scripts/telegram_bot.py` – Telegram Bot API bridge with optional user allowlist.
- `frontend/` – Vite + React SPA with a polished chat interface.

## Extending the Agent

1. Add more Polymarket endpoints (balances, transfers, market creation, etc.) and expose them as new tools.
2. Layer in retrieval-augmented context (market metadata, strategy prompts) via LangChain retrievers.
3. Wrap the Flask server with additional transports (REST, gRPC, Slack bot, Telegram bot).
4. Add integration tests using VCR/pytest-httpx to replay Polymarket responses across critical flows.
