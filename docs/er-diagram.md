# ER / Data Model — Billing Database (PostgreSQL)

```mermaid
erDiagram
    SUBSCRIBERS ||--o{ USERS : "has login (ADMIN users have none)"
    SUBSCRIBERS ||--o{ USAGE_RECORDS : "generates"
    SUBSCRIBERS ||--o{ BILLS : "is billed"
    BILLS ||--o{ PAYMENTS : "is paid by"

    SUBSCRIBERS {
        varchar(20) subscriber_no PK
        varchar(100) full_name
        timestamptz created_at
    }
    USERS {
        int id PK
        varchar(50) username UK
        varchar(100) password_hash "bcrypt"
        varchar(20) role "SUBSCRIBER | ADMIN"
        varchar(20) subscriber_no FK "NULL only for ADMIN"
    }
    USAGE_RECORDS {
        bigint id PK
        varchar(20) subscriber_no FK
        int year
        int month "1-12"
        varchar(10) usage_type "PHONE | INTERNET"
        int quantity "10 minutes or 1 MB per event"
        timestamptz recorded_at
    }
    BILLS {
        int id PK
        varchar(20) subscriber_no FK
        int year
        int month "1-12"
        int phone_minutes "snapshot at calculation"
        int internet_mb "snapshot at calculation"
        numeric(12_2) phone_charge
        numeric(12_2) internet_charge
        numeric(12_2) total_amount
        numeric(12_2) paid_amount
        varchar(20) status "UNPAID | PARTIALLY_PAID | PAID"
        timestamptz calculated_at
    }
    PAYMENTS {
        int id PK
        int bill_id FK
        varchar(64) transaction_id UK "duplicate protection"
        numeric(12_2) amount "> 0"
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
