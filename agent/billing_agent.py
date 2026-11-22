"""AI Agent orchestrator.

Flow for every user question:
    user question -> LLM (Claude) selects tools -> the AGENT executes them
        * MCP tools  -> MCP client -> MCP server (search_billing_documentation)
        * REST tools -> Billing REST API **via the API Gateway** (JWT of the logged-in user)
    -> tool results are sent back to the LLM -> grounded final answer (with guide section references).

The LLM never calls backend services directly; it only returns tool_use requests.

Security rules enforced in code (not only in the prompt):
    * REST tools have NO subscriberNo parameter. The agent always uses the subscriber number from the
      logged-in user's JWT, so a prompt such as "show the bill of 5551002" cannot reach another
      subscriber's private data. The API also re-checks ownership (403).
    * pay_bill is executed only after the human explicitly confirms the subscriber, period and
      amount (confirm callback). A declined confirmation never reaches the payment API.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

MAX_TOOL_ROUNDS = 8

REST_TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_bill",
        "description": (
            "Query Bill (REST API via gateway) for the LOGGED-IN subscriber: bill total, paid amount, remaining "
            "balance, status and due date for one billing month. Use for 'what is my bill/balance' questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "integer", "minimum": 1, "maximum": 12, "description": "Billing month 1-12"},
                "year": {"type": "integer", "minimum": 2000, "maximum": 2100, "description": "Billing year"},
            },
            "required": ["month", "year"],
            "additionalProperties": False,
        },
    },
    {
        "name": "query_bill_detailed",
        "description": (
            "Query Bill Detailed (REST API via gateway) for the LOGGED-IN subscriber: totals plus phone minutes, "
            "internet MB/GB, extra blocks and the phone/internet charge breakdown, and a page of usage records. "
            "Use it to explain why a bill is high or what was charged."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "integer", "minimum": 1, "maximum": 12},
                "year": {"type": "integer", "minimum": 2000, "maximum": 2100},
                "page": {"type": "integer", "minimum": 1, "description": "Usage records page (default 1)"},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Default 5"},
            },
            "required": ["month", "year"],
            "additionalProperties": False,
        },
    },
    {
        "name": "pay_bill",
        "description": (
            "Pay Bill (REST API via gateway): record a simulated full or partial payment for the LOGGED-IN "
            "subscriber. Only call it when the user asked to pay and the month, year and amount are known. "
            "The application itself shows the user a confirmation prompt and only submits after an explicit yes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "integer", "minimum": 1, "maximum": 12},
                "year": {"type": "integer", "minimum": 2000, "maximum": 2100},
                "amount": {"type": "number", "exclusiveMinimum": 0, "description": "Amount in USD, max 2 decimals"},
            },
            "required": ["month", "year", "amount"],
            "additionalProperties": False,
        },
    },
]
REST_TOOL_NAMES = {t["name"] for t in REST_TOOLS}

SYSTEM_PROMPT = """You are the Mobile Provider Billing Assistant for a mobile operator.
Today's date is {today}. The logged-in subscriber number is {subscriber_no}.

Tools:
- search_billing_documentation (MCP): billing POLICIES from the Mobile Provider Billing Guide - pricing, allowances,
  bill calculation, due dates, partial payments, late payments, disputes. It has no live account data.
- query_bill, query_bill_detailed, pay_bill (Billing REST API via the API Gateway): LIVE data and payments for the
  logged-in subscriber only.

How to answer:
- Policy / pricing question -> search_billing_documentation only.
- Question about the user's own bill, balance or usage -> REST tools only.
- Explaining the user's own charges (e.g. "why is my bill higher?") -> BOTH: get the real numbers with
  query_bill_detailed and the rules with search_billing_documentation. "Higher" means compared with the previous
  month, so also call query_bill_detailed for the previous month and compare the two (if it does not exist,
  say so).
- Use the breakdown values returned by the API (minutes, GB, extraBlocks, charge) exactly as they are; do not
  recalculate or speculate about other block counts.
- When you use the guide, cite the section, e.g. "(Billing Guide §3.2)".
- Never invent usage, totals or balances; only state stored values returned by the API. If a bill is not found,
  say it has not been calculated yet.
- You can only access the logged-in subscriber's account. If the user asks about another subscriber number, refuse.
- Payments: you need month, year and amount. If the amount or period is missing, ask for it (you may first call
  query_bill to show the remaining balance). Then call pay_bill; the application asks the user to confirm.
  Report a payment as successful only if pay_bill returns paymentStatus SUCCESS.
- "This month" means the current calendar month; bills are usually calculated after the month ends.
- If the user does not name a billing period ("my bill", "pay my bill"), use the most recent completed month,
  {last_month_name} ({last_month}). For "pay my bill" without an amount, check that bill with query_bill and pay
  the full remaining balance (the application still asks the user to confirm the period and amount).
