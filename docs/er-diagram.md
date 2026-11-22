# ER / Data Model — Billing Database (PostgreSQL)

Image version: [`er-diagram.png`](er-diagram.png) / [`er-diagram.svg`](er-diagram.svg). Both diagrams show exactly the tables created by [`billing_api/app/models.py`](../billing_api/app/models.py).

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

## Constraints and indexes

| Table | Constraint / index | Purpose |
|---|---|---|
| `bills` | `UNIQUE (subscriber_no, year, month)` | One stored bill per subscriber per month; Calculate Bill updates it |
| `payments` | `UNIQUE (transaction_id)` | Duplicate transaction IDs are rejected even under concurrent requests |
| `payments` | `CHECK (amount > 0)` | No zero/negative payments |
| `bills` | `CHECK (paid_amount >= 0)`, `CHECK (month BETWEEN 1 AND 12)` | Data integrity |
| `usage_records` | `INDEX (subscriber_no, year, month)` | Fast aggregation for Calculate Bill and paging for Query Bill Detailed |
| `usage_records` | `CHECK (quantity > 0)`, `CHECK (month BETWEEN 1 AND 12)` | Data integrity |
| `users` | `UNIQUE (username)`, `CHECK (role = 'ADMIN' OR subscriber_no IS NOT NULL)` | Each subscriber login is linked to exactly one account |

Money is stored as `NUMERIC(12,2)` (exact decimal, never floating point). Usage is stored as integer
minutes and MB, so all bill calculations are exact integer arithmetic.
