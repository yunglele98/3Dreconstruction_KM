"""Tests for writeback_to_db — skipped when psycopg2 is unavailable."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# writeback_to_db calls sys.exit(1) at module level when psycopg2 is missing,
# so we must pre-check and skip the entire module before importing.
pytest.importorskip("psycopg2", reason="psycopg2 not installed (requires database)")

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import writeback_to_db


def test_parse_number_street_returns_text_number():
    parsed = writeback_to_db._parse_number_street("440 College St")
    assert parsed == ("440", "College St")


def test_parse_number_street_handles_suffix_and_whitespace():
    parsed = writeback_to_db._parse_number_street("  59A   Kensington   Ave ")
    assert parsed == ("59", "Kensington Ave")
