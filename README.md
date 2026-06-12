# mojawave-mcp

MojaWave MCP server — connect any MCP-compatible AI assistant to the
[MojaWave](https://mojawave.com) SMS Gateway.

Works with **Claude** (Desktop & Code), **ChatGPT** (via OpenAI Agents SDK),
**Gemini** (via Google ADK), **Cursor**, **Windsurf**, and any other tool that
speaks the [Model Context Protocol](https://modelcontextprotocol.io).

Every tool maps to a documented endpoint of the [MojaWave public API](https://mojawave.com/docs)
— nothing undocumented is exposed.

---

## Available tools

| Tool | API endpoint | What it does |
| --- | --- | --- |
| `send_sms` | `POST /sms/send` | Send a single SMS, optionally scheduled (`schedule_at`) |
| `send_bulk_sms` | `POST /sms/bulk` | Start an async bulk SMS job for up to 10,000 recipients — returns a `job_id` |
| `get_bulk_sms_job` | `GET /sms/bulk/{id}` | Poll the status and progress of a bulk SMS job |
| `get_message` | `GET /messages/{id}` | Get full details and delivery timeline for a single message |
| `get_credit_balance` | `GET /credits` | Check current SMS and email credit balances |
| `verify_webhook_signature` | — | Verify a webhook's `X-MojaWave-Signature` (HMAC-SHA256) |

Inputs are validated before any request is made (E.164 phone numbers, 1–11-char
sender IDs, message length, recipient count, ISO-8601 schedule times), and the
client retries `429`/`5xx` responses with backoff that honours `Retry-After`.

---

## Installation

```bash
pip install mojawave-mcp
```

Or for local development:

```bash
git clone https://github.com/mojawave/mojawave-mcp
cd mojawave-mcp
pip install -e ".[dev]"
```

---

## Configuration

Copy `.env.example` to `.env` and add your API key:

```bash
cp .env.example .env
```

```env
MOJAWAVE_API_KEY=sk_live_mw_xxxxxxxxxxxxxxxxxxxx
```

Get your API key from the [MojaWave dashboard](https://app.mojawave.com) under
**Settings → API Keys**.

Use a **test key** (`sk_test_mw_…`) during development — it returns synthetic
responses without sending real messages or charging credits.

---

## Connecting to AI assistants

### Claude Desktop

Add this block to `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "mojawave": {
      "command": "mojawave-mcp",
      "env": {
        "MOJAWAVE_API_KEY": "sk_live_mw_xxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

Restart Claude Desktop. You will see a **MojaWave** tool icon in the chat interface.

---

### Claude Code (CLI)

```bash
claude mcp add mojawave -- env MOJAWAVE_API_KEY=sk_live_mw_xxx mojawave-mcp
```

---

### Cursor / Windsurf / any stdio MCP client

Point the client at the `mojawave-mcp` command with your API key as an
environment variable. Most clients use the same JSON config format as Claude
Desktop above — refer to your client's MCP documentation.

---

### OpenAI Agents SDK (ChatGPT / GPT-4o)

Start the server in **SSE mode** so OpenAI can reach it over HTTP:

```bash
MOJAWAVE_API_KEY=sk_live_mw_xxx mojawave-mcp --transport sse --port 8080
```

Then connect from Python:

```python
from agents import Agent, Runner
from agents.mcp import MCPServerSse

async def main():
    server = MCPServerSse(url="http://localhost:8080/sse")
    async with server:
        agent = Agent(
            name="MojaWave Agent",
            model="gpt-4o",
            mcp_servers=[server],
        )
        result = await Runner.run(
            agent, "Send an SMS to +255712345678 saying Hello from AI"
        )
        print(result.final_output)
```

---

### Google Gemini (Google ADK)

Start the server in SSE mode:

```bash
MOJAWAVE_API_KEY=sk_live_mw_xxx mojawave-mcp --transport sse --port 8080
```

Then connect from Python:

```python
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseServerParams

mojawave_tools = MCPToolset(
    connection_params=SseServerParams(url="http://localhost:8080/sse")
)

agent = LlmAgent(
    model="gemini-2.0-flash",
    name="mojawave_agent",
    instruction="You can send SMS and check credits via MojaWave.",
    tools=[mojawave_tools],
)
```

---

### Hosted deployment (Docker)

For production, run the SSE server behind a reverse proxy:

```dockerfile
FROM python:3.12-slim
RUN pip install mojawave-mcp
ENV MOJAWAVE_API_KEY=""
EXPOSE 8080
CMD ["mojawave-mcp", "--transport", "sse", "--port", "8080"]
```

```bash
docker build -t mojawave-mcp .
docker run -e MOJAWAVE_API_KEY=sk_live_mw_xxx -p 8080:8080 mojawave-mcp
```

---

## Running locally (stdio)

```bash
MOJAWAVE_API_KEY=sk_live_mw_xxx mojawave-mcp
```

The server reads JSON-RPC from stdin and writes to stdout — the standard MCP
stdio transport used by Claude Desktop and most IDE extensions.

---

## Bulk SMS workflow

Bulk sends are asynchronous. `send_bulk_sms` returns a `job_id` immediately;
use `get_bulk_sms_job` to poll until the job completes:

```text
1. send_bulk_sms(recipients=[...], message="...", sender_id="MYAPP")
   → { "job_id": "ec0fb57c-...", "status": "scheduled", "total_recipients": 500 }

2. get_bulk_sms_job(job_id="ec0fb57c-...")
   → { "status": "processing", "progress_percent": 42, "sent_count": 210 }

3. get_bulk_sms_job(job_id="ec0fb57c-...")
   → { "status": "completed", "total_recipients": 500, "total_credits_cost": 500 }
```

---

## Security notes

- Never commit your API key. Use environment variables or a secrets manager.
- Use **test keys** (`sk_test_mw_…`) in CI/CD and development — no real messages are sent and no credits are charged.
- Scope API keys to only the permissions they need from the MojaWave dashboard.
- Webhook payloads are signed with `X-MojaWave-Signature` (HMAC-SHA256) — verify signatures on your server before trusting delivery events.

---

## License

MIT
