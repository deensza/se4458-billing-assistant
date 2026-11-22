"""Command-line chat for the Mobile Provider Billing Assistant.

    python agent/cli.py                       # interactive (asks username/password)
    python agent/cli.py --user user1001 --password 'Pass1001!' --ask "How much does extra internet cost?"

Environment:
    ANTHROPIC_API_KEY   Claude API key (or an `ant auth login` profile)
    GATEWAY_URL         API Gateway base URL         (default http://localhost:8000)
    MCP_URL             MCP server endpoint          (default http://localhost:8001/mcp)
    AGENT_MODEL         Claude model                 (default claude-haiku-5-5 - lowest cost)
    AGENT_EFFORT        low | medium | high          (default high)

Every turn prints a tool trace (LLM tool selection, tool name, route, input, result, final answer) and
saves it as JSON + Markdown under docs/traces/.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from billing_agent import BillingAgent, ToolExecutionError, TurnResult  # noqa: E402
from clients import GatewayBillingClient, McpToolClient  # noqa: E402

TRACE_DIR = Path(__file__).resolve().parents[1] / "docs" / "traces"
# USD per 1M tokens (input, output) - Claude API list prices
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}


def _short(value, limit: int = 600) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + " …"


def render_trace(turn: TurnResult, model: str) -> str:
    lines = [f"### Question\n{turn.question}\n", "### Tool trace"]
    n = 0
    for step in turn.trace:
        if step.kind == "llm":
            chosen = ", ".join(f"{t['name']}({json.dumps(t['input'], ensure_ascii=False)})" for t in step.data["selectedTools"])
            lines.append(f"- **LLM** (stop_reason={step.data['stopReason']}): {chosen or 'final answer, no tool'}")
        else:
            n += 1
            d = step.data
            lines.append(f"- **Tool {n}: `{d['tool']}`** via *{d['route']}*{' (ERROR)' if d['isError'] else ''}")
            lines.append(f"  - input: `{json.dumps(d['input'], ensure_ascii=False)}`")
            lines.append(f"  - result: `{_short(d['result'])}`")
    price_in, price_out = PRICES.get(model, (0, 0))
    cost = turn.usage["input_tokens"] / 1e6 * price_in + turn.usage["output_tokens"] / 1e6 * price_out
    lines += [
        f"\n### Final answer\n{turn.answer}\n",
        f"_Model {model}: {turn.usage['input_tokens']} input + {turn.usage['output_tokens']} output tokens "
        f"≈ ${cost:.5f}_",
    ]
    return "\n".join(lines)


def save_trace(turn: TurnResult, model: str, label: str | None) -> Path:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = label or re.sub(r"[^a-z0-9]+", "-", turn.question.lower()).strip("-")[:40]
    base = TRACE_DIR / f"{stamp}-{slug}"
    base.with_suffix(".json").write_text(
        json.dumps({"model": model, **turn.to_dict()}, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    base.with_suffix(".md").write_text(render_trace(turn, model) + "\n", encoding="utf-8")
    return base.with_suffix(".md")


async def confirm_in_terminal(summary: str) -> bool:
    print(f"\n⚠️  PAYMENT CONFIRMATION REQUIRED\n    {summary}")
    answer = await asyncio.to_thread(input, "    Type 'yes' to confirm, anything else to cancel: ")
    return answer.strip().lower() in {"yes", "y", "evet", "e"}


def load_dotenv(path: Path = Path(__file__).resolve().parents[1] / ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines); real environment variables take precedence."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


async def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Mobile Provider Billing Assistant (CLI)")
    parser.add_argument("--user")
    parser.add_argument("--password")
    parser.add_argument("--ask", action="append", help="Ask one or more questions non-interactively")
    parser.add_argument("--label", help="File name label for the saved trace")
    args = parser.parse_args()

    gateway_url = os.getenv("GATEWAY_URL", "http://localhost:8000")
    mcp_url = os.getenv("MCP_URL", "http://localhost:8001/mcp")
    model = os.getenv("AGENT_MODEL", "claude-haiku-5-5")
    effort = os.getenv("AGENT_EFFORT", "high")

    billing = GatewayBillingClient(gateway_url)
    username = args.user or input("Username: ")
    password = args.password or getpass.getpass("Password: ")
    try:
        login = await billing.login(username, password)
    except ToolExecutionError as exc:
        print(f"Login failed: {exc.payload}")
        return 1
    if login["role"] != "SUBSCRIBER":
        print("The assistant is for subscriber accounts. Log in as a subscriber user.")
        return 1
    print(f"Logged in as {username} (subscriber {login['subscriberNo']}). Gateway: {gateway_url}  MCP: {mcp_url}")

    try:
        async with McpToolClient(mcp_url) as mcp, anthropic.AsyncAnthropic() as llm:
            agent = BillingAgent(
                llm=llm,
                model=model,
                mcp=mcp,
                billing=billing,
                subscriber_no=login["subscriberNo"],
                confirm=confirm_in_terminal,
                effort=effort,
            )
            questions = args.ask or []
            interactive = not questions
            while True:
                if interactive:
                    try:
                        question = (await asyncio.to_thread(input, "\nYou: ")).strip()
                    except EOFError:
                        break
                    if question.lower() in {"exit", "quit", "q"}:
                        break
                    if not question:
                        continue
                elif questions:
                    question = questions.pop(0)
                    print(f"\nYou: {question}")
                else:
                    break
                turn = await agent.ask(question)
                print("\n" + render_trace(turn, model))
                print(f"\n(trace saved to {save_trace(turn, model, args.label)})")
    finally:
        await billing.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
