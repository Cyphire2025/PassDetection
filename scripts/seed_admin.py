#!/usr/bin/env python3
"""Delegate repository-root invocations to the canonical backend seed script."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    backend_root = repository_root / "backend"
    sys.path.insert(0, str(backend_root))
    runpy.run_path(str(backend_root / "scripts" / "seed_admin.py"), run_name="__main__")


if __name__ == "__main__":
    main()