- Be concise. Answer in the same language as the user."""


class BillingApi(Protocol):
    async def query_bill(self, subscriber_no: str, month: int, year: int) -> dict: ...
    async def query_bill_detailed(
        self, subscriber_no: str, month: int, year: int, page: int, page_size: int
    ) -> dict: ...
    async def pay_bill(
        self, subscriber_no: str, month: int, year: int, amount: float, transaction_id: str
    ) -> dict: ...


class McpTools(Protocol):
    async def list_tools(self) -> list[dict]: ...
    async def call_tool(self, name: str, arguments: dict) -> tuple[dict | str, bool]: ...


ConfirmFn = Callable[[str], Awaitable[bool]]


class ToolExecutionError(Exception):
    def __init__(self, payload: Any):
        super().__init__(str(payload))
        self.payload = payload


@dataclass
class TraceStep:
    kind: str  # "llm" | "tool"
    data: dict


@dataclass
class TurnResult:
    question: str
    answer: str
    trace: list[TraceStep] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "trace": [{"kind": s.kind, **s.data} for s in self.trace],
            "finalAnswer": self.answer,
            "usage": self.usage,
        }


class BillingAgent:
    def __init__(
        self,
        llm,
        model: str,
        mcp: McpTools,
        billing: BillingApi,
        subscriber_no: str,
        confirm: ConfirmFn,
        effort: str = "high",
        today: date | None = None,
        max_tokens: int = 4096,
    ):
        self.llm = llm
        self.model = model
        self.mcp = mcp
        self.billing = billing
        self.subscriber_no = subscriber_no
        self.confirm = confirm
        self.effort = effort
        self.max_tokens = max_tokens
        today = today or date.today()
        last = date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)
        self.system = SYSTEM_PROMPT.format(
            today=today.isoformat(),
            subscriber_no=subscriber_no,
            last_month=f"month={last.month}, year={last.year}",
            last_month_name=last.strftime("%B %Y"),
        )
        self.messages: list[dict] = []
        self.tools: list[dict] | None = None
        self.mcp_tool_names: set[str] = set()

    async def _load_tools(self) -> list[dict]:
        if self.tools is None:
            mcp_tools = await self.mcp.list_tools()  # schemas come from the MCP server itself
            self.mcp_tool_names = {t["name"] for t in mcp_tools}
            self.tools = mcp_tools + REST_TOOLS
        return self.tools

    # ------------------------------------------------------------------ tool execution
    async def _execute(self, name: str, args: dict) -> tuple[str, Any, bool]:
        """Returns (route, result, is_error)."""
        if name in self.mcp_tool_names:
            result, is_error = await self.mcp.call_tool(name, args)
            return "MCP", result, is_error
        if name not in REST_TOOL_NAMES:
            return "agent", {"error": f"Unknown tool {name}"}, True

        route = "REST via API Gateway"
        try:
            month, year = int(args["month"]), int(args["year"])
            if name == "query_bill":
                return route, await self.billing.query_bill(self.subscriber_no, month, year), False
            if name == "query_bill_detailed":
                return route, await self.billing.query_bill_detailed(
                    self.subscriber_no, month, year, int(args.get("page", 1)), int(args.get("page_size", 5))
                ), False
            # pay_bill: explicit human confirmation BEFORE the payment API is called
            amount = round(float(args["amount"]), 2)
            summary = (
                f"Pay ${amount:.2f} for subscriber {self.subscriber_no}, billing period {year}-{month:02d}?"
            )
            if not await self.confirm(summary):
                return "agent (payment not sent)", {
                    "paymentStatus": "NOT_SUBMITTED",
                    "reason": "The user did not confirm the payment. Nothing was charged.",
                }, False
            transaction_id = f"AGENT-{uuid.uuid4()}"
            return route, await self.billing.pay_bill(self.subscriber_no, month, year, amount, transaction_id), False
        except ToolExecutionError as exc:
            return route, exc.payload, True
        except (KeyError, TypeError, ValueError) as exc:
            return "agent", {"error": f"Invalid tool input: {exc}"}, True

    # ------------------------------------------------------------------ one conversation turn
    async def ask(self, question: str) -> TurnResult:
        tools = await self._load_tools()
        turn = TurnResult(question=question, answer="")
        self.messages.append({"role": "user", "content": question})

        for _ in range(MAX_TOOL_ROUNDS):
            response = await self.llm.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system,
                tools=tools,
                output_config={"effort": self.effort},
                messages=self.messages,
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                turn.usage["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
                turn.usage["output_tokens"] += getattr(usage, "output_tokens", 0) or 0

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            turn.trace.append(
                TraceStep(
                    "llm",
                    {
                        "stopReason": response.stop_reason,
                        "selectedTools": [{"name": b.name, "input": b.input} for b in tool_uses],
                    },
                )
            )
            # Keep the full assistant content (incl. thinking blocks) unchanged in the history.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                turn.answer = "Sorry, I can't help with that request."
                return turn
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use" or not tool_uses:
                turn.answer = "".join(b.text for b in response.content if b.type == "text").strip()
                return turn

            results = []
            for block in tool_uses:
                route, result, is_error = await self._execute(block.name, dict(block.input))
                turn.trace.append(
                    TraceStep(
                        "tool",
                        {"tool": block.name, "route": route, "input": block.input, "result": result, "isError": is_error},
                    )
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result if isinstance(result, str) else json.dumps(result, default=str),
                        "is_error": is_error,
                    }
                )
            self.messages.append({"role": "user", "content": results})

        turn.answer = "I could not finish this request (too many tool steps). Please try rephrasing."
        return turn
