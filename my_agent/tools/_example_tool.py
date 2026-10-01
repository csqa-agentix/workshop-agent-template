"""COPY ME to make a tool. Rename this file (drop the leading underscore) to switch it on.

A good tool:
  • does ONE deterministic job              • returns REAL output as a string, never a guess
  • has a clear one-sentence docstring      • raises ValueError("helpful message") on bad input
  • reaches files only through resolve()    • contains NO judgement ("is this good?") – that is the prompt's job
"""
from __future__ import annotations

from app.tools._sandbox import resolve
from app.tools.registry import tool


@tool
def count_words(path: str) -> str:
    """Count the words in a text file in the workspace."""
    file = resolve(path)
    if not file.is_file():
        raise ValueError(f"'{path}' not found. Call list_files first.")
    return f"{path}: {len(file.read_text(encoding='utf-8', errors='replace').split())} words"
