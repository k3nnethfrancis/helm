#!/usr/bin/env python3
"""Generate a deterministic messy sales CSV for agent benchmarking.

Produces ~100 rows with strategic corruption:
- Missing values (region ~10%, sales_rep ~5%)
- Mixed date formats (ISO, Unix timestamp, human-readable)
- Duplicate order_ids with conflicting data
- Negative quantities (data entry errors)
- String in numeric field ("TBD" price)
- Mixed case in status column
"""

import argparse
import csv
import io
import random
import sys
from datetime import datetime, timedelta


PRODUCTS = ["Widget A", "Widget B", "Gadget X", "Gadget Y", "Gizmo Pro", "Gizmo Lite"]
REGIONS = ["North", "South", "East", "West", "Central"]
REPS = ["Jordan", "Taylor", "Morgan", "Casey", "Riley", "Quinn"]
STATUSES_NORMAL = ["Completed", "Pending", "Cancelled", "Refunded"]
STATUS_VARIANTS = {
    "Completed": ["Completed", "completed", "COMPLETED"],
    "Pending": ["Pending", "pending", "PENDING"],
    "Cancelled": ["Cancelled", "cancelled", "CANCELLED"],
    "Refunded": ["Refunded", "refunded", "REFUNDED"],
}

BASE_DATE = datetime(2024, 1, 1)


def random_date():
    """Return a random date in 2024 as a datetime object."""
    return BASE_DATE + timedelta(days=random.randint(0, 364))


def format_date_iso(dt):
    return dt.strftime("%Y-%m-%d")


def format_date_unix(dt):
    return str(int(dt.timestamp()))


def format_date_human(dt):
    return dt.strftime("%B %d, %Y")


def generate_rows(n=95):
    """Generate n base rows of sales data."""
    rows = []
    for i in range(1, n + 1):
        order_id = f"ORD-{i:04d}"
        dt = random_date()

        # Date format: ~80% ISO, ~15% Unix, ~5% human-readable
        r = random.random()
        if r < 0.80:
            date_str = format_date_iso(dt)
        elif r < 0.95:
            date_str = format_date_unix(dt)
        else:
            date_str = format_date_human(dt)

        product = random.choice(PRODUCTS)
        quantity = random.randint(1, 50)
        price = round(random.uniform(5.0, 200.0), 2)

        # Region: ~10% missing
        region = random.choice(REGIONS) if random.random() > 0.10 else ""

        # Sales rep: ~5% missing
        sales_rep = random.choice(REPS) if random.random() > 0.05 else ""

        # Status with mixed case
        base_status = random.choice(STATUSES_NORMAL)
        status = random.choice(STATUS_VARIANTS[base_status])

        rows.append({
            "order_id": order_id,
            "date": date_str,
            "product": product,
            "quantity": quantity,
            "price": price,
            "region": region,
            "sales_rep": sales_rep,
            "status": status,
        })

    return rows


def inject_corruptions(rows):
    """Apply strategic corruptions to the generated rows."""
    # 1. Duplicate IDs with conflicting prices/quantities (5 duplicates)
    dup_indices = random.sample(range(len(rows)), 5)
    duplicates = []
    for idx in dup_indices:
        original = rows[idx].copy()
        # Conflicting price and quantity
        original["quantity"] = original["quantity"] + random.randint(-5, 10)
        original["price"] = round(original["price"] * random.uniform(0.8, 1.3), 2)
        duplicates.append(original)

    # 2. Negative quantities on a few rows (data entry errors)
    neg_indices = random.sample(range(len(rows)), 3)
    for idx in neg_indices:
        rows[idx]["quantity"] = -abs(rows[idx]["quantity"])

    # 3. One row with price as string "TBD"
    tbd_idx = random.choice(range(len(rows)))
    rows[tbd_idx]["price"] = "TBD"

    # Insert duplicates at scattered positions
    for dup in duplicates:
        insert_pos = random.randint(0, len(rows))
        rows.insert(insert_pos, dup)

    return rows


def generate(seed=42):
    """Generate the full messy dataset."""
    random.seed(seed)
    rows = generate_rows(95)
    rows = inject_corruptions(rows)
    return rows


def write_csv(rows, output=None):
    """Write rows to CSV file or stdout."""
    fieldnames = ["order_id", "date", "product", "quantity", "price", "region", "sales_rep", "status"]

    if output:
        with open(output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        sys.stdout.write(buf.getvalue())


def main():
    parser = argparse.ArgumentParser(description="Generate messy sales CSV for benchmarking")
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    args = parser.parse_args()

    rows = generate()
    write_csv(rows, args.output)


if __name__ == "__main__":
    main()
