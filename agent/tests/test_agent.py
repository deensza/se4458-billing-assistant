"""Agent orchestration tests with a scripted fake LLM (no API key, no network, no cloud)."""

import sys
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from billing_agent import REST_TOOLS, BillingAgent, ToolExecutionError  # noqa: E402


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def response(stop_reason, *blocks):
    return SimpleNamespace(
        stop_reason=stop_reason, content=list(blocks), usage=SimpleNamespace(input_tokens=100, output_tokens=20)
    )


class FakeLLM:
    """Returns scripted responses and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    async def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot
        return self.responses.pop(0)


class FakeMcp:
    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return [
            {
                "name": "search_billing_documentation",
                "description": "search",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            }
        ]

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"matches": [{"section": "3.2", "heading": "Additional internet blocks", "text": "$10 per 10 GB"}]}, False


class FakeBilling:
    def __init__(self, fail_with=None):
        self.calls = []
        self.fail_with = fail_with

    async def query_bill(self, subscriber_no, month, year):
        self.calls.append(("query_bill", subscriber_no, month, year))
        if self.fail_with:
            raise ToolExecutionError(self.fail_with)
        return {"billTotal": 80.0, "remainingBalance": 80.0}

    async def query_bill_detailed(self, subscriber_no, month, year, page, page_size):
        self.calls.append(("query_bill_detailed", subscriber_no, month, year, page, page_size))
        return {"internet": {"usageGb": 35.0, "charge": 70.0}}

    async def pay_bill(self, subscriber_no, month, year, amount, transaction_id):
        self.calls.append(("pay_bill", subscriber_no, month, year, amount, transaction_id))
        return {"paymentStatus": "SUCCESS", "remainingBalance": 50.0}


def make_agent(llm, billing=None, confirm_answer=True):
    confirmations = []

    async def confirm(summary):
        confirmations.append(summary)
        return confirm_answer

    agent = BillingAgent(
        llm=llm, model="test-model", mcp=FakeMcp(), billing=billing or FakeBilling(),
        subscriber_no="5551001", confirm=confirm,
    )
    return agent, confirmations


def run(agent, q):
    return anyio.run(agent.ask, q)


def test_rest_tools_never_accept_a_subscriber_number():
    for tool in REST_TOOLS:
        assert "subscriberNo" not in tool["input_schema"]["properties"]
        assert "subscriber_no" not in tool["input_schema"]["properties"]


def test_mcp_only_question():
    llm = FakeLLM(
        response("tool_use", tool_use("t1", "search_billing_documentation", {"query": "extra internet cost"})),
        response("end_turn", text("Each extra 10 GB costs $10 (Billing Guide §3.2).")),
    )
    agent, _ = make_agent(llm)
    turn = run(agent, "How much does extra internet cost?")
    assert agent.mcp.calls == [("search_billing_documentation", {"query": "extra internet cost"})]
    assert agent.billing.calls == []
    assert "§3.2" in turn.answer
    tool_step = [s for s in turn.trace if s.kind == "tool"][0]
    assert tool_step.data["route"] == "MCP"
    # the MCP tool schema offered to the LLM comes from the MCP server
    assert [t["name"] for t in llm.requests[0]["tools"]][0] == "search_billing_documentation"


def test_rest_only_question_uses_logged_in_subscriber():
    llm = FakeLLM(
        response("tool_use", tool_use("t1", "query_bill", {"month": 10, "year": 2026})),
        response("end_turn", text("Your October 2026 bill is $80.")),
    )
    agent, _ = make_agent(llm)
    turn = run(agent, "What is my October bill?")
    assert agent.billing.calls == [("query_bill", "5551001", 10, 2026)]
    assert agent.mcp.calls == []
    assert [s.data["route"] for s in turn.trace if s.kind == "tool"] == ["REST via API Gateway"]
    # tool result is sent back to the LLM
    last_user = llm.requests[1]["messages"][-1]
    assert last_user["content"][0]["type"] == "tool_result" and last_user["content"][0]["tool_use_id"] == "t1"


def test_combined_mcp_and_rest_question():
    llm = FakeLLM(
        response(
            "tool_use",
            tool_use("t1", "query_bill_detailed", {"month": 10, "year": 2026}),
            tool_use("t2", "search_billing_documentation", {"query": "extra data charges"}),
        ),
        response("end_turn", text("35 GB -> $70 internet (§3.2).")),
    )
    agent, _ = make_agent(llm)
    turn = run(agent, "Why is my October bill higher?")
    routes = [s.data["route"] for s in turn.trace if s.kind == "tool"]
    assert routes == ["REST via API Gateway", "MCP"]
    # both results returned in ONE user message
    assert len(llm.requests[1]["messages"][-1]["content"]) == 2


def test_payment_is_not_sent_without_confirmation():
    llm = FakeLLM(
        response("tool_use", tool_use("t1", "pay_bill", {"month": 10, "year": 2026, "amount": 30})),
        response("end_turn", text("Payment cancelled.")),
    )
    agent, confirmations = make_agent(llm, confirm_answer=False)
    turn = run(agent, "Pay 30 dollars of my October bill")
    assert confirmations == ["Pay $30.00 for subscriber 5551001, billing period 2026-10?"]
    assert agent.billing.calls == []  # payment API never called
    tool_step = [s for s in turn.trace if s.kind == "tool"][0]
    assert tool_step.data["result"]["paymentStatus"] == "NOT_SUBMITTED"


def test_confirmed_payment_calls_api_with_unique_transaction_id():
    llm = FakeLLM(
        response("tool_use", tool_use("t1", "pay_bill", {"month": 10, "year": 2026, "amount": 30})),
        response("end_turn", text("Paid $30. Remaining $50.")),
    )
    agent, confirmations = make_agent(llm, confirm_answer=True)
    run(agent, "Pay 30 dollars of my October bill")
    assert len(confirmations) == 1
    (name, subscriber, month, year, amount, txn) = agent.billing.calls[0]
    assert (name, subscriber, month, year, amount) == ("pay_bill", "5551001", 10, 2026, 30.0)
    assert txn.startswith("AGENT-")


def test_api_error_is_returned_to_llm_as_tool_error():
    llm = FakeLLM(
        response("tool_use", tool_use("t1", "query_bill", {"month": 9, "year": 2026})),
        response("end_turn", text("That bill has not been calculated yet.")),
    )
    billing = FakeBilling(fail_with={"httpStatus": 404, "error": {"code": "BILL_NOT_FOUND"}})
    agent, _ = make_agent(llm, billing=billing)
    turn = run(agent, "What is my September bill?")
    result_block = llm.requests[1]["messages"][-1]["content"][0]
    assert result_block["is_error"] is True and "BILL_NOT_FOUND" in result_block["content"]
    assert [s.data["isError"] for s in turn.trace if s.kind == "tool"] == [True]


def test_unknown_tool_and_bad_input_are_errors():
    llm = FakeLLM(
        response("tool_use", tool_use("t1", "delete_everything", {}), tool_use("t2", "query_bill", {"month": 10})),
        response("end_turn", text("ok")),
    )
    agent, _ = make_agent(llm)
    run(agent, "x")
    blocks = llm.requests[1]["messages"][-1]["content"]
    assert all(b["is_error"] for b in blocks)


def test_refusal_stop_reason_is_handled():
    agent, _ = make_agent(FakeLLM(response("refusal")))
    assert "can't help" in run(agent, "x").answer


@pytest.mark.parametrize("rounds", [8])
def test_tool_loop_is_bounded(rounds):
    llm = FakeLLM(*[response("tool_use", tool_use(f"t{i}", "query_bill", {"month": 10, "year": 2026})) for i in range(rounds)])
    agent, _ = make_agent(llm)
    assert "too many tool steps" in run(agent, "loop").answer


def test_system_prompt_defaults_to_previous_month():
    from datetime import date

    agent = BillingAgent(
        llm=FakeLLM(), model="m", mcp=FakeMcp(), billing=FakeBilling(), subscriber_no="5551001",
        confirm=None, today=date(2026, 1, 10),
    )
    assert "December 2025 (month=12, year=2025)" in agent.system
    assert "5551001" in agent.system
