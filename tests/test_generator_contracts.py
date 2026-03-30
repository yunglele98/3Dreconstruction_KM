"""Tests for scripts/audit_generator_contracts.py"""

import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.audit_generator_contracts import (
    extract_param_accesses,
)


def test_extract_finds_params_get():
    code = '''width = params.get("facade_width_m", 5.0)
height = params["total_height_m"]'''
    required, optional = extract_param_accesses(code)
    all_fields = required | optional
    assert "facade_width_m" in all_fields or "total_height_m" in all_fields


def test_extract_finds_optional():
    code = '''width = params.get("facade_width_m", 5.0)'''
    required, optional = extract_param_accesses(code)
    assert "facade_width_m" in optional


def test_extract_handles_empty():
    required, optional = extract_param_accesses("")
    assert isinstance(required, set)
    assert isinstance(optional, set)
    assert len(required) == 0
    assert len(optional) == 0


def test_extract_multiple_fields():
    code = '''
w = params.get("facade_width_m")
h = params.get("total_height_m")
m = params.get("facade_material")
'''
    required, optional = extract_param_accesses(code)
    all_fields = required | optional
    assert len(all_fields) >= 2


def test_extract_returns_tuple_of_sets():
    result = extract_param_accesses("x = params.get('test')")
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], set)
    assert isinstance(result[1], set)


def test_extract_nested_get():
    code = '''
bw = params.get("bay_window", {})
w = bw.get("width_m", 2.0)
'''
    required, optional = extract_param_accesses(code)
    all_fields = required | optional
    assert "bay_window" in all_fields


def test_extract_bracket_access():
    code = '''height = params["total_height_m"]'''
    required, optional = extract_param_accesses(code)
    assert "total_height_m" in required


def test_extract_ignores_non_params():
    code = '''x = other_dict.get("not_a_param")'''
    required, optional = extract_param_accesses(code)
    assert "not_a_param" not in (required | optional)
