#!/usr/bin/env python3
"""
Generate deterministic test fixtures for all 10 SnapScript CLI gate tasks.

Run from repo root:
    python scripts/generate_fixtures.py

Outputs:
    tests/fixtures/integration/task_NN_<name>.csv   (input)
    tests/fixtures/integration/task_NN_expected.csv (expected output)
    tests/fixtures/integration/FIXTURE_MANIFEST.md  (counts for assertions)
"""
import json
import os
import random
import string
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SEED = 42
random.seed(SEED)

OUT = Path("tests/fixtures/integration")
OUT.mkdir(parents=True, exist_ok=True)

manifest = {}  # task_id → {input_rows, output_rows, ...notes}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def rng():
    """Return a seeded random.Random so each task starts from a known state."""
    return random.Random(SEED)


def random_email(r, domain="test.com"):
    name = "".join(r.choices(string.ascii_lowercase, k=r.randint(4, 9)))
    return f"{name}@{domain}"


def random_date(r, start=date(2023, 1, 1), end=date(2024, 12, 31)):
    delta = (end - start).days
    return start + timedelta(days=r.randint(0, delta))


# ─────────────────────────────────────────────────────────────────────────────
# Task 1: Deduplicate by email, keep latest created_at
# ─────────────────────────────────────────────────────────────────────────────
def task_01():
    r = random.Random(SEED + 1)

    # 800 unique emails → 200 will appear twice
    unique_emails = [random_email(r, "example.com") for _ in range(800)]
    # Ensure uniqueness
    unique_emails = list(dict.fromkeys(unique_emails))
    while len(unique_emails) < 800:
        unique_emails.append(random_email(r, "example.com"))
        unique_emails = list(dict.fromkeys(unique_emails))
    unique_emails = unique_emails[:800]

    # Force specific known duplicate for assertion
    unique_emails[0] = "alice@test.com"

    rows = []
    for email in unique_emails:
        d = random_date(r)
        rows.append({
            "id": r.randint(1000, 9999),
            "email": email,
            "name": "".join(r.choices(string.ascii_letters, k=8)),
            "created_at": d.strftime("%Y-%m-%d"),
        })

    # Inject 200 duplicates — each has an earlier date than the original
    duplicates = []
    dup_emails = unique_emails[:200]
    for email in dup_emails:
        original_row = next(ro for ro in rows if ro["email"] == email)
        original_date = date.fromisoformat(original_row["created_at"])
        # Duplicate gets an earlier date (so the original should be kept)
        earlier_date = original_date - timedelta(days=r.randint(1, 180))
        duplicates.append({
            "id": r.randint(1000, 9999),
            "email": email,
            "name": "".join(r.choices(string.ascii_letters, k=8)),
            "created_at": earlier_date.strftime("%Y-%m-%d"),
        })

    all_rows = rows + duplicates
    r.shuffle(all_rows)

    df = pd.DataFrame(all_rows)
    assert len(df) == 1000
    df.to_csv(OUT / "task_01_customers.csv", index=False)

    # Expected: keep most recent per email
    df["created_at"] = pd.to_datetime(df["created_at"])
    expected = df.sort_values("created_at", ascending=False).drop_duplicates(
        subset="email", keep="first"
    ).sort_index()
    assert len(expected) == 800
    assert expected["email"].nunique() == 800
    expected["created_at"] = expected["created_at"].dt.strftime("%Y-%m-%d")
    expected.to_csv(OUT / "task_01_expected.csv", index=False)

    manifest["task_01"] = {
        "description": "Deduplicate by email, keep latest created_at",
        "input_rows": 1000,
        "output_rows": 800,
        "unique_emails": 800,
        "known_duplicate_email": "alice@test.com",
        "note": "alice@test.com row with later created_at must be kept",
    }
    print("✓ Task 01: dedup by email (1000 in → 800 out)")


# ─────────────────────────────────────────────────────────────────────────────
# Task 2: Filter rows where amount > 1000
# ─────────────────────────────────────────────────────────────────────────────
def task_02():
    r = random.Random(SEED + 2)

    amounts = [round(r.uniform(0, 5000), 2) for _ in range(500)]
    df = pd.DataFrame({
        "order_id": range(1, 501),
        "customer": ["".join(r.choices(string.ascii_letters, k=6)) for _ in range(500)],
        "amount": amounts,
        "status": [r.choice(["pending", "shipped", "delivered"]) for _ in range(500)],
    })
    df.to_csv(OUT / "task_02_orders.csv", index=False)

    expected = df[df["amount"] > 1000].copy()
    known_count = len(expected)
    expected.to_csv(OUT / "task_02_expected.csv", index=False)

    manifest["task_02"] = {
        "description": "Keep only orders where amount > 1000",
        "input_rows": 500,
        "output_rows": known_count,
        "amount_min_in_output": float(expected["amount"].min()),
        "note": "All output rows must have amount > 1000",
    }
    print(f"✓ Task 02: filter amount > 1000 (500 in → {known_count} out)")


