"""MCP server (official MCP Python SDK, Streamable HTTP transport) exposing:

    search_billing_documentation(query) -> relevant excerpts with section references

The policy document is indexed ONCE at start-up (see docs_index.py); every tool call reuses the index.
Endpoint: http://<host>:8001/mcp     Health check: GET /health
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

sys.path.insert(0, str(Path(__file__).parent))
from docs_index import DEFAULT_DOC_PATH, BillingDocsIndex  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("billing_mcp")

DOC_PATH = Path(os.getenv("BILLING_DOC_PATH", str(DEFAULT_DOC_PATH)))
MAX_RESULTS = 3

# ---- Indexed once, before any query is served --------------------------------------------
INDEX = BillingDocsIndex.from_file(DOC_PATH)
logger.info("Indexed %s (%s) into %d chunks.", INDEX.document, INDEX.document_id, len(INDEX.chunks))



class PolicyMatch(BaseModel):
    section: str = Field(description="Section id in the guide, e.g. '3.2'")
    heading: str = Field(description="Section heading, e.g. 'Additional internet blocks'")
    parentHeading: str | None = Field(description="Parent section, e.g. '3. Internet pricing'")
    text: str = Field(description="Excerpt text of the section")
    score: float = Field(description="BM25 relevance score")


class SearchResult(BaseModel):
    document: str
    documentId: str
    query: str
    matches: list[PolicyMatch]
    message: str | None = None


mcp = MCPServer(
    name="billing-documentation",
    version="1.0.0",
    instructions=(
        "Search the Mobile Provider Billing Guide (policies, pricing, payments, late payments, disputes). "
        "It contains NO live subscriber data; use the Billing REST API for bills, usage and payments."
    ),
)


@mcp.tool(
    name="search_billing_documentation",
    description=(
        "Full-text search over the Mobile Provider Billing Guide (MOB-BILLING-2026-01). Use it for billing "
        "rules: phone/internet pricing and allowances, bill calculation, billing cycles and due dates, "
        "partial payments, late payments/service restriction and disputes. Returns up to 3 excerpts, each "
        "with section id, heading and text, so answers can cite e.g. 'Section 3.2'. It does NOT contain any "
        "subscriber's bill, usage or payment records."
    ),
)
def search_billing_documentation(
    query: str = Field(description='Natural-language search text, e.g. "extra internet cost" or "late payment"'),
) -> SearchResult:
    query = (query or "").strip()
    if not query:
        return SearchResult(
            document=INDEX.document, documentId=INDEX.document_id, query=query, matches=[], message="Empty query."
        )
    result = SearchResult(**INDEX.search(query, top_k=MAX_RESULTS))
    logger.info("search_billing_documentation(%r) -> %s", query, [m.section for m in result.matches])
    if not result.matches:
        result.message = "No relevant section found in the billing guide."
    return result


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "document": INDEX.document, "chunks": len(INDEX.chunks)})


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8001")),
        stateless_http=True,
        json_response=True,
        # Read-only public documentation search served behind a cloud ingress with its own
        # hostname, so Host-header (DNS rebinding) checks are disabled.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
