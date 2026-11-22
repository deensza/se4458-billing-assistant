"""Unit tests for the billing-guide index and the MCP tool (no network, no LLM)."""

import sys
from pathlib import Path

import anyio
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp import Client  # noqa: E402

import server  # noqa: E402
from docs_index import BillingDocsIndex, chunk_markdown, tokenize  # noqa: E402


@pytest.fixture(scope="module")
def index():
    return BillingDocsIndex.from_file()


# ---------------- chunking ----------------
def test_document_is_split_into_section_chunks(index):
    sections = [c.section for c in index.chunks]
    assert len(index.chunks) == 26
    assert sections[:3] == ["0", "1", "2.1"]
    assert {"3.2", "4.3", "5.2", "6.3", "7.1", "8.4", "9"} <= set(sections)
    assert index.document_id == "MOB-BILLING-2026-01"


def test_chunk_keeps_heading_parent_and_text(index):
    chunk = next(c for c in index.chunks if c.section == "3.2")
    assert chunk.heading == "Additional internet blocks"
    assert chunk.parent_heading == "3. Internet pricing"
    assert "Each additional **10 GB block** costs **$10**" in chunk.text


def test_headings_inside_code_blocks_are_not_split():
    md = "## 1. A\ntext\n```\n## 2. not a heading\n```\n### 1.1 Sub\nbody"
    chunks = chunk_markdown(md)
    assert [c.section for c in chunks] == ["1", "1.1"]
    assert "## 2. not a heading" in chunks[0].text


def test_tokenizer_removes_stop_words_and_stems():
    assert tokenize("What are the additional blocks?") == ["additional", "block"]


# ---------------- three distinct retrieval queries ----------------
@pytest.mark.parametrize(
    "query, expected_sections",
    [
        ("How much does extra internet cost?", {"8.1", "3.2"}),  # pricing
        ("What happens with late payments?", {"6.1", "6.2", "6.3"}),  # late payments / due date
        ("How can I dispute a charge on my bill?", {"8.4", "7.1"}),  # disputes
    ],
)
def test_three_distinct_retrieval_queries(index, query, expected_sections):
    result = index.search(query)
    returned = [m["section"] for m in result["matches"]]
    assert result["matches"][0]["section"] in expected_sections
    assert expected_sections & set(returned)
    assert len(returned) <= 3


def test_partial_payment_query(index):
    sections = [m["section"] for m in index.search("Can I pay only part of my bill?")["matches"]]
    assert sections[0] == "8.3" and "5.1" in sections


def test_unrelated_query_returns_no_matches(index):
    assert index.search("zebra giraffe banana")["matches"] == []


def test_result_format_matches_guide_section_9(index):
    result = index.search("extra data charges")
    assert result["document"] == "Mobile_Provider_Billing_Guide.md"
    assert set(result["matches"][0]) == {"section", "heading", "parentHeading", "text", "score"}


# ---------------- MCP protocol (in-process client -> server) ----------------
def test_index_is_built_once_at_startup():
    assert server.INDEX is not None and len(server.INDEX.chunks) == 26


def test_mcp_tool_is_listed_with_query_schema():
    async def run():
        async with Client(server.mcp) as client:
            return (await client.list_tools()).tools

    tools = anyio.run(run)
    assert [t.name for t in tools] == ["search_billing_documentation"]
    schema = tools[0].input_schema
    assert schema["required"] == ["query"]
    assert schema["properties"]["query"]["type"] == "string"


def test_mcp_tool_call_returns_excerpts_with_sections():
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool("search_billing_documentation", {"query": "extra internet cost"})

    result = anyio.run(run)
    assert result.is_error is False
    data = result.structured_content
    assert data["documentId"] == "MOB-BILLING-2026-01"
    assert data["matches"][0]["section"] == "8.1"
    assert any(m["section"] == "3.2" for m in data["matches"])


def test_mcp_tool_empty_query_returns_message():
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool("search_billing_documentation", {"query": "   "})

    data = anyio.run(run).structured_content
    assert data["matches"] == [] and data["message"] == "Empty query."
