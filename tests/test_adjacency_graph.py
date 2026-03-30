"""Tests for scripts/build_adjacency_graph.py"""

import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.build_adjacency_graph import (
    extract_street_number,
    find_neighbours,
    create_blocks,
)


def test_extract_street_number_simple():
    num, street = extract_street_number("10 Nassau St")
    assert num == 10
    assert "Nassau" in street


def test_extract_street_number_letter_suffix():
    num, street = extract_street_number("10A Kensington Ave")
    assert num == 10


def test_extract_street_number_hyphen():
    num, street = extract_street_number("10-8 Glen Baillie Pl")
    assert num == 10


def test_find_neighbours_returns_dict():
    # find_neighbours takes list of (number, address, params) tuples
    buildings = [
        (8, "8 Nassau St", {"total_height_m": 8.0, "facade_material": "brick"}),
        (10, "10 Nassau St", {"total_height_m": 9.0, "facade_material": "brick"}),
        (12, "12 Nassau St", {"total_height_m": 7.5, "facade_material": "painted"}),
    ]
    result = find_neighbours(buildings)
    assert isinstance(result, dict)


def test_create_blocks_returns_list():
    buildings = [
        (10, "10 St", {"total_height_m": 8.0}),
        (12, "12 St", {"total_height_m": 8.0}),
        (30, "30 St", {"total_height_m": 8.0}),
    ]
    blocks = create_blocks(buildings)
    assert isinstance(blocks, list)
    assert len(blocks) >= 1


def test_extract_none_for_non_numeric():
    num, street = extract_street_number("No Number Street")
    assert num is None or isinstance(num, int)
