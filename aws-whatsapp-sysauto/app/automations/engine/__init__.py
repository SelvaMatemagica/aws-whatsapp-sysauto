"""Alias package for app.automations.engine."""
from __future__ import annotations
from pathlib import Path

__path__.append(str(Path(__file__).resolve().parents[2] / "automations" / "engine"))
