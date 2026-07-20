from __future__ import annotations

import os


def normalize_path(path: str) -> str:
    return os.path.normpath(path.strip())


def sanitize_name(value: str) -> str:
    return value.strip() or ""


def format_entry_label(entry: object) -> str:
    if hasattr(entry, "name") and hasattr(entry, "path"):
        return f"{entry.name} - {entry.path}"
    return str(entry)
