"""Halt detection: checked every loop iteration before any action is taken."""

from __future__ import annotations

import os
from pathlib import Path


def is_halted(halt_file_path: str = "./HALT") -> bool:
    """Return True if a halt signal is active (file or env var)."""
    if os.environ.get("HALT", "").lower() in ("true", "1", "yes"):
        return True
    return Path(halt_file_path).exists()
