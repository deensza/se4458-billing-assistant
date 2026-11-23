# Mobile Provider Billing Assistant — SE 4458 Midterm 1 (Group 2)

**Student:** Bermal Deniz Akkaya  ·  **Group:** 2 – AI Billing Support Assistant

An integrated, service-oriented system with the four mandatory components:

1. **AI Agent** (`agent/`): Claude LLM with real tool/function calling. The agent executes every tool call itself.
2. **MCP Server** (`mcp_server/`): official MCP Python SDK; exposes `search_billing_documentation(query)` over an indexed copy of `Mobile_Provider_Billing_Guide.md`.
3. **Billing REST API + server database** (`billing_api/`): FastAPI and PostgreSQL, versioned under `/api/v1`, JWT authentication, Swagger UI.
4. **API Gateway** (`gateway/`): Kong (DB-less). **All** REST calls go through it, including the agent's calls.

**Live deployment (Azure):** API Gateway `https://gateway.happystone-4bc228e1.germanywestcentral.azurecontainerapps.io` · Swagger UI `https://gateway.happystone-4bc228e1.germanywestcentral.azurecontainerapps.io/api/v1/docs` · MCP `https://mcp-server.happystone-4bc228e1.germanywestcentral.azurecontainerapps.io/mcp`

---

## Table of contents
1. [Architecture](#1-architecture)
2. [Repository structure](#2-repository-structure)
3. [Technology choices](#3-technology-choices)
4. [REST API](#4-rest-api)
5. [Business rules](#5-business-rules)
6. [Data model (ER diagram)](#6-data-model-er-diagram)
7. [Authentication & authorization](#7-authentication--authorization)
8. [API Gateway](#8-api-gateway)
9. [MCP server & AI agent](#9-mcp-server--ai-agent)
10. [Run locally](#10-run-locally)
11. [Unit tests](#11-unit-tests)
12. [Cloud deployment](#12-cloud-deployment)
13. [Test data & reproduction steps for the instructor](#13-test-data--reproduction-steps-for-the-instructor)
14. [Demo video](#14-demo-video)
15. [Assumptions](#15-assumptions)
16. [LLM cost & low-cost testing](#16-llm-cost--low-cost-testing)

---

## 1. Architecture

```mermaid
flowchart TB
    U["User / Chat UI<br/>(command-line chat, agent/cli.py)"] -->|question| A["AI Agent Orchestrator<br/>(LLM client + tool execution)"]
    A <-->|"prompts / tool requests"| L["LLM: Claude (Anthropic API)<br/>(tool selection + response)"]
    A -->|"MCP tool call"| MC["MCP Client<br/>(official MCP Python SDK)"]
    A -->|"REST request + JWT"| G["API Gateway: Kong<br/>(versioned routes /api/v1/*,<br/>JWT validation, rate limiting)"]
    MC <-->|"Streamable HTTP /mcp"| MS["MCP Server<br/>(search tool: search_billing_documentation)"]
    MS <-->|"retrieve passages"| IDX[("Indexed Policy Markdown Document<br/>Mobile_Provider_Billing_Guide.md<br/>(BM25 index, built once at start-up)")]
    G <--> API["Billing REST API: FastAPI<br/>(business operations)"]
    API <--> DB[("Billing Database: PostgreSQL<br/>(live records)")]
```

* **The LLM never calls a backend.** It only returns `tool_use` requests. The agent executes them and sends the `tool_result`s back, and the LLM writes the grounded final answer with guide section references.
* **The MCP path and the API Gateway path are separate.** MCP traffic goes agent → MCP client → MCP server. REST traffic goes agent → Kong → Billing API → PostgreSQL.
* The policy document is **indexed once** when the MCP server starts, never per question. The policy document is **not** the billing database: live bills, usage and payments come only from the REST API.

## 2. Repository structure

```
billing_api/            Billing REST API (FastAPI, SQLAlchemy, PostgreSQL)
  app/main.py           app + Swagger UI (/api/v1/docs)
  app/routers/v1.py     versioned routes (/api/v1/...)
  app/services.py       business logic          app/pricing.py   pricing rules (pure functions)
  app/models.py         database model           app/security.py  JWT + authorization
  app/seed.py           demo/test data           tests/           76 unit tests
mcp_server/             MCP server (official MCP Python SDK, Streamable HTTP)
  server.py             tool search_billing_documentation(query)
  docs_index.py         chunking + BM25 full-text index
  data/Mobile_Provider_Billing_Guide.md          tests/   16 unit tests
agent/                  AI agent (Claude tool calling) + CLI chat
  billing_agent.py      orchestrator: tool loop, confirmation gate, trace
  clients.py            MCP client + API-Gateway REST client
  cli.py                command-line chat, saves traces to docs/traces/   tests/  11 unit tests
gateway/                Kong declarative config, Dockerfile, entrypoint
infra/azure-deploy.sh   one-command Azure deployment (re-runnable)
infra/reset-cloud-data.sh  reset the cloud database to the demo data
scripts/                run_tests.sh, gateway_demo.sh, mcp_demo.py, render_er_diagram.py
docs/                   openapi.json, er-diagram.png/.svg/.md, mcp-tool-schema.json, test-results.txt,
                        test-results-postgresql.txt, mcp-retrieval-demo-*.txt, mcp-server-log-*.txt,
                        gateway-demo-*.txt, traces/ (agent tool traces)
docker-compose.yml      local stack (PostgreSQL + API + MCP + Kong)
```

## 3. Technology choices

| Concern | Choice | Why |
|---|---|---|
| API style | **REST** (JSON, camelCase) | Required operations map 1:1 to resources; works through any gateway |
| API framework | Python 3.12 + FastAPI | Automatic OpenAPI 3 / Swagger UI, request validation |
| Database | **PostgreSQL 16** (Azure Database for PostgreSQL Flexible Server in the cloud) | Server database as required (SQLite is used **only** inside the unit tests, see §11) |
| Versioning | URL path versioning `/api/v1/...` | A breaking change becomes `/api/v2` (a new router) while v1 keeps working; the gateway routes are versioned too |
| Gateway | **Kong 3.9** (DB-less, declarative) | The same config file runs locally and in the cloud; JWT and rate-limiting plugins |
| Auth | **JWT (HS256)**, issued by `POST /api/v1/auth/token` | Validated at the gateway (signature + expiry) **and** in the API (role + account ownership) |
| MCP | Official **MCP Python SDK 2.x** (`MCPServer`, Streamable HTTP) | A real MCP server, not a REST imitation |
| LLM | **Claude `claude-haiku-5-5`** via the Anthropic Python SDK (configurable with `AGENT_MODEL`) | Native tool calling, lowest cost (§16) |
| Search | BM25 full-text over heading-based chunks | Full-text indexing is accepted by the spec; deterministic and testable |
| Cloud | **Azure**: Container Apps + Container Registry + PostgreSQL Flexible Server | Azure for Students credit |
| Tests | pytest | Run offline without cloud or LLM |

## 4. REST API

Base URL (through the gateway): local `http://localhost:8000`, cloud: see §12.
**Swagger UI:** `{GATEWAY_URL}/api/v1/docs`. **OpenAPI spec:** `{GATEWAY_URL}/api/v1/openapi.json` (committed copy: [`docs/openapi.json`](docs/openapi.json)).

| Operation | Method & path | Parameters | Response | Auth | Paging |
|---|---|---|---|---|---|
| Login | `POST /api/v1/auth/token` | body `username`, `password` | `accessToken`, `expiresIn`, `role`, `subscriberNo` | – | – |
| **Add Usage** | `POST /api/v1/usage` | body `subscriberNo`, `month`, `year`, `usageType` (`Phone` \| `Internet`, case-insensitive) | transaction status (+ `usageId`, `quantityAdded`, `unit`) | **YES** (own account or ADMIN) | NO |
| **Calculate Bill** | `POST /api/v1/bills/calculate` | body `subscriberNo`, `month`, `year` | transaction status (+ bill summary, `action` CREATED/RECALCULATED) | **YES** (own account or ADMIN) | NO |
| **Query Bill** | `GET /api/v1/bills` | query `subscriberNo`, `month`, `year` | `billTotal`, `paidAmount`, `remainingBalance`, `status`, `dueDate` | NO | NO |
| **Query Bill Detailed** | `GET /api/v1/bills/detailed` | query `subscriberNo`, `month`, `year`, `page` (≥1, default 1), `pageSize` (1–100, default 20) | totals + `phone` {minutes, extraBlocks, charge} + `internet` {usageMb, usageGb, extraBlocks, charge} + paged `usageRecords` | **YES** (own account or ADMIN) | **YES** |
| **Pay Bill** | `POST /api/v1/payments` | body `subscriberNo`, `month`, `year`, `amount`, `transactionId` | `paymentStatus`, `paidAmount`, `totalPaid`, `remainingBalance`, `billStatus` | **YES** (own account or ADMIN) | NO |

**Error format (all errors):**
```json
{"error": {"code": "AMOUNT_EXCEEDS_BALANCE", "message": "Payment amount 1000 exceeds the remaining balance 50.00.", "details": {"remainingBalance": 50.0}}}
```

| HTTP | `code` | When |
|---|---|---|
| 401 | `AUTHENTICATION_REQUIRED`, `INVALID_TOKEN`, `TOKEN_EXPIRED`, `INVALID_CREDENTIALS` | missing/invalid/expired token, wrong login |
| 403 | `FORBIDDEN`, `GATEWAY_REQUIRED` | another subscriber's account; request did not come through the API Gateway |
| 404 | `SUBSCRIBER_NOT_FOUND`, `BILL_NOT_FOUND` | unknown subscriber; bill not calculated yet |
| 409 | `DUPLICATE_TRANSACTION`, `BILL_ALREADY_PAID` | reused transaction ID; nothing left to pay |
| 422 | `VALIDATION_ERROR`, `AMOUNT_EXCEEDS_BALANCE` | invalid input (month 13, amount ≤ 0, > 2 decimals …); amount > remaining balance |
| 429 | (gateway) `API rate limit exceeded` | rate limit hit |

Gateway-generated errors (401 at the gateway, 404 unknown route, 429) use Kong's format `{"message": "..."}`.

## 5. Business rules

Implemented in [`billing_api/app/pricing.py`](billing_api/app/pricing.py), following guide sections 2–4 and 6.1:

* **Add Usage:** each `PHONE` event adds **10 minutes**; each `INTERNET` event adds **1 MB**.
* **Phone:** first 1,000 minutes free, then **$10 per started 1,000-minute block**: `10 × ceil(max(0, minutes − 1000) / 1000)`.
* **Internet:** **$50** up to 20 GB (also with zero usage), then **$10 per started 10 GB block**: `50 + 10 × ceil(max(0, GB − 20) / 10)`. **1 GB = 1,000 MB**.
* **Total** = phone + internet. No taxes or fees. Worked example (guide §4.3): 1,350 min + 35 GB → $10 + $70 = **$80** (unit-tested).
* **Calculate Bill** stores the bill (one row per subscriber/month). Running it again **recalculates** from all recorded usage and **keeps the payments already made**.
* **Pay Bill:** full or partial payments. A partial payment gives `PARTIALLY_PAID`; the bill is `PAID` only when the remaining balance is 0 (guide §5.1). Rejected: duplicate `transactionId` (409, nothing recorded, balance preserved), amount > remaining balance (422), bill already fully paid (409), amount ≤ 0 or more than 2 decimals (422). The bill row is locked (`SELECT … FOR UPDATE`) and `transaction_id` is `UNIQUE`, so concurrent duplicates are also rejected. **No real card processing.**
* **Due date** = 15 days after the end of the billing month (guide §6.1), returned as `dueDate`.

## 6. Data model (ER diagram)

![ER diagram](docs/er-diagram.png)

Image: [`docs/er-diagram.png`](docs/er-diagram.png) / [`docs/er-diagram.svg`](docs/er-diagram.svg) (generated by `scripts/render_er_diagram.py`). Both diagrams match the tables created by [`billing_api/app/models.py`](billing_api/app/models.py) exactly. Constraints and indexes: [`docs/er-diagram.md`](docs/er-diagram.md). The same model as Mermaid:

```mermaid
erDiagram
    SUBSCRIBERS |o--o{ USERS : "has login (ADMIN users have none)"
    SUBSCRIBERS ||--o{ USAGE_RECORDS : "generates"
    SUBSCRIBERS ||--o{ BILLS : "is billed"
    BILLS ||--o{ PAYMENTS : "is paid by"

    SUBSCRIBERS {
        varchar(20) subscriber_no PK
        varchar(100) full_name
        timestamptz created_at
    }
    USERS {
        integer id PK
        varchar(50) username UK
        varchar(100) password_hash "bcrypt"
        varchar(20) role "SUBSCRIBER or ADMIN"
        varchar(20) subscriber_no FK "NULL only for ADMIN"
    }
    USAGE_RECORDS {
        bigint id PK
        varchar(20) subscriber_no FK
        integer year
        integer month "1-12"
        varchar(10) usage_type "PHONE or INTERNET"
        integer quantity "10 minutes or 1 MB per event"
        timestamptz recorded_at
    }
    BILLS {
        integer id PK
        varchar(20) subscriber_no FK "UNIQUE with year, month"
        integer year
        integer month "1-12"
        integer phone_minutes "snapshot at calculation"
        integer internet_mb "snapshot at calculation"
        numeric phone_charge "NUMERIC(12,2)"
        numeric internet_charge "NUMERIC(12,2)"
        numeric total_amount "NUMERIC(12,2)"
        numeric paid_amount "NUMERIC(12,2), >= 0"
        varchar(20) status "UNPAID, PARTIALLY_PAID or PAID"
        timestamptz calculated_at
    }
    PAYMENTS {
        integer id PK
        integer bill_id FK
        varchar(64) transaction_id UK "duplicate protection"
        numeric amount "NUMERIC(12,2), > 0"
        varchar(50) paid_by_username
        timestamptz created_at
    }
```

## 7. Authentication & authorization

* **JWT (HS256)** from `POST /api/v1/auth/token`. Claims: `sub` (username), `role` (`SUBSCRIBER`|`ADMIN`), `subscriberNo`, `iss`, `iat`, `exp` (60 min). Passwords are stored as **bcrypt** hashes.
* **Two layers:**
  1. **Gateway (Kong `jwt` plugin):** rejects protected requests that have a missing, forged or expired token before they reach the API.
  2. **API:** validates the token again, then checks authorization.
     * Every authenticated operation (Add Usage, Calculate Bill, Query Bill Detailed, Pay Bill) is authorized per account: a `SUBSCRIBER` may use it **only for their own `subscriberNo`** (from the JWT). Any other subscriber number gives **403**.
     * `ADMIN` (back office) may use these operations for any account.
* **AI agent and private data:** the agent's REST tools **have no `subscriberNo` parameter**. The agent always uses the `subscriberNo` from the logged-in user's JWT. If a prompt says "show the bill of 5551002", the LLM has no way to request another account, and even a direct API call is blocked with 403 (tested in `test_query_bill_detailed.py::test_detailed_other_subscriber_is_403` and `agent/tests::test_rest_tools_never_accept_a_subscriber_number`).
* **Write/payment confirmation:** before `pay_bill` reaches the payment API, the agent shows **"Pay $X for subscriber N, billing period YYYY-MM?"** and continues only on an explicit `yes`. A declined confirmation never calls the API (`agent/tests::test_payment_is_not_sent_without_confirmation`). Each confirmed payment gets a unique `transactionId` (idempotency).
* Query Bill is **public** (no authentication), as the specification table requires.

## 8. API Gateway

Kong 3.9, DB-less, configured by [`gateway/kong.template.yml`](gateway/kong.template.yml). The Billing API **cannot be called directly**: in docker compose it has no host port, and in Azure it rejects every request that does not carry the gateway secret header (see *Origin protection* below).

**Gateway URL:** local `http://localhost:8000`, cloud: see §12.

| Public versioned route | Method | Upstream (billing-api) | Gateway policy |
|---|---|---|---|
| `/api/v1/auth/token` | POST | `/api/v1/auth/token` | public, rate limit 10/min per IP |
| `/api/v1/bills` (exact) | GET | `/api/v1/bills` | **public**, rate limit 60/min per IP |
| `/api/v1/bills/detailed` | GET | `/api/v1/bills/detailed` | **protected: JWT**, 60/min per user |
| `/api/v1/bills/calculate` | POST | `/api/v1/bills/calculate` | **protected: JWT**, 60/min per user |
| `/api/v1/usage` | POST | `/api/v1/usage` | **protected: JWT**, 60/min per user |
| `/api/v1/payments` | POST | `/api/v1/payments` | **protected: JWT**, 60/min per user |
| `/api/v1/docs`, `/api/v1/openapi.json`, `/health` | GET | same | public |
| `/`, `/api/v1` | GET | – (answered by Kong) | **302 redirect to the Swagger UI**, so the gateway's base URL opens the API documentation |

* **Authentication is enforced consistently.** All payment, account-detail and admin routes require a valid JWT at the gateway, and authorization happens in the API.
* **Rate limiting is keyed by identity, not only IP.** On protected routes, a `pre-function` plugin derives the key from the JWT `sub` claim, so each user has their own counter (`X-RateLimit-Remaining-Minute` header). A client cannot spoof it because the header is always overwritten, and forged tokens are rejected by the `jwt` plugin before the limit is counted. The Group 2 specification defines no numeric limits; the values above are my own documented choice.
* Every response carries `X-Request-ID` (correlation-id), `X-API-Gateway: kong` and `X-API-Version: v1`.
* **Origin protection (gateway-only access).** Kong removes any client-supplied `X-Gateway-Secret` header and adds the real secret (`request-transformer` plugin). The Billing API rejects every request without the correct value with **403 `GATEWAY_REQUIRED`** (`/health` excepted for platform probes). So even though the API container has its own hostname in Azure, it can only be used through the gateway (tested in `billing_api/tests/test_gateway_origin.py`; demonstrated as step 12 in the cloud demo).

**Example error response (protected route, no token):**
```
$ curl -i "$GATEWAY_URL/api/v1/bills/detailed?subscriberNo=5551001&month=10&year=2026"
HTTP/1.1 401 Unauthorized
X-API-Gateway: kong
{"message":"Unauthorized"}
```
Full recorded demonstrations (public route, protected route without/with/forged token, 403, payment, duplicate, 422, 404, direct-API bypass blocked): **cloud** [`docs/gateway-demo-cloud.txt`](docs/gateway-demo-cloud.txt), local [`docs/gateway-demo-local.txt`](docs/gateway-demo-local.txt). Re-run it with `GATEWAY_URL=... BILLING_API_DIRECT_URL=... ./scripts/gateway_demo.sh`.

## 9. MCP server & AI agent

### 9.1 MCP tool schema
Tool `search_billing_documentation`. Full input/output JSON schema: [`docs/mcp-tool-schema.json`](docs/mcp-tool-schema.json).

```json
{"name": "search_billing_documentation",
 "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}
```
Result (format from guide §9, plus `documentId`, `parentHeading`, `score`):
```json
{"document": "Mobile_Provider_Billing_Guide.md", "documentId": "MOB-BILLING-2026-01", "query": "extra internet cost",
 "matches": [{"section": "8.1", "heading": "What is the cost of extra internet?", "parentHeading": "8. Frequently asked questions",
              "text": "Each additional 10 GB block beyond 20 GB costs $10. ...", "score": 9.43},
             {"section": "3.2", "heading": "Additional internet blocks", "parentHeading": "3. Internet pricing", "text": "...", "score": 7.27}]}
```
Endpoint: `{MCP_URL}` = `http://localhost:8001/mcp` (Streamable HTTP, stateless, JSON responses). Health check: `/health`.
MCP clients `POST` JSON-RPC to `/mcp`. A **browser** opening `/` or `/mcp` gets a short HTML page instead: it describes the server and has a search form that sends a real MCP `tools/call` request (MCP clients are not affected; tested in `mcp_server/tests`).

### 9.2 Indexing approach ([`mcp_server/docs_index.py`](mcp_server/docs_index.py))
1. **Chunking by headings:** each `### x.y` subsection is a chunk; a `## x` section without subsections is one chunk; the preamble is chunk `0`. That gives **26 chunks**. Headings inside code blocks are ignored. Each chunk keeps its section ID, heading, parent heading and text, so answers can cite "§3.2".
2. **Tokenizing:** lowercase alphanumeric tokens, stop words removed, light plural stemming. Heading tokens are counted twice.
3. **Index:** in-memory inverted index with **BM25** scoring (k1 = 1.5, b = 0.75), built **once at server start-up** (log line `Indexed Mobile_Provider_Billing_Guide.md (MOB-BILLING-2026-01) into 26 chunks.`). Every query reuses it; the server logs show one `Indexed` line followed by many queries: [cloud](docs/mcp-server-log-cloud.txt), [local](docs/mcp-server-log-local.txt).
4. **Query expansion:** a small domain synonym table maps user words to document words (`data → internet`, `extra → additional`, `call → phone`, `part → partial`, …).
5. Returns the top **3** matches with score > 0. An unrelated query returns no matches (the agent then does not invent policy).

Embeddings or vector search are optional in the spec and are not used.

### 9.3 Three distinct retrieval tests
| Query | Top sections returned |
|---|---|
| "How much does extra internet cost?" | **8.1** What is the cost of extra internet?, **3.2** Additional internet blocks |
| "What happens with late payments?" | **6.2** Late payment reminder, **6.1** Due date, **6.3** Service restriction |
| "How can I dispute a charge on my bill?" | **8.4** How can I dispute a charge?, **7.1** Dispute window, **7.2** Information required |

* **Live logs** (official MCP client → running MCP server, `tools/list` + 3 `tools/call`): **cloud** [`docs/mcp-retrieval-demo-cloud.txt`](docs/mcp-retrieval-demo-cloud.txt), local [`docs/mcp-retrieval-demo-local.txt`](docs/mcp-retrieval-demo-local.txt). Re-run: `MCP_URL=... .venv/bin/python scripts/mcp_demo.py`.
* **Automated tests:** `mcp_server/tests/test_mcp_server.py` asserts the same three queries, also through a real in-process MCP client ↔ server session.

### 9.4 Demonstrated scenarios (tool traces)
The agent (`agent/billing_agent.py`) sends Claude the MCP tool (schema discovered from the MCP server with `list_tools`) plus three REST tools: `query_bill`, `query_bill_detailed`, `pay_bill`. Claude chooses the tools. The agent executes them and returns the results, and Claude writes the answer. Each turn prints and saves a trace (LLM selection → tool name, route, input, result → final answer) to [`docs/traces/`](docs/traces/).

Recorded with `claude-haiku-5-5` on the local stack using the **exact example questions of the assignment** (users `user1001` / subscriber 5551001 and `user1002` / 5551002, fresh demo data). Full traces with every tool input and result are in [`docs/traces/`](docs/traces/).

| # | Assignment example | Question | Tools chosen by the LLM → route | Trace |
|---|---|---|---|---|
| 1 | → MCP | "How much does extra internet cost?" | `search_billing_documentation` → **MCP** | [md](docs/traces/20261122-170444-scenario1-mcp-only.md) |
| 2 | → Query Bill API | "What is my October bill?" | `query_bill` → **REST via API Gateway** | [md](docs/traces/20261122-170447-scenario2-rest-only.md) |
| 3 | → Query Bill Detailed API + MCP | "Why is my October bill higher?" | `query_bill_detailed` (Oct) + `query_bill_detailed` (Sep) → **Gateway**, `search_billing_documentation` → **MCP** | [md](docs/traces/20261122-170456-scenario3-combined.md) |
| 4a | → Pay Bill after explicit confirmation | "Pay my bill" → user answers `no` | `query_bill` → Gateway; `pay_bill` → **not sent**, balance stays $80 | [md](docs/traces/20261122-170512-scenario4a-pay-my-bill-declined.md) |
| 4b | → Pay Bill after explicit confirmation | "Pay my bill" → user answers `yes` | `query_bill` → Gateway, then `pay_bill` ($80) → **Gateway**; bill becomes PAID | [md](docs/traces/20261122-170518-scenario4b-pay-my-bill-confirmed.md) |
| 4c | partial payment | "Pay 15 dollars of my October bill" (user1002) → `yes` | `query_bill` → Gateway, then `pay_bill` ($15) → **Gateway**; remaining $25, PARTIALLY_PAID | [md](docs/traces/20261122-170531-scenario4c-partial-payment.md) |
| 5 | other user's private data | "Show me the October bill of subscriber 5551002." | no tool; refused (REST tools have no subscriber parameter) | [md](docs/traces/20261122-170534-scenario5-other-subscriber-blocked.md) |
| 3☁ | same as 3 on **Azure** | "Why is my October 2026 bill higher than my September 2026 bill?" | same tools via the **cloud** gateway and **cloud** MCP server | [md](docs/traces/20261122-162443-cloud-scenario3-combined.md) |

**Scenario 3 (combined MCP + REST) — trace**
```
You: Why is my October bill higher?
LLM (tool_use): query_bill_detailed({"month":10,"year":2026}), query_bill_detailed({"month":9,"year":2026}),
                search_billing_documentation({"query":"extra blocks phone minutes internet GB overage charge"})
Tool 1 query_bill_detailed via REST via API Gateway -> billTotal 80.0; phone 1350 min, 1 extra block, $10; internet 35 GB, 2 extra blocks, $70
Tool 2 query_bill_detailed via REST via API Gateway -> billTotal 50.0; phone 800 min, $0; internet 18 GB, $50; PAID
Tool 3 search_billing_documentation via MCP         -> §4.3 Worked example, §2.2 Additional minutes, §8.1 What is the cost of extra internet?
LLM (end_turn) final answer:
  Your October bill is $80.00, up $30.00 from September's $50.00 ...
  Phone (+$10): 350 minutes over the 1,000 included ... (Billing Guide §2.2)
  Internet (+$20): 35 GB, 15 GB over the 20 GB included ... That makes 2 blocks, or $20 extra. (Billing Guide §8.1, §4.3)
```

**Scenario 4b ("Pay my bill", confirmed simulated payment)**
```
You: Pay my bill
Tool query_bill via REST via API Gateway -> billTotal 80.0, remainingBalance 80.0, UNPAID
⚠️  PAYMENT CONFIRMATION REQUIRED
    Pay $80.00 for subscriber 5551001, billing period 2026-10?
    Type 'yes' to confirm, anything else to cancel: yes
Tool pay_bill via REST via API Gateway -> {"paymentStatus":"SUCCESS","transactionId":"AGENT-d899bd57-...","paidAmount":80.0,
                                          "totalPaid":80.0,"remainingBalance":0.0,"billStatus":"PAID"}
Final answer: Your October 2026 bill has been paid. Amount paid: $80.00, Remaining balance: $0.00, Bill status: PAID ...
```
Total LLM cost of all recorded scenarios: well under **$0.01** (token counts and cost are printed in each trace).

## 10. Run locally

Requirements: Docker Desktop, Python 3.12, an Anthropic API key (only for the live agent).

```bash
# 1. Start PostgreSQL + Billing API + MCP server + Kong gateway (demo data is seeded automatically)
docker compose up --build -d
curl http://localhost:8000/health                      # through the gateway
open http://localhost:8000/api/v1/docs                 # Swagger UI

# 2. Python environment for tests and the agent
python3.12 -m venv .venv
.venv/bin/pip install -r billing_api/requirements-dev.txt -r mcp_server/requirements-dev.txt -r agent/requirements-dev.txt

# 3. Chat with the agent (put ANTHROPIC_API_KEY in .env, see .env.example)
.venv/bin/python agent/cli.py --user user1001 --password 'Pass1001!'

# Reset the database to the original demo data
docker compose down -v && docker compose up -d
```

**Windows:** run the commands in **Git Bash** (installed with Git for Windows) with Docker Desktop running. Three differences: create the environment with `py -3.12 -m venv .venv`, use `.venv/Scripts/` instead of `.venv/bin/` (for example `.venv/Scripts/pip`, `.venv/Scripts/python agent/cli.py ...`), and open the Swagger UI in the browser instead of `open`. `./scripts/run_tests.sh` and `./scripts/gateway_demo.sh` find the Windows virtualenv automatically, and `.gitattributes` keeps LF line endings so the scripts and the gateway container work after a Windows checkout. No local build is needed to check the system: the cloud URLs in §12 work from any OS and browser.

## 11. Unit tests

**103 automated tests** (pytest). They need **no cloud, no gateway and no LLM**.

| Suite | Tests | Covers |
|---|---|---|
| `billing_api/tests` | 76 | every REST operation: success + failure/edge cases (Add Usage, Calculate Bill, Query Bill, Query Bill Detailed, Pay Bill, Login), pricing rules (all examples of guide §2–4), JWT (missing/tampered/expired), authorization (403), paging, validation, duplicate transaction, amount > balance, gateway-only access (origin protection) |
| `mcp_server/tests` | 16 | chunking, tokenizer, 3 distinct retrieval queries, result format, MCP client↔server `list_tools`/`call_tool`, browser info page + JSON-RPC `tools/call` over HTTP |
| `agent/tests` | 11 | tool routing (MCP-only, REST-only, combined) with a scripted fake LLM, payment confirmation gate, no `subscriberNo` in REST tools, API errors returned as tool errors, refusal and loop limits |

**Every REST API operation has success and failure/edge-case tests** (`billing_api/tests`):

| Operation | Success tests | Failure / edge-case tests |
|---|---|---|
| Add Usage | `test_add_phone_usage_adds_10_minutes`, `test_add_internet_usage_adds_1_mb`, `test_repeated_events_accumulate`, `test_spec_spelling_phone_and_internet_is_accepted`, `test_subscriber_can_add_usage_to_own_account` | `test_add_usage_unknown_subscriber_is_404`, `test_add_usage_invalid_type_and_month_is_422`, `test_subscriber_cannot_add_usage_to_another_account`, `test_add_usage_requires_token` |
| Calculate Bill | `test_calculate_worked_example_is_80`, `test_calculate_with_no_usage_is_internet_base_50`, `test_partial_blocks_are_charged_as_full_blocks`, `test_usage_via_api_is_included`, `test_recalculation_updates_total_and_keeps_payments`, `test_subscriber_can_calculate_own_bill` | `test_calculate_unknown_subscriber_is_404`, `test_calculate_invalid_month_is_422`, `test_calculate_other_account_is_403_and_requires_token` |
| Query Bill | `test_query_bill_returns_total_paid_remaining_status`, `test_query_bill_reflects_partial_payment` | `test_query_bill_not_calculated_is_404`, `test_query_bill_unknown_subscriber_is_404`, `test_query_bill_missing_or_invalid_params_is_422` |
| Query Bill Detailed | `test_detailed_breakdown`, `test_detailed_paging`, `test_detailed_admin_can_read_any_account`, `test_detailed_flags_usage_added_after_calculation` | `test_detailed_page_beyond_last_is_empty`, `test_detailed_invalid_paging_is_422`, `test_detailed_other_subscriber_is_403`, `test_detailed_requires_token`, `test_detailed_bill_not_calculated_is_404` |
| Pay Bill | `test_partial_payment`, `test_full_payment_in_two_steps_marks_paid`, `test_decimal_amounts_are_exact` | `test_duplicate_transaction_id_is_rejected`, `test_amount_exceeding_balance_is_rejected`, `test_paying_a_fully_paid_bill_is_409`, `test_zero_negative_or_too_precise_amount_is_422`, `test_missing_transaction_id_is_422`, `test_paying_another_subscribers_bill_is_403`, `test_pay_requires_token`, `test_pay_bill_not_calculated_is_404` |
| Login (`/auth/token`) | `test_login_success_returns_jwt`, `test_login_token_works_on_protected_route` | `test_login_wrong_password_is_401`, `test_login_unknown_user_is_401`, `test_login_missing_fields_is_422`, `test_tampered_token_is_401`, `test_expired_token_is_401`, `test_protected_route_without_token_is_401` |
| Business rules (pricing) | `test_phone_charge_examples`, `test_internet_charge_examples`, `test_worked_example_total_is_80`, `test_due_date_is_15_days_after_month_end`, `test_mb_to_gb_uses_1000_mb_per_gb` | `test_negative_usage_is_rejected` |
| Gateway-only access | `test_request_with_gateway_header_is_accepted`, `test_health_is_open_for_platform_probes` | `test_direct_request_without_gateway_header_is_403`, `test_wrong_gateway_header_is_403` |

**How to run** (after the Python environment of §10 step 2):
```bash
./scripts/run_tests.sh                 # runs all suites, saves output to docs/test-results.txt
cd billing_api && ../.venv/bin/pytest  # a single suite
```
By default the API tests use a fresh **in-memory SQLite database per test** for speed and isolation. This is a test fixture only; the application uses PostgreSQL. The same tests run against PostgreSQL:
```bash
docker compose exec postgres psql -U billing -c "CREATE DATABASE billing_test;"
cd billing_api && TEST_DATABASE_URL=postgresql+psycopg://billing:billing@localhost:5433/billing_test ../.venv/bin/pytest
```
**Evidence:** [`docs/test-results.txt`](docs/test-results.txt): 76 + 16 + 11 = **103 passed**. The API suite also passes against PostgreSQL 16: [`docs/test-results-postgresql.txt`](docs/test-results-postgresql.txt) (76 passed).

```
$ ./scripts/run_tests.sh
================ billing_api ================
tests/test_add_usage.py::test_add_phone_usage_adds_10_minutes PASSED
...
tests/test_pay_bill.py::test_duplicate_transaction_id_is_rejected PASSED
tests/test_pay_bill.py::test_amount_exceeding_balance_is_rejected PASSED
...
============================== 76 passed in 8.01s ==============================
================ mcp_server ================
============================== 16 passed in 0.38s ==============================
================ agent ================
============================== 11 passed in 0.02s ==============================
```

## 12. Cloud deployment

Azure (all components): **Azure Container Apps** (Consumption) for `gateway`, `billing-api` and `mcp-server`, **Azure Container Registry** for the images, and **Azure Database for PostgreSQL Flexible Server** 16 (Burstable B1ms) as the server database. `billing-api` accepts only requests forwarded by the gateway (origin protection, §8).

```bash
az login
SUBSCRIPTION=<subscription-id> ./infra/azure-deploy.sh   # builds linux/amd64 images, creates/updates all resources, prints the URLs
```
The script is re-runnable (it updates existing apps with a new image tag). Generated secrets (DB password, JWT secret, gateway secret) are stored in the git-ignored `infra/.azure-deploy.env`.

| Component | URL |
|---|---|
| API Gateway (base URL) | **https://gateway.happystone-4bc228e1.germanywestcentral.azurecontainerapps.io** (region Germany West Central; opening it in a browser redirects to the Swagger UI) |
| Swagger UI | https://gateway.happystone-4bc228e1.germanywestcentral.azurecontainerapps.io/api/v1/docs |
| MCP server | https://mcp-server.happystone-4bc228e1.germanywestcentral.azurecontainerapps.io/mcp (health: `/health`; opening it in a browser shows a description page with a search form) |
| Billing API | `https://billing-api.happystone-4bc228e1.germanywestcentral.azurecontainerapps.io`: direct calls return **403 GATEWAY_REQUIRED**, use the gateway |
| PostgreSQL | `se4458bill11826-db.postgres.database.azure.com`, database `billing` (region Spain Central; credentials are not published) |

Use the agent against the cloud:
```bash
GATEWAY_URL=https://gateway.happystone-4bc228e1.germanywestcentral.azurecontainerapps.io \
MCP_URL=https://mcp-server.happystone-4bc228e1.germanywestcentral.azurecontainerapps.io/mcp \
.venv/bin/python agent/cli.py --user user1001 --password 'Pass1001!'
```
Cloud evidence: [gateway demo](docs/gateway-demo-cloud.txt), [agent combined scenario trace](docs/traces/20261122-162443-cloud-scenario3-combined.md).
The cloud database contains exactly the demo data of §13. Demo actions (payments, usage) change it; reset it to the documented state with `./infra/reset-cloud-data.sh` (opens the PostgreSQL firewall to your IP only for the duration of the reset).
Clean up: `az group delete -n se4458-billing-rg --yes`.

## 13. Test data & reproduction steps for the instructor

Seeded automatically on first start ([`billing_api/app/seed.py`](billing_api/app/seed.py)). Usage is stored as real Add Usage events (10 min / 1 MB each).

| User / password | Role | Subscriber | Data |
|---|---|---|---|
| `admin` / `Admin123!` | ADMIN | – | back office: all operations for any account |
| `user1001` / `Pass1001!` | SUBSCRIBER | 5551001 | Sep 2026: 800 min, 18 GB → **$50, PAID**. Oct 2026: 1,350 min, 35 GB → **$80, UNPAID** |
| `user1002` / `Pass1002!` | SUBSCRIBER | 5551002 | Oct 2026: 2,500 min, 12 GB → **$70**, $30 paid → **PARTIALLY_PAID** |
| `user1003` / `Pass1003!` | SUBSCRIBER | 5551003 | Oct 2026: 1,010 min, 20,001 MB recorded, **bill not calculated yet** (admin demo: Calculate Bill → $70) |

**Steps:**
1. `docker compose up --build -d` (or use the cloud URLs in §12), then create the Python environment (§10 step 2). On Windows, see the note at the end of §10.
2. Unit tests: `./scripts/run_tests.sh` (no Docker, cloud or API key needed for this step).
3. Gateway demo: `GATEWAY_URL=http://localhost:8000 ./scripts/gateway_demo.sh`.
4. Swagger UI: open `/api/v1/docs`, call `POST /api/v1/auth/token`, click **Authorize**, paste the token, and try the protected operations.
5. Agent (needs `ANTHROPIC_API_KEY` in `.env`, see `.env.example`): `.venv/bin/python agent/cli.py --user user1001 --password 'Pass1001!'` and ask the questions in §9.4. For the payment, answer `yes` to the confirmation prompt.
6. MCP retrieval demo: `.venv/bin/python scripts/mcp_demo.py` (local) or with `MCP_URL=<cloud MCP URL>`.
7. Reset data: `docker compose down -v && docker compose up -d` (cloud: `./infra/reset-cloud-data.sh`).

## 14. Demo video

Video file in this repository: `docs/demo-video.mp4` (about 6 minutes, no audio, recorded against the Azure deployment). GitHub does not preview a file this large, so use the direct download link: [download demo-video.mp4](https://github.com/deensza/se4458-billing-assistant/raw/main/docs/demo-video.mp4).

In order, it shows:
1. This README: architecture diagram (§1), ER diagram (§6), gateway routes (§8) and cloud URLs (§12).
2. Unit tests run with `./scripts/run_tests.sh`: 76 + 16 + 11 passed (§11).
3. Three distinct MCP retrieval tests with `scripts/mcp_demo.py` against the cloud MCP server (§9.3).
4. The MCP server's browser page answering "Can I pay only part of my bill?" (§8.3, §5.1, §5.3).
5. The gateway demo (`scripts/gateway_demo.sh`): public route, protected route rejected without a token (401) and with a forged token (401), login, protected route with a token (200), access to another subscriber blocked (403), a $30 simulated payment (201), duplicate transaction ID (409), amount above the balance (422), unknown route (404) and a direct call that bypasses the gateway (403 `GATEWAY_REQUIRED`).
6. Swagger UI through the gateway: login, **Authorize**, then the protected `GET /api/v1/bills/detailed`.
7. The AI agent (`agent/cli.py`, user1001): MCP-only ("How much does extra internet cost?"), API-only ("What is my October bill?"), combined ("Why is my October bill higher?"), then "Pay my bill" with the confirmation prompt answered `yes`, and a final check that the bill is PAID.

## 15. Assumptions

**Billing and rounding**
* Partially used extra blocks are charged as full blocks (guide §2.2, §3.2). Blocks are computed with integer arithmetic on minutes and MB, so there is no floating-point rounding. Example: 20,001 MB → 1 extra block → $60.
* 1 GB = 1,000 MB (spec). `usageGb` is shown with 3 decimals.
* Money is `NUMERIC(12,2)`. Payment amounts may have at most 2 decimals.
* The "Apr 2025 75$" in the specification table is read as an **illustration of the response format only**. Under the given pricing every total is $50 + multiples of $10, so $75 cannot occur.
* Internet base price ($50) is charged even with zero usage (guide §3.1), so Calculate Bill for a month without usage gives $50.

**Operations**
* Add Usage always adds exactly one event (10 min or 1 MB), as specified. Large realistic demo volumes (for example 35 GB = 35,000 events) are loaded by the seed script as the same event rows.
* Calculate Bill can be called again: it recalculates from all usage recorded so far and keeps payments. If usage is added after a calculation, Query Bill Detailed reports `recalculationNeeded: true`.
* Query Bill / Pay Bill / Query Bill Detailed for a month that was not calculated → 404 `BILL_NOT_FOUND`. The agent never presents an estimate as a stored bill (guide §4.4).
* Query Bill Detailed pages the month's **usage records** (`page`, `pageSize`). A page past the end returns an empty list.
* Duplicate transaction ID → 409 even if the amount differs. The first payment is kept and the balance is unchanged.
* Overpayment is not allowed. Paying a fully paid bill → 409.

**API errors**
* Every API error uses one JSON format: `{"error": {"code", "message", "details"}}` (full list of codes in §4). Validation problems return 422 `VALIDATION_ERROR` with the failing fields in `details`.
* 401 = not authenticated (missing/invalid/expired token or wrong login); 403 = authenticated but not allowed (another subscriber's account) or the request bypassed the gateway (`GATEWAY_REQUIRED`); 404 = unknown subscriber or bill not calculated yet; 409 = duplicate transaction ID or bill already fully paid; 422 = invalid input or amount larger than the remaining balance.
* Errors produced by the gateway itself (401 before reaching the API, 404 unknown route, 429 rate limit) use Kong's `{"message": "..."}` format.
* For the agent, API errors are returned to the LLM as tool errors (`is_error: true`) so it can explain them (e.g. "the bill has not been calculated yet") instead of inventing values.

**Identity and security**
* Add Usage and Calculate Bill require authentication (as specified). A subscriber may call them for their own account; the ADMIN role may call them for any account.
* Subscribers can read details and pay **only their own** account. Admins can access every account.
* Query Bill is public as the specification requires. It returns only totals and status (no usage details).
* The AI agent is for subscriber accounts; an admin login is rejected by the CLI.
* Demo passwords are test values for this fictitious system.

**Policy interpretation**
* Disputes and service restriction are explained from the guide only. There is no Dispute or service-status API (guide §7.2, §6.3).
* "This month" for the agent = current calendar month. Bills are normally calculated after the month ends.
* When the user names no billing period ("my bill", "Pay my bill"), the agent uses the most recent completed month. For "Pay my bill" without an amount it proposes the full remaining balance; the user must still confirm subscriber, period and amount (guide §5.2).

**Gateway and deployment**
* Rate limits (10/min login, 60/min public Query Bill per IP, 60/min per user on protected routes) are my own values, because Group 2 has no stated limits.
* The MCP server has no authentication: it serves only the public, fictitious policy document and no private data. DNS-rebinding host checks are disabled because it runs behind a cloud ingress hostname.
* The database schema is created automatically at start-up (`create_all`); no migration tool is used.
* Cloud: Azure. The "Azure for Students" subscription only allows some regions, and PostgreSQL provisioning is restricted in Germany West Central, so the database runs in **Spain Central** while the container apps run in **Germany West Central**.
* In the Container Apps Consumption environment (no VNet) the apps resolve each other through public DNS, so an internal-only ingress was not reachable from Kong. Gateway-only access is therefore enforced with a shared secret header (origin protection, §8) instead of network isolation.
* Payments are simulated; **no real money or card processing**.

## 16. LLM cost & low-cost testing

* Default model **`claude-haiku-5-5`**: $0.10 per 1M input tokens and $0.50 per 1M output tokens (Anthropic list price for prompts up to 100K tokens; every prompt here is far below that). A typical question uses 2–3 LLM calls of about 3–4K input tokens each, which is **about $0.001 per question**. All demo scenarios together cost well under $0.05. The CLI prints the token usage and estimated cost of every turn.
* `AGENT_MODEL` can switch to a larger model (e.g. `claude-sonnet-5-5`) without code changes.
* **No LLM is needed for testing:** all 103 unit tests use a scripted fake LLM / in-process MCP, and the REST API and gateway can be tested fully with Swagger, curl or `scripts/gateway_demo.sh`.
