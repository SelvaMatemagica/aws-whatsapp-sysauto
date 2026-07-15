"""Alias package so local imports using `app.*` work when this folder is added to sys.path."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Add the project root to the package search path so imports like
# `from app.config import settings` can resolve root/config.py.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

__path__.append(str(ROOT))
