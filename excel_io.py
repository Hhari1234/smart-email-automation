"""
excel_io.py
Reads recipient lists (xlsx/csv) and writes send logs / failed-email reports / summary.
"""
import pandas as pd
from pathlib import Path
from datetime import datetime

# Maps flexible source column names -> canonical field names used across the app
COLUMN_ALIASES = {
    "hr_name": ["hr name", "name", "hrname", "hr_name", "contact name"],
    "company": ["company", "organisation", "organization", "company name"],
    "email": ["email", "e-mail", "mail", "email address"],
    "job_role": ["job role", "role", "title", "job_role", "position"],
    "location": ["location", "city", "place"],
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    lower_map = {c.lower().strip(): c for c in df.columns}
    rename = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_map:
                rename[lower_map[alias]] = canonical
                break
    df = df.rename(columns=rename)
    for canonical in COLUMN_ALIASES:
        if canonical not in df.columns:
            df[canonical] = ""
    return df


def load_recipients(path: str) -> list[dict]:
    path = str(path)
    if path.lower().endswith(".csv"):
        df = pd.read_csv(path, dtype=str).fillna("")
    else:
        df = pd.read_excel(path, dtype=str).fillna("")
    df = _normalize_columns(df)
    records = df[["hr_name", "company", "email", "job_role", "location"]].to_dict("records")
    return records


def create_sample_recipients(path: Path):
    sample = pd.DataFrame(
        [
            {
                "HR Name": "Jane Doe",
                "Company": "Example Tech Pvt Ltd",
                "Email": "jane.doe@example.com",
                "Job Role": "Software Development Engineer",
                "Location": "Bengaluru",
            },
            {
                "HR Name": "John Smith",
                "Company": "Sample Solutions Inc",
                "Email": "john.smith@example.com",
                "Job Role": "Backend Developer",
                "Location": "Hyderabad",
            },
        ]
    )
    sample.to_excel(path, index=False)


def append_log(log_path: Path, row: dict):
    """Appends one send-result row to the running CSV log (creates file if needed)."""
    log_path = Path(log_path)
    df_row = pd.DataFrame([row])
    if log_path.exists():
        df_row.to_csv(log_path, mode="a", header=False, index=False)
    else:
        df_row.to_csv(log_path, mode="w", header=True, index=False)


def export_failed(records: list[dict], out_path: Path):
    df = pd.DataFrame(records)
    df.to_excel(out_path, index=False)


def export_summary(stats: dict, out_path: Path):
    lines = [
        "ResumeMailer - Send Summary Report",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "-" * 40,
        f"Total Sent:      {stats.get('sent', 0)}",
        f"Total Failed:    {stats.get('failed', 0)}",
        f"Total Skipped (duplicates): {stats.get('skipped', 0)}",
        f"Total Processed: {stats.get('sent', 0) + stats.get('failed', 0) + stats.get('skipped', 0)}",
    ]
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
