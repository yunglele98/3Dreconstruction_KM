"""Pytest path setup for repo-local script imports.

Some tests import modules directly from ``scripts/`` using bare names such as
``import enrich_skeletons``. Adding both the repository root and the
``scripts/`` directory to ``sys.path`` is sufficient for that pattern and
avoids eagerly importing every top-level script during pytest startup.
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
REPO_ROOT = SCRIPTS_DIR.parent


def _ensure_repo_paths() -> None:
    """Make repo modules importable without executing unrelated scripts."""
    scripts_str = str(SCRIPTS_DIR)
    root_str = str(REPO_ROOT)
    if scripts_str not in sys.path:
        sys.path.insert(0, scripts_str)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


_ensure_repo_paths()