# ─────────────────────────────────────────────────────────────────────────────
# Task 3: Concatenate first_name + last_name → full_name
# ─────────────────────────────────────────────────────────────────────────────
def task_03():
    r = random.Random(SEED + 3)

    first_names = ["Alice", "Bob", "Carol", "David", "Eve", "Frank", "Grace",
                   "Henry", "Iris", "Jack", "Karen", "Leo", "Mia", "Noah", "Olivia"]
    last_names = ["Smith", "Jones", "Williams", "Brown", "Taylor", "Davies",
                  "Evans", "Wilson", "Thomas", "Roberts", "Johnson", "White"]

    rows = []
    for i in range(200):
        first = r.choice(first_names)
        last = r.choice(last_names)
        rows.append({
            "contact_id": i + 1,
            "first_name": first,
            "last_name": last,
            "email": f"{first.lower()}.{last.lower()}{r.randint(1,99)}@company.com",
            "phone": f"555-{r.randint(1000,9999)}",
        })

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "task_03_contacts.csv", index=False)

    expected = df.copy()
    expected["full_name"] = expected["first_name"] + " " + expected["last_name"]
    expected.to_csv(OUT / "task_03_expected.csv", index=False)

    first_row_full = f"{df.iloc[0]['first_name']} {df.iloc[0]['last_name']}"
    manifest["task_03"] = {
        "description": "Combine first_name + last_name into full_name column",
        "input_rows": 200,
        "output_rows": 200,
        "first_row_full_name": first_row_full,
        "note": "full_name column added; original columns preserved",
    }
    print(f"✓ Task 03: concat columns (200 in → 200 out, adds full_name column)")


# ─────────────────────────────────────────────────────────────────────────────
# Task 4: Convert date format MM/DD/YYYY → YYYY-MM-DD
# ─────────────────────────────────────────────────────────────────────────────
def task_04():
    r = random.Random(SEED + 4)

    known_row_date_in = "01/15/2024"
    known_row_date_out = "2024-01-15"

    rows = []
    for i in range(300):
        if i == 0:
            d_str = known_row_date_in
        else:
            d = random_date(r)
            d_str = d.strftime("%m/%d/%Y")
        rows.append({
            "log_id": i + 1,
            "event_date": d_str,
            "level": r.choice(["INFO", "WARN", "ERROR", "DEBUG"]),
            "message": "Event message " + str(i + 1),
        })

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "task_04_logs.csv", index=False)

    expected = df.copy()
    expected["event_date"] = pd.to_datetime(
        expected["event_date"], format="%m/%d/%Y"
    ).dt.strftime("%Y-%m-%d")
    expected.to_csv(OUT / "task_04_expected.csv", index=False)

    manifest["task_04"] = {
        "description": "Convert event_date from MM/DD/YYYY to YYYY-MM-DD",
        "input_rows": 300,
        "output_rows": 300,
        "known_input_date": known_row_date_in,
        "known_output_date": known_row_date_out,
        "note": "Row 0: 01/15/2024 → 2024-01-15",
    }
    print("✓ Task 04: date format conversion (300 in → 300 out)")


# ─────────────────────────────────────────────────────────────────────────────
# Task 5: Cast price to numeric, drop rows where conversion fails
# ─────────────────────────────────────────────────────────────────────────────
def task_05():
    r = random.Random(SEED + 5)

    prices = [str(round(r.uniform(1, 500), 2)) for _ in range(380)]
    # Inject 20 invalid rows
    invalid = ["N/A", "invalid", "n/a", "TBD", "-", "??", "none",
               "N/A", "invalid", "N/A", "n/a", "TBD", "-", "??",
               "none", "N/A", "invalid", "TBD", "-", "??"]
    all_prices = prices + invalid
    r.shuffle(all_prices)

    rows = []
    for i, price in enumerate(all_prices):
        rows.append({
            "product_id": i + 1,
            "name": "Product " + str(i + 1),
            "price": price,
            "category": r.choice(["electronics", "clothing", "food", "books"]),
        })

    df = pd.DataFrame(rows)
    assert len(df) == 400
    df.to_csv(OUT / "task_05_mixed.csv", index=False)

    expected = df.copy()
    expected["price"] = pd.to_numeric(expected["price"], errors="coerce")
    expected = expected.dropna(subset=["price"])
    assert len(expected) == 380
    expected.to_csv(OUT / "task_05_expected.csv", index=False)

    manifest["task_05"] = {
        "description": "Convert price to numeric, drop 20 invalid rows",
        "input_rows": 400,
        "output_rows": 380,
        "invalid_count": 20,
        "note": "Rows with N/A, invalid, TBD, etc. are dropped; price dtype is float64",
    }
    print("✓ Task 05: dtype cast (400 in → 380 out)")


