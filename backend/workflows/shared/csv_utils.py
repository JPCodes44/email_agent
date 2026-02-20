import csv
from pathlib import Path


def read_csv(path: str | Path) -> list[dict]:
    """Read a CSV file and return a list of dicts with stripped keys and values."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({k.strip(): v.strip() for k, v in row.items()})
        return rows


def write_csv(path: str | Path, rows: list[dict], fieldnames: list[str] | None = None):
    """Write rows back to a CSV file."""
    if not rows:
        return
    fieldnames = fieldnames or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def filter_not_emailed(rows: list[dict]) -> list[dict]:
    """Return rows where Emailed? is not 'Yes' (case-insensitive)."""
    return [r for r in rows if r.get("Emailed?", "").strip().lower() != "yes"]
