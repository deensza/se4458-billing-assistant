"""Renders the ER diagram of the billing database to docs/er-diagram.svg (no dependencies).

    .venv/bin/python scripts/render_er_diagram.py
    rsvg-convert -z 1.3 docs/er-diagram.svg -o docs/er-diagram.png   # PNG for the README
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "docs" / "er-diagram.svg"

W, HEAD, ROW = 370, 34, 24
CANVAS_W, CANVAS_H = 1370, 720
ENTITIES = {
    "users": (40, 60, [
        ("PK", "id", "INTEGER"),
        ("UK", "username", "VARCHAR(50)"),
        ("", "password_hash", "VARCHAR(100) (bcrypt)"),
        ("", "role", "VARCHAR(20) SUBSCRIBER / ADMIN"),
        ("FK", "subscriber_no", "VARCHAR(20) NULL (ADMIN)"),
    ]),
    "subscribers": (500, 260, [
        ("PK", "subscriber_no", "VARCHAR(20)"),
        ("", "full_name", "VARCHAR(100)"),
        ("", "created_at", "TIMESTAMPTZ"),
    ]),
    "usage_records": (40, 470, [
        ("PK", "id", "BIGINT"),
        ("FK", "subscriber_no", "VARCHAR(20)"),
        ("", "year", "INTEGER"),
        ("", "month", "INTEGER (1-12)"),
        ("", "usage_type", "VARCHAR(10) PHONE / INTERNET"),
        ("", "quantity", "INTEGER (10 min or 1 MB)"),
        ("", "recorded_at", "TIMESTAMPTZ"),
    ]),
    "bills": (960, 60, [
        ("PK", "id", "INTEGER"),
        ("FK", "subscriber_no", "VARCHAR(20)"),
        ("", "year", "INTEGER"),
        ("", "month", "INTEGER (1-12)"),
        ("", "phone_minutes", "INTEGER"),
        ("", "internet_mb", "INTEGER"),
        ("", "phone_charge", "NUMERIC(12,2)"),
        ("", "internet_charge", "NUMERIC(12,2)"),
        ("", "total_amount", "NUMERIC(12,2)"),
        ("", "paid_amount", "NUMERIC(12,2) (>= 0)"),
        ("", "status", "VARCHAR(20) UNPAID / PARTIALLY_PAID / PAID"),
        ("", "calculated_at", "TIMESTAMPTZ"),
    ]),
    "payments": (960, 470, [
        ("PK", "id", "INTEGER"),
        ("FK", "bill_id", "INTEGER"),
        ("UK", "transaction_id", "VARCHAR(64)"),
        ("", "amount", "NUMERIC(12,2) (> 0)"),
        ("", "paid_by_username", "VARCHAR(50)"),
        ("", "created_at", "TIMESTAMPTZ"),
    ]),
}
# (parent, child, label, parent side, parent anchor fraction, child side,
#  parent multiplicity, child multiplicity, x of the vertical segment for side connections)
RELATIONS = [
    ("subscribers", "users", "has login", "left", 0.4, "right", "0..1", "0..*", 445),
    ("subscribers", "usage_records", "generates", "left", 0.75, "right", "1", "0..*", 465),
    ("subscribers", "bills", "is billed", "right", 0.5, "left", "1", "0..*", 915),
    ("bills", "payments", "is paid by", "bottom", 0.5, "top", "1", "0..*", None),
]


def box(name):
    x, y, cols = ENTITIES[name]
    return x, y, W, HEAD + ROW * len(cols)


def anchor(name, side, frac=0.5):
    x, y, w, h = box(name)
    return {"left": (x, y + h * frac), "right": (x + w, y + h * frac),
            "top": (x + w * frac, y), "bottom": (x + w * frac, y + h)}[side]


def multiplicity(x, y, side, text):
    """Multiplicity label next to the end of a connector, outside the entity box."""
    if side == "left":
        return f'<text x="{x - 6}" y="{y - 6}" text-anchor="end" font-size="13" font-weight="bold" fill="#0f766e">{text}</text>'
    if side == "right":
        return f'<text x="{x + 6}" y="{y - 6}" font-size="13" font-weight="bold" fill="#0f766e">{text}</text>'
    dy = -6 if side == "top" else 18
    return f'<text x="{x + 8}" y="{y + dy}" font-size="13" font-weight="bold" fill="#0f766e">{text}</text>'


def main() -> None:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_W}" height="{CANVAS_H}" '
        f'viewBox="0 0 {CANVAS_W} {CANVAS_H}" font-family="Helvetica, Arial, sans-serif">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{CANVAS_W / 2}" y="32" text-anchor="middle" font-size="20" font-weight="bold" fill="#1f2937">'
        "Billing Database - ER Diagram (PostgreSQL)</text>",
    ]
    for parent, child, label, ps, frac, cs, pm, cm, mx in RELATIONS:
        (x1, y1), (x2, y2) = anchor(parent, ps, frac), anchor(child, cs)
        if ps in ("left", "right"):
            path = f"M{x1},{y1} L{mx},{y1} L{mx},{y2} L{x2},{y2}"
            if ps == "left":
                anchor_, lx, ly = "start", mx + 6, (y1 + y2) / 2
            else:  # narrow gap: put the label below the lower horizontal segment
                anchor_, lx, ly = "middle", mx, max(y1, y2) + 20
        else:
            path = f"M{x1},{y1} L{x2},{y2}"
            anchor_, lx, ly = "start", x1 + 8, (y1 + y2) / 2 + 4
        parts.append(f'<path d="{path}" fill="none" stroke="#475569" stroke-width="1.6"/>')
        parts.append(
            f'<text x="{lx}" y="{ly}" text-anchor="{anchor_}" font-size="13" fill="#334155" font-style="italic">{label}</text>'
        )
        parts.append(multiplicity(x1, y1, ps, pm))
        parts.append(multiplicity(x2, y2, cs, cm))
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
        f'<text x="{CANVAS_W / 2}" y="{CANVAS_H - 14}" text-anchor="middle" font-size="12" fill="#64748b">'
        "PK primary key · FK foreign key · UK unique · bills UNIQUE(subscriber_no, year, month) · "
        "payments.transaction_id UNIQUE (duplicate protection) · users.subscriber_no is NULL only for ADMIN</text>"
    )
    parts.append("</svg>")
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
