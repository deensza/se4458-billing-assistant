"""Live MCP retrieval demonstration: connects to a running MCP server with the official MCP client,
lists the tool and runs three distinct retrieval queries.

    .venv/bin/python scripts/mcp_demo.py                                   # local  (http://localhost:8001/mcp)
    MCP_URL=https://<mcp-host>/mcp .venv/bin/python scripts/mcp_demo.py    # cloud
"""

import asyncio
import json
import os
from datetime import datetime, timezone

from mcp import Client

MCP_URL = os.getenv("MCP_URL", "http://localhost:8001/mcp")
QUERIES = [
    "How much does extra internet cost?",  # pricing
    "What happens with late payments?",  # due date / reminders / restriction
    "How can I dispute a charge on my bill?",  # disputes
]


async def main() -> None:
    print(f"MCP server: {MCP_URL}")
    print(f"Run at: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC\n")
    async with Client(MCP_URL) as client:
        tools = (await client.list_tools()).tools
        print("== tools/list")
        for tool in tools:
            print(f"- {tool.name}: input schema {json.dumps(tool.input_schema)}")
        for i, query in enumerate(QUERIES, 1):
            result = await client.call_tool("search_billing_documentation", {"query": query})
            data = result.structured_content
            print(f"\n== Retrieval test {i}: search_billing_documentation(query={query!r})")
            print(f"document: {data['document']} ({data['documentId']}), isError={result.is_error}")
            for m in data["matches"]:
                text = " ".join(m["text"].split())
                print(f"  §{m['section']} {m['heading']}  [{m['parentHeading'] or '-'}]  score={m['score']}")
                print(f"      {text[:160]}{'…' if len(text) > 160 else ''}")


if __name__ == "__main__":
    asyncio.run(main())
