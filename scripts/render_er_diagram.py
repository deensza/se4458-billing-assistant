"""Renders the ER diagram of the billing database to docs/er-diagram.svg (no dependencies).

    .venv/bin/python scripts/render_er_diagram.py
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "docs" / "er-diagram.svg"

W, HEAD, ROW = 330, 34, 24
ENTITIES = {
    "users": (40, 60, [
        ("PK", "id", "INTEGER"),
        ("UK", "username", "VARCHAR(50)"),
        ("", "password_hash", "VARCHAR(100) bcrypt"),
        ("", "role", "SUBSCRIBER / ADMIN"),
        ("FK", "subscriber_no", "VARCHAR(20) NULL"),
    ]),
    "subscribers": (460, 250, [
        ("PK", "subscriber_no", "VARCHAR(20)"),
        ("", "full_name", "VARCHAR(100)"),
        ("", "created_at", "TIMESTAMPTZ"),
    ]),
    "usage_records": (40, 450, [
        ("PK", "id", "BIGINT"),
        ("FK", "subscriber_no", "VARCHAR(20)"),
        ("", "year", "INTEGER"),
        ("", "month", "INTEGER 1-12"),
        ("", "usage_type", "PHONE / INTERNET"),
        ("", "quantity", "INT (10 min or 1 MB)"),
        ("", "recorded_at", "TIMESTAMPTZ"),
    ]),
    "bills": (880, 60, [
        ("PK", "id", "INTEGER"),
        ("FK", "subscriber_no", "VARCHAR(20)"),
        ("", "year / month", "INTEGER (UNIQUE w/ sub.)"),
        ("", "phone_minutes", "INTEGER"),
        ("", "internet_mb", "INTEGER"),
        ("", "phone_charge", "NUMERIC(12,2)"),
        ("", "internet_charge", "NUMERIC(12,2)"),
        ("", "total_amount", "NUMERIC(12,2)"),
        ("", "paid_amount", "NUMERIC(12,2)"),
        ("", "status", "UNPAID / PARTIALLY_PAID / PAID"),
        ("", "calculated_at", "TIMESTAMPTZ"),
    ]),
    "payments": (880, 450, [
        ("PK", "id", "INTEGER"),
        ("FK", "bill_id", "INTEGER"),
        ("UK", "transaction_id", "VARCHAR(64)"),
        ("", "amount", "NUMERIC(12,2) > 0"),
        ("", "paid_by_username", "VARCHAR(50)"),
        ("", "created_at", "TIMESTAMPTZ"),
    ]),
}
# (parent, child, label, parent side, child side)
RELATIONS = [
    ("subscribers", "users", "has login", "left", "right"),
    ("subscribers", "usage_records", "generates", "left", "right"),
    ("subscribers", "bills", "is billed", "right", "left"),
    ("bills", "payments", "is paid by", "bottom", "top"),
]


def box(name):
    x, y, cols = ENTITIES[name]
    return x, y, W, HEAD + ROW * len(cols)


def anchor(name, side):
    x, y, w, h = box(name)
    return {"left": (x, y + h / 2), "right": (x + w, y + h / 2), "top": (x + w / 2, y), "bottom": (x + w / 2, y + h)}[side]


def main() -> None:
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1260" height="680" viewBox="0 0 1260 680" '
        'font-family="Helvetica, Arial, sans-serif">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="630" y="32" text-anchor="middle" font-size="20" font-weight="bold" fill="#1f2937">'
        "Billing Database - ER Diagram (PostgreSQL)</text>",
    ]
    for parent, child, label, ps, cs in RELATIONS:
        (x1, y1), (x2, y2) = anchor(parent, ps), anchor(child, cs)
        if ps in ("left", "right"):
            mx = (x1 + x2) / 2
            path = f"M{x1},{y1} L{mx},{y1} L{mx},{y2} L{x2},{y2}"
            if ps == "left":
                anchor_, lx, ly = "start", mx + 6, (y1 + y2) / 2
            else:  # narrow gap: put the label below the lower horizontal segment
                anchor_, lx, ly = "middle", mx, max(y1, y2) + 20
        else:
            path = f"M{x1},{y1} L{x2},{y2}"
            anchor_ = "start"
            lx, ly = x1 + 8, (y1 + y2) / 2 + 4
        parts.append(f'<path d="{path}" fill="none" stroke="#475569" stroke-width="1.6"/>')
        parts.append(
            f'<text x="{lx}" y="{ly}" text-anchor="{anchor_}" font-size="13" fill="#334155" font-style="italic">{label}</text>'
        )
        dx = {"left": -14, "right": 14, "top": -16, "bottom": -16}
        dy = {"left": -6, "right": -6, "top": -6, "bottom": 18}
        parts.append(f'<text x="{x1 + dx[ps] - 4}" y="{y1 + dy[ps]}" font-size="13" font-weight="bold" fill="#0f766e">1</text>')
        parts.append(f'<text x="{x2 + dx[cs] - (24 if cs == "top" else 10)}" y="{y2 + dy[cs]}" font-size="13" font-weight="bold" fill="#0f766e">0..*</text>')
    for name, (x, y, cols) in ENTITIES.items():
        _, _, w, h = box(name)
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#f8fafc" stroke="#334155" stroke-width="1.5"/>')
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{HEAD}" rx="6" fill="#0f766e"/>')
        parts.append(f'<rect x="{x}" y="{y + HEAD - 6}" width="{w}" height="6" fill="#0f766e"/>')
        parts.append(f'<text x="{x + w / 2}" y="{y + 22}" text-anchor="middle" font-size="15" font-weight="bold" fill="#ffffff">{name}</text>')
        for i, (key, col, typ) in enumerate(cols):
            ry = y + HEAD + ROW * i + 17
            if i:
                parts.append(f'<line x1="{x}" y1="{ry - 17}" x2="{x + w}" y2="{ry - 17}" stroke="#e2e8f0"/>')
            parts.append(f'<text x="{x + 10}" y="{ry}" font-size="11" font-weight="bold" fill="#b45309">{key}</text>')
            weight = "bold" if key == "PK" else "normal"
            parts.append(f'<text x="{x + 38}" y="{ry}" font-size="13" font-weight="{weight}" fill="#111827">{escape(col)}</text>')
            parts.append(f'<text x="{x + w - 10}" y="{ry}" text-anchor="end" font-size="12" fill="#475569">{escape(typ)}</text>')
    parts.append(
        '<text x="630" y="665" text-anchor="middle" font-size="12" fill="#64748b">'
        "PK primary key · FK foreign key · UK unique · bills UNIQUE(subscriber_no, year, month) · "
        "payments.transaction_id UNIQUE (duplicate protection)</text>"
    )
    parts.append("</svg>")
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