# ─────────────────────────────────────────────────────────────────────────────
# Task 6: Fill nulls in notes column with "No notes"
# ─────────────────────────────────────────────────────────────────────────────
def task_06():
    r = random.Random(SEED + 6)

    notes_pool = [
        "Followed up via email",
        "Left voicemail",
        "Met at conference",
        "Referral from client",
        "Cold outreach",
        None,  # will be placed intentionally
    ]

    rows = []
    null_indices = set(r.sample(range(300), 100))
    for i in range(300):
        rows.append({
            "ticket_id": i + 1,
            "assignee": "".join(r.choices(string.ascii_letters, k=6)),
            "status": r.choice(["open", "closed", "pending"]),
            "notes": None if i in null_indices else r.choice(notes_pool[:5]),
        })

    df = pd.DataFrame(rows)
    assert df["notes"].isna().sum() == 100
    df.to_csv(OUT / "task_06_sparse.csv", index=False)

    expected = df.copy()
    expected["notes"] = expected["notes"].fillna("No notes")
    assert expected["notes"].isna().sum() == 0
    assert (expected["notes"] == "No notes").sum() == 100
    expected.to_csv(OUT / "task_06_expected.csv", index=False)

    manifest["task_06"] = {
        "description": "Fill null notes with 'No notes'",
        "input_rows": 300,
        "output_rows": 300,
        "null_count_input": 100,
        "null_count_output": 0,
        "filled_count": 100,
        "note": "Exactly 100 rows get 'No notes'; non-null rows unchanged",
    }
    print("✓ Task 06: fill nulls (300 in → 300 out, 100 fills)")


# ─────────────────────────────────────────────────────────────────────────────
# Task 7: Replace status 'old' → 'archived'
# ─────────────────────────────────────────────────────────────────────────────
def task_07():
    r = random.Random(SEED + 7)

    statuses = ["active", "old", "pending"]
    weights = [0.5, 0.3, 0.2]  # 250 active, 150 old, 100 pending (approximately)

    rows = []
    for i in range(500):
        rows.append({
            "record_id": i + 1,
            "name": "Record " + str(i + 1),
            "status": r.choices(statuses, weights=weights, k=1)[0],
            "updated_at": random_date(r).strftime("%Y-%m-%d"),
        })

    df = pd.DataFrame(rows)
    known_old_count = (df["status"] == "old").sum()
    known_active_count = (df["status"] == "active").sum()
    known_pending_count = (df["status"] == "pending").sum()
    df.to_csv(OUT / "task_07_status.csv", index=False)

    expected = df.copy()
    expected["status"] = expected["status"].replace("old", "archived")
    assert (expected["status"] == "old").sum() == 0
    assert (expected["status"] == "archived").sum() == known_old_count
    assert (expected["status"] == "active").sum() == known_active_count
    expected.to_csv(OUT / "task_07_expected.csv", index=False)

    manifest["task_07"] = {
        "description": "Replace status 'old' → 'archived'",
        "input_rows": 500,
        "output_rows": 500,
        "known_old_count": int(known_old_count),
        "known_active_count": int(known_active_count),
        "known_pending_count": int(known_pending_count),
        "note": "All 'old' become 'archived'; 'active' and 'pending' untouched",
    }
    print(f"✓ Task 07: conditional replace (500 in → 500 out, {known_old_count} replaced)")


# ─────────────────────────────────────────────────────────────────────────────
# Task 8: Sort by score descending, keep top 10
# ─────────────────────────────────────────────────────────────────────────────
def task_08():
    r = random.Random(SEED + 8)

    scores = [r.randint(0, 100) for _ in range(1000)]
    rows = []
    for i, score in enumerate(scores):
        rows.append({
            "player_id": i + 1,
            "username": "player_" + str(i + 1),
            "score": score,
            "level": r.randint(1, 50),
        })

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "task_08_scores.csv", index=False)

    expected = df.nlargest(10, "score").reset_index(drop=True)
    top_score = df["score"].max()
    tenth_score = df["score"].nlargest(10).min()
    expected.to_csv(OUT / "task_08_expected.csv", index=False)

    manifest["task_08"] = {
        "description": "Sort by score descending, keep top 10",
        "input_rows": 1000,
        "output_rows": 10,
        "max_score": int(top_score),
        "tenth_score": int(tenth_score),
        "note": "Output must be sorted descending; first row is highest score",
    }
    print(f"✓ Task 08: sort + limit (1000 in → 10 out, top score={top_score})")


