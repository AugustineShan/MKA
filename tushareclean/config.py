"""Shared configuration and environment loading for tushareclean.

This module centralises the package/project roots, `.env` loading, and a few
common path helpers so that every other module imports a single source of truth
instead of computing ``Path(__file__).resolve().parent.parent`` on its own.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent

COMPANIES_DIR = PROJECT_ROOT / "companies"


def load_env(path: Path) -> None:
    """Load a ``KEY=VALUE`` file into ``os.environ`` only for unset keys."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# Load environment variables from the caller's working directory first, then
# fall back to the package directory.  This lets users drop a .env next to their
# script while still allowing a packaged default.
load_env(Path.cwd() / ".env")
load_env(PACKAGE_ROOT / ".env")
