"""Generate synthetic Indian GST invoices (PNG) with exact ground-truth labels (JSON).

Real invoices can't be shared publicly, and hand-labelling is slow; synthetic data
gives a reproducible benchmark. Half are "clean scans", half are "phone photos"
(slight rotation, blur and noise) to measure how OCR quality affects accuracy.

    python -m evaluation.generate_samples --count 20 --out evaluation/data/synthetic
"""

import argparse
import json
import random
import string
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.utils.gstin import gstin_checksum

VENDORS = [
    "Sharma Steel Distributors",
    "Gupta Electricals",
    "Patel Packaging Co",
    "Reddy Hardware Mart",
    "Mehta Textiles",
    "Iyer Office Supplies",
]
ITEMS = [
    ("TMT Steel Bar 12mm", "7214"),
    ("Copper Wire 2.5mm", "7408"),
    ("Corrugated Box", "4819"),
    ("LED Panel 18W", "9405"),
    ("Cotton Fabric Roll", "5208"),
    ("A4 Paper Ream", "4802"),
    ("PVC Pipe 1in", "3917"),
    ("Binding Wire", "7217"),
]
STATES = ["27", "29", "24", "33", "07"]  # Maharashtra, Karnataka, Gujarat, Tamil Nadu, Delhi
TWO = Decimal("0.01")


def make_gstin(state: str) -> str:
    pan = (
        "".join(random.choices(string.ascii_uppercase, k=5))
        + f"{random.randint(0, 9999):04d}"
        + random.choice(string.ascii_uppercase)
    )
    first14 = f"{state}{pan}1Z"
    return first14 + gstin_checksum(first14)


def make_invoice(index: int) -> dict[str, object]:
    vendor_state, buyer_state = random.choice(STATES), "27"
    rate = random.choice([Decimal("12"), Decimal("18")])
    items = []
    for name, hsn in random.sample(ITEMS, random.randint(2, 4)):
        qty = Decimal(random.randint(1, 50))
        price = Decimal(random.randint(50, 2000))
        items.append(
            {
                "description": name,
                "hsn_code": hsn,
                "quantity": qty,
                "unit_price": price,
                "tax_rate": rate,
                "amount": qty * price,
            }
        )
    subtotal = sum((i["amount"] for i in items), Decimal("0"))
    tax = (subtotal * rate / 100).quantize(TWO)
    intra = vendor_state == buyer_state  # same state -> CGST + SGST, else IGST
    cgst = sgst = (tax / 2).quantize(TWO) if intra else None
    igst = None if intra else tax
    return {
        "vendor_name": random.choice(VENDORS),
        "vendor_gstin": make_gstin(vendor_state),
        "buyer_gstin": make_gstin(buyer_state),  # a distractor: must NOT be extracted as vendor
        "invoice_number": f"INV/{random.randint(2025, 2026)}/{index:04d}",
        "invoice_date": date(2026, 9, 1) + timedelta(days=random.randint(0, 29)),
        "line_items": items,
        "subtotal": subtotal,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "total_amount": subtotal + tax,
    }


def render(inv: dict[str, object], photo: bool) -> Image.Image:
    image = Image.new("RGB", (1240, 1500), "white")
    draw = ImageDraw.Draw(image)
    font, bold = ImageFont.load_default(size=26), ImageFont.load_default(size=40)
    money = lambda v: f"{v:,.2f}"  # noqa: E731
    y = 60
    draw.text((420, y), "TAX INVOICE", font=bold, fill="black")
    y += 90
    for line in [
        str(inv["vendor_name"]),
        f"GSTIN: {inv['vendor_gstin']}",
        "",
        "Bill To: InvoiceIQ Demo Traders, Mumbai",
        f"Buyer GSTIN: {inv['buyer_gstin']}",
        "",
        f"Invoice No: {inv['invoice_number']}",
        f"Invoice Date: {inv['invoice_date'].strftime('%d/%m/%Y')}",
    ]:  # type: ignore[attr-defined]
        draw.text((60, y), line, font=font, fill="black")
        y += 40
    y += 30
    draw.text(
        (60, y), "Description          HSN     Qty     Rate      Amount", font=font, fill="black"
    )
    y += 45
    for item in inv["line_items"]:  # type: ignore[attr-defined]
        draw.text(
            (60, y),
            f"{item['description']:<22} {item['hsn_code']}   {item['quantity']:>4}  "
            f"{money(item['unit_price']):>9}  {money(item['amount']):>11}",
            font=font,
            fill="black",
        )
        y += 40
    y += 40
    rows = [
        ("Taxable Value", inv["subtotal"]),
        ("CGST", inv["cgst"]),
        ("SGST", inv["sgst"]),
        ("IGST", inv["igst"]),
        ("Grand Total", inv["total_amount"]),
    ]
    for label, value in rows:
        if value is not None:
            draw.text((700, y), f"{label}: {money(value)}", font=font, fill="black")
            y += 40
    if photo:  # simulate a phone photo
        image = image.rotate(random.uniform(-2.5, 2.5), expand=True, fillcolor="white")
        image = image.filter(ImageFilter.GaussianBlur(radius=1.1))
        noise = Image.effect_noise(image.size, 18).convert("RGB")
        image = Image.blend(image, noise, 0.08)
    return image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--out", default="evaluation/data/synthetic")
    parser.add_argument("--seed", type=int, default=42)  # reproducible benchmark
    args = parser.parse_args()
    random.seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for index in range(1, args.count + 1):
        invoice = make_invoice(index)
        kind = "photo" if index % 2 == 0 else "scan"
        render(invoice, photo=kind == "photo").save(out / f"invoice_{index:03d}_{kind}.png")
        (out / f"invoice_{index:03d}_{kind}.json").write_text(
            json.dumps(invoice, default=str, indent=2)
        )
    print(f"Generated {args.count} invoices in {out}")


if __name__ == "__main__":
    main()