# ─────────────────────────────────────────────────────────────────────────────
# Task 9: Count rows by event_type
# ─────────────────────────────────────────────────────────────────────────────
def task_09():
    r = random.Random(SEED + 9)

    event_types = ["click", "view", "purchase", "signup", "logout"]
    # Assign counts deterministically so totals are known
    counts = {
        "click": 600,
        "view": 500,
        "purchase": 300,
        "signup": 400,
        "logout": 200,
    }
    assert sum(counts.values()) == 2000

    rows = []
    event_id = 1
    for event_type, count in counts.items():
        for _ in range(count):
            rows.append({
                "event_id": event_id,
                "event_type": event_type,
                "user_id": r.randint(1000, 9999),
                "timestamp": random_date(r).strftime("%Y-%m-%d"),
            })
            event_id += 1

    r.shuffle(rows)
    df = pd.DataFrame(rows)
    assert len(df) == 2000
    assert df["event_type"].nunique() == 5
    df.to_csv(OUT / "task_09_events.csv", index=False)

    expected = (
        df.groupby("event_type")
        .size()
        .reset_index(name="count")
        .sort_values("event_type")
    )
    expected.to_csv(OUT / "task_09_expected.csv", index=False)

    manifest["task_09"] = {
        "description": "Count rows per event_type",
        "input_rows": 2000,
        "output_rows": 5,
        "event_counts": counts,
        "total_sum": 2000,
        "note": "5 rows in output (one per event_type); sum of counts == 2000",
    }
    print("✓ Task 09: group count (2000 in → 5 out)")


# ─────────────────────────────────────────────────────────────────────────────
# Task 10: Large file — keep only rows where region == 'West'
# ─────────────────────────────────────────────────────────────────────────────
def task_10():
    r = random.Random(SEED + 10)

    regions = ["West", "East", "North", "South"]
    # 25% West → ~50,000 rows
    n = 200_000
    region_col = r.choices(regions, weights=[0.25, 0.25, 0.25, 0.25], k=n)

    df = pd.DataFrame({
        "sale_id": range(1, n + 1),
        "region": region_col,
        "amount": [round(r.uniform(10, 10000), 2) for _ in range(n)],
        "rep": ["Rep_" + str(r.randint(1, 50)) for _ in range(n)],
    })

    known_west_count = (df["region"] == "West").sum()
    df.to_csv(OUT / "task_10_big.csv", index=False)

    expected = df[df["region"] == "West"].copy()
    expected.to_csv(OUT / "task_10_expected.csv", index=False)

    manifest["task_10"] = {
        "description": "Filter rows where region == 'West' (200k row performance gate)",
        "input_rows": n,
        "output_rows": int(known_west_count),
        "note": f"~25% West rows; completes within 25s; memory peak < 1GB",
    }
    print(f"✓ Task 10: large filter (200000 in → {known_west_count} out)")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    print("Generating SnapScript CLI gate fixtures...")
    print(f"Output directory: {OUT.resolve()}\n")

    task_01()
    task_02()
    task_03()
    task_04()
    task_05()
    task_06()
    task_07()
    task_08()
    task_09()
    task_10()

    # Write manifest
    manifest_path = OUT / "FIXTURE_MANIFEST.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # Human-readable summary for FIXTURE_MANIFEST.md
    md_lines = [
        "# SnapScript CLI Gate — Fixture Manifest",
        "",
        "Generated by `scripts/generate_fixtures.py` (seed=42).",
        "All counts are exact — use these in integration test assertions.",
        "",
        "| Task | Input Rows | Output Rows | Key Assertion |",
        "|------|-----------|-------------|---------------|",
    ]
    for tid, m in manifest.items():
        key = list(m.items())[3] if len(m) > 3 else ("note", m.get("note", ""))
        md_lines.append(
            f"| {tid} | {m['input_rows']:,} | {m['output_rows']:,} "
            f"| {m['description']} |"
        )

    md_lines += [
        "",
        "## Known Counts (for test assertions)",
        "",
    ]
    for tid, m in manifest.items():
        md_lines.append(f"### {tid}")
        for k, v in m.items():
            md_lines.append(f"- **{k}**: `{v}`")
        md_lines.append("")

    md_path = OUT / "FIXTURE_MANIFEST.md"
    md_path.write_text("\n".join(md_lines))

    print(f"\n✓ Manifest written to {manifest_path}")
    print(f"✓ Readme written to {md_path}")
    print(f"\nAll {len(manifest)} fixtures generated successfully.")
