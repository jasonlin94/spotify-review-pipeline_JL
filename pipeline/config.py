"""Tiny .env loader (stdlib only) + run controls.

Loads KEY=VALUE lines from a .env file into os.environ without overwriting
values already set in the real environment. Keys are never printed.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | os.PathLike = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def control(name: str, default):
    """Read a numeric run control from env with a default."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return type(default)(raw)
    except (TypeError, ValueError):
        return default
