"""EXAMPLE custom tool. A good tool: ONE deterministic job, REAL output, plain-English errors.
Judgement ("is this important?") belongs in the prompt/skill, never here."""
from __future__ import annotations

import csv
from collections import Counter

from app.tools._sandbox import resolve
from app.tools.registry import tool


@tool
def summarize_csv(path: str, column: str) -> str:
    """Count how many rows have each value in one column of a CSV file in the workspace (for example a 'status' column)."""
    file = resolve(path)
    if not file.is_file():
        raise ValueError(f"'{path}' not found. Call list_files first.")
    with file.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if column not in (reader.fieldnames or []):
            raise ValueError(f"No column '{column}'. Columns are: {reader.fieldnames}")
        counts = Counter(row[column] for row in reader)
    return f"{path}: {sum(counts.values())} rows. {column}: " + ", ".join(f"{k}={v}" for k, v in counts.most_common())
