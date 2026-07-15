"""Alias package to expose services under app.services."""
from __future__ import annotations
from pathlib import Path

# Extend the package search path to the root services directory.
__path__.append(str(Path(__file__).resolve().parents[2] / "services"))
