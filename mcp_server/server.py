"""MCP server (official MCP Python SDK, Streamable HTTP transport) exposing:

    search_billing_documentation(query) -> relevant excerpts with section references

The policy document is indexed ONCE at start-up (see docs_index.py); every tool call reuses the index.
Endpoint: http://<host>:8001/mcp     Health check: GET /health
A browser opening / or /mcp gets a short HTML page that describes the server and can run the tool.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

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


INFO_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Billing Documentation MCP Server</title>
<style>
body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:860px;margin:32px auto;padding:0 16px;color:#1f2937;line-height:1.5}
h1{font-size:24px;margin-bottom:4px}code,pre{background:#f3f4f6;border-radius:4px}code{padding:1px 4px}
pre{padding:12px;overflow-x:auto;font-size:13px;white-space:pre-wrap}
input{width:70%;padding:8px;font-size:15px}button{padding:8px 16px;font-size:15px;cursor:pointer}
.match{border:1px solid #e5e7eb;border-radius:6px;padding:10px 12px;margin:8px 0}.muted{color:#6b7280}
</style></head><body>
<h1>Billing Documentation MCP Server</h1>
<p class="muted">SE 4458 Midterm 1, Group 2. Official MCP Python SDK, Streamable HTTP transport.</p>
<p>This is an <b>MCP server</b>, not a website: MCP clients (the AI agent) send JSON-RPC requests with
<code>POST /mcp</code>. This page is shown only to browsers. The server indexes
<code>__DOCUMENT__</code> (<code>__DOCUMENT_ID__</code>) once at start-up into __CHUNKS__ chunks.</p>
<h2>Tool</h2>
<p><code>search_billing_documentation(query: string)</code> returns up to 3 excerpts of the billing guide
with section numbers. It contains no subscriber data.</p>
<h2>Try the tool</h2>
<p>This form sends a real MCP <code>tools/call</code> request to <code>/mcp</code>:</p>
<form id="f"><input id="q" value="How much does extra internet cost?" aria-label="Query">
<button>Search</button></form>
<div id="out"></div>
<h2>Same request with curl</h2>
<pre>curl -X POST __BASE__/mcp \\
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \\
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_billing_documentation","arguments":{"query":"extra internet cost"}}}'</pre>
<p>Health check: <a href="/health">/health</a></p>
<script>
document.getElementById("f").addEventListener("submit", async (e) => {
  e.preventDefault();
  const out = document.getElementById("out");
  out.textContent = "Searching...";
  try {
    const r = await fetch("/mcp", {method: "POST",
      headers: {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
      body: JSON.stringify({jsonrpc: "2.0", id: 1, method: "tools/call",
        params: {name: "search_billing_documentation", arguments: {query: document.getElementById("q").value}}})});
    const data = await r.json();
    const result = data.result && data.result.structuredContent;
    out.textContent = "";
    if (!result) { out.textContent = JSON.stringify(data); return; }
    if (!result.matches.length) { out.textContent = result.message || "No match."; return; }
    for (const m of result.matches) {
      const div = document.createElement("div"); div.className = "match";
      const h = document.createElement("b"); h.textContent = "\\u00a7" + m.section + " " + m.heading;
      const s = document.createElement("span"); s.className = "muted"; s.textContent = "  (score " + m.score + ")";
      const t = document.createElement("div"); t.textContent = m.text.replace(/\\*\\*/g, "");
      div.append(h, s, t); out.append(div);
    }
  } catch (err) { out.textContent = "Error: " + err; }
});
</script>
</body></html>
"""


def info_page(base_url: str) -> str:
    return (
        INFO_PAGE.replace("__DOCUMENT__", INDEX.document)
        .replace("__DOCUMENT_ID__", INDEX.document_id)
        .replace("__CHUNKS__", str(len(INDEX.chunks)))
        .replace("__BASE__", base_url.rstrip("/"))
    )


class BrowserInfoPage:
    """ASGI middleware: a browser GET on / or /mcp gets the HTML info page.

    MCP clients are not affected: they POST to /mcp, and a GET that asks for an SSE stream
    (Accept: text/event-stream) is passed to the MCP transport unchanged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in ("GET", "HEAD") and scope["path"] in ("/", "/mcp"):
            request = Request(scope)
            if "text/event-stream" not in request.headers.get("accept", ""):
                proto = request.headers.get("x-forwarded-proto", request.url.scheme)
                base = f"{proto}://{request.headers.get('host', request.url.netloc)}"
                await HTMLResponse(info_page(base))(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_app(host: str = "0.0.0.0") -> ASGIApp:
    app = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        # Read-only public documentation search served behind a cloud ingress with its own
        # hostname, so Host-header (DNS rebinding) checks are disabled.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        host=host,
    )
    app.add_middleware(BrowserInfoPage)
    return app


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("MCP_HOST", "0.0.0.0")
    uvicorn.run(build_app(host), host=host, port=int(os.getenv("PORT", "8001")), proxy_headers=True, forwarded_allow_ips="*")
