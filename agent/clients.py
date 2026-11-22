"""Transport clients used by the agent: API Gateway (REST) and MCP (Streamable HTTP)."""

from __future__ import annotations

import json
from contextlib import AsyncExitStack

import httpx
from mcp import Client

from billing_agent import ToolExecutionError


class GatewayBillingClient:
    """Calls the Billing REST API through the API Gateway with the logged-in user's JWT."""

    def __init__(self, gateway_url: str, timeout: float = 20.0):
        self.http = httpx.AsyncClient(base_url=gateway_url.rstrip("/"), timeout=timeout)
        self.token: str | None = None
        self.subscriber_no: str | None = None
        self.role: str | None = None

    async def login(self, username: str, password: str) -> dict:
        r = await self.http.post("/api/v1/auth/token", json={"username": username, "password": password})
        body = self._json(r)
        if r.status_code != 200:
            raise ToolExecutionError(body)
        self.token, self.subscriber_no, self.role = body["accessToken"], body["subscriberNo"], body["role"]
        return body

    @property
    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @staticmethod
    def _json(r: httpx.Response) -> dict:
        try:
            body = r.json()
        except json.JSONDecodeError:
            body = {"raw": r.text}
        if r.status_code >= 400:
            return {"httpStatus": r.status_code, **(body if isinstance(body, dict) else {"body": body})}
        return body

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        r = await self.http.request(method, url, headers=self._auth, **kwargs)
        body = self._json(r)
        if r.status_code >= 400:
            raise ToolExecutionError(body)
        return body

    async def query_bill(self, subscriber_no: str, month: int, year: int) -> dict:
        # Query Bill is a public endpoint; the token is still sent (harmless) for consistency.
        return await self._request(
            "GET", "/api/v1/bills", params={"subscriberNo": subscriber_no, "month": month, "year": year}
        )

    async def query_bill_detailed(self, subscriber_no: str, month: int, year: int, page: int, page_size: int) -> dict:
        return await self._request(
            "GET",
            "/api/v1/bills/detailed",
            params={"subscriberNo": subscriber_no, "month": month, "year": year, "page": page, "pageSize": page_size},
        )

    async def pay_bill(self, subscriber_no: str, month: int, year: int, amount: float, transaction_id: str) -> dict:
        return await self._request(
            "POST",
            "/api/v1/payments",
            json={
                "subscriberNo": subscriber_no,
                "month": month,
                "year": year,
                "amount": amount,
                "transactionId": transaction_id,
            },
        )

    async def aclose(self):
        await self.http.aclose()


class McpToolClient:
    """MCP client (official SDK) connected to the MCP server over Streamable HTTP."""

    def __init__(self, server_url: str):
        self.server_url = server_url
        self._stack = AsyncExitStack()
        self._client: Client | None = None

    async def __aenter__(self) -> "McpToolClient":
        self._client = await self._stack.enter_async_context(Client(self.server_url))
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()

    async def list_tools(self) -> list[dict]:
        tools = (await self._client.list_tools()).tools
        return [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in tools]

    async def call_tool(self, name: str, arguments: dict) -> tuple[dict | str, bool]:
        result = await self._client.call_tool(name, arguments)
        if result.structured_content is not None:
            return result.structured_content, result.is_error
        text = "\n".join(getattr(c, "text", "") for c in result.content)
        return text, result.is_error
