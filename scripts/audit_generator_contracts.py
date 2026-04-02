"""
Audit script: extract which param fields each create_* function in generate_building.py reads,
build a contract map, and validate active param files against those contracts.

Usage:
    python scripts/audit_generator_contracts.py

Output: outputs/generator_contract_audit.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# Configuration
GENERATE_BUILDING_PATH = Path(__file__).parent.parent / "generate_building.py"
PARAMS_DIR = Path(__file__).parent.parent / "params"
OUTPUT_DIR = Path(__file__).parent.parent / "outputs"
OUTPUT_FILE = OUTPUT_DIR / "generator_contract_audit.json"


def extract_param_accesses(func_body: str) -> tuple[set[str], set[str]]:
    """
    Extract param field accesses from a function body.

    Returns (required_fields, optional_fields) where required are accessed
    without defaults and optional are accessed with .get() defaults.
    """
    required = set()
    optional = set()

    # Pattern 1: params["key"] or params.get("key") — can't determine easily
    # Pattern 2: params.get("key", default) — these are optional
    pattern_with_default = r'params\.get\s*\(\s*["\']([^"\']+)["\']\s*,\s*'
    for match in re.finditer(pattern_with_default, func_body):
        field = match.group(1)
        optional.add(field)

    # Pattern 3: params.get("key") without default — semi-required (optional)
    pattern_without_default = r'params\.get\s*\(\s*["\']([^"\']+)["\']\s*\)'
    for match in re.finditer(pattern_without_default, func_body):
        field = match.group(1)
        optional.add(field)  # .get() always returns something, so it's optional

    # Pattern 4: params["key"] direct access — required
    pattern_direct = r'params\s*\[\s*["\']([^"\']+)["\']\s*\]'
    for match in re.finditer(pattern_direct, func_body):
        field = match.group(1)
        # Only add if not already in optional
        if field not in optional:
            required.add(field)

    # Pattern 5: nested access like facade_detail.get("key")
    # Extract nested accesses like hcd_data, facade_detail, etc.
    nested_pattern = r'(\w+)\s*=\s*params\.get\s*\(\s*["\']([^"\']+)["\']\s*,\s*\{?\}?\s*\)'
    for match in re.finditer(nested_pattern, func_body):
        var_name, field = match.group(1), match.group(2)
        optional.add(field)
        # Now look for accesses to var_name
        nested_accesses = re.findall(rf'{var_name}\.get\s*\(\s*["\']([^"\']+)["\']\s*(?:,|[))])', func_body)
        for nested_field in nested_accesses:
            optional.add(f"{field}.{nested_field}")

    return required, optional


def parse_generate_building() -> dict[str, dict[str, Any]]:
    """Parse generate_building.py and generator_modules/ for create_* function contracts."""
    with open(GENERATE_BUILDING_PATH, encoding="utf-8") as f:
        content = f.read()
    # Also include extracted module files
    modules_dir = GENERATE_BUILDING_PATH.parent / "generator_modules"
    if modules_dir.is_dir():
        for mod_file in sorted(modules_dir.glob("*.py")):
            if mod_file.name.startswith("_"):
                continue
            content += "\n" + mod_file.read_text(encoding="utf-8")

    contract_map = {}

    # Find all create_* functions (skip create_box, create_arch_cutter, etc. — only generator functions)
    generator_functions = {
        "create_walls",
        "create_gable_walls",
        "create_gable_roof",
        "create_cross_gable_roof",
        "create_hip_roof",
        "create_flat_roof",
        "create_porch",
        "create_chimney",
        "create_bay_window",
        "create_storefront",
        "create_string_courses",
        "create_corbelling",
        "create_tower",
        "create_quoins",
        "create_bargeboard",
        "create_cornice_band",
        "create_stained_glass_transoms",
        "create_hip_rooflet",
        "create_window_lintels",
        "create_brackets",
        "create_ridge_finial",
        "create_voussoirs",
        "create_gable_shingles",
        "create_dormer",
        "create_fascia_boards",
        "create_parapet_coping",
        "create_gabled_parapet",
        "create_turned_posts",
        "create_storefront_awning",
        "create_foundation",
        "create_gutters",
        "create_chimney_caps",
        "create_porch_lattice",
        "create_step_handrails",
        "cut_windows",
        "cut_doors",
    }

    for func_name in generator_functions:
        pattern = rf"def {func_name}\s*\([^)]*\):[^\n]*\n(.*?)(?=\ndef |\Z)"
        match = re.search(pattern, content, re.DOTALL)
        if not match:
            continue

        func_body = match.group(1)
        required, optional = extract_param_accesses(func_body)

        # Determine invocation conditions (when is this function called?)
        # This is heuristic; check the main generate_building() for conditionals
        conditions = []
        if func_name == "create_flat_roof":
            conditions.append('roof_type == "flat"')
        elif func_name == "create_gable_roof":
            conditions.append('"gable" in roof_type and "cross" not in roof_type')
        elif func_name == "create_cross_gable_roof":
            conditions.append('"cross" in roof_type or "bay-and-gable" in roof_type')
        elif func_name == "create_hip_roof":
            conditions.append('"hip" in roof_type')
        elif func_name == "create_gable_walls":
            conditions.append('"gable" in roof_type or "cross" in roof_type')
        elif func_name == "create_bargeboard":
            conditions.append('"gable" in roof_type')
        elif func_name == "create_gable_shingles":
            conditions.append('"gable" in roof_type')
        elif func_name == "create_ridge_finial":
            conditions.append('"gable" in roof_type')
        elif func_name == "create_bay_window":
            conditions.append("bay_window.present OR windows_detail[*].bay_window")
        elif func_name == "create_storefront":
            conditions.append("has_storefront == True")
        elif func_name == "create_porch":
            conditions.append("porch_present == True")
        elif func_name == "create_chimney":
            conditions.append("chimneys OR roof_features contains 'chimney'")
        elif func_name == "create_tower":
            conditions.append("tower in roof_features OR special_features")
        elif func_name == "create_dormer":
            conditions.append("dormer in roof_features OR roof_detail.gable_window")
        elif func_name == "create_string_courses":
            conditions.append("string_courses in decorative_elements")
        elif func_name == "create_quoins":
            conditions.append("quoins in decorative_elements")
        elif func_name == "create_bargeboard":
            conditions.append('"gable" in roof_type')
        elif func_name == "create_cornice_band":
            conditions.append("cornice in decorative_elements OR hcd_data.building_features contains 'cornice'")

        contract_map[func_name] = {
            "required": sorted(list(required)),
            "optional": sorted(list(optional)),
            "conditions": conditions,
        }

    return contract_map


def load_active_params() -> list[tuple[str, dict[str, Any]]]:
    """Load all active (non-skipped) param files."""
    params = []
    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        # Skip metadata files and skipped entries
        if param_file.name.startswith("_"):
            continue

        try:
            with open(param_file, encoding="utf-8") as f:
                data = json.load(f)

            if data.get("skipped", False):
                continue

            params.append((param_file.stem, data))
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: skipping {param_file.name}: {e}")

    return params


def check_compatibility(
    contract_map: dict[str, dict[str, Any]],
    params: dict[str, Any],
    address: str,
) -> list[dict[str, Any]]:
    """
    Check a param file against the contract map.
    Determine which create_* functions will be called and check for missing required fields.

    Returns list of warnings.
    """
    warnings = []

    roof_type = str(params.get("roof_type", "gable")).lower()
    has_storefront = params.get("has_storefront", False)
    porch_present = params.get("porch_present", False)
    bay_window = params.get("bay_window", {})
    windows_detail = params.get("windows_detail", [])
    decorative_elements = params.get("decorative_elements", {})
    roof_features = params.get("roof_features", [])

    # Determine which functions will be called
    will_call = set()
    will_call.add("create_walls")
    will_call.add("cut_windows")
    will_call.add("cut_doors")

    # Roof
    if "flat" in roof_type:
        will_call.add("create_flat_roof")
    elif "hip" in roof_type:
        will_call.add("create_hip_roof")
    elif "cross" in roof_type or "bay-and-gable" in roof_type or "bay_and_gable" in roof_type:
        will_call.add("create_cross_gable_roof")
        will_call.add("create_gable_walls")
    elif "gable" in roof_type:
        will_call.add("create_gable_roof")
        will_call.add("create_gable_walls")
    else:
        will_call.add("create_gable_roof")
        will_call.add("create_gable_walls")

    # Decorative/optional features
    if has_storefront:
        will_call.add("create_storefront")
    if porch_present:
        will_call.add("create_porch")
    if isinstance(bay_window, dict) and bay_window.get("present"):
        will_call.add("create_bay_window")
    if windows_detail and any(
        isinstance(f, dict) and f.get("bay_window") for f in windows_detail
    ):
        will_call.add("create_bay_window")

    if isinstance(decorative_elements, dict):
        if decorative_elements.get("string_courses", {}).get("present"):
            will_call.add("create_string_courses")
        if decorative_elements.get("quoins", {}).get("present"):
            will_call.add("create_quoins")
        if decorative_elements.get("bargeboard", {}).get("present") and "gable" in roof_type:
            will_call.add("create_bargeboard")
        if decorative_elements.get("cornice", {}).get("present"):
            will_call.add("create_cornice_band")

    if "gable" in roof_type:
        will_call.add("create_bargeboard")
        will_call.add("create_ridge_finial")
        will_call.add("create_gable_shingles")

    if isinstance(roof_features, list):
        if any("chimney" in str(f).lower() for f in roof_features):
            will_call.add("create_chimney")
        if any("dormer" in str(f).lower() for f in roof_features):
            will_call.add("create_dormer")
        if any("tower" in str(f).lower() for f in roof_features):
            will_call.add("create_tower")

    # Check required fields for each function that will be called
    for func_name in sorted(will_call):
        if func_name not in contract_map:
            continue

        contract = contract_map[func_name]
        for required_field in contract["required"]:
            # Check if field exists and is not None
            keys = required_field.split(".")
            value = params
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    value = None
                    break

            if value is None or (isinstance(value, str) and value == ""):
                warnings.append({
                    "address": address,
                    "function": func_name,
                    "missing_field": required_field,
                    "severity": "error",
                })

    return warnings


def main():
    """Main audit routine."""
    print("[AUDIT] Parsing generate_building.py...")
    contract_map = parse_generate_building()
    print(f"  Found {len(contract_map)} create_* functions")

    print("[AUDIT] Loading active param files...")
    active_params = load_active_params()
    print(f"  Loaded {len(active_params)} active buildings")

    print("[AUDIT] Checking compatibility...")
    all_warnings = []
    fully_compatible = 0
    function_coverage = {}

    for address, params in active_params:
        warnings = check_compatibility(contract_map, params, address)
        all_warnings.extend(warnings)
        if not warnings:
            fully_compatible += 1

        # Track which functions are called for each building
        roof_type = str(params.get("roof_type", "gable")).lower()
        has_storefront = params.get("has_storefront", False)

        for func_name in contract_map:
            if func_name not in function_coverage:
                function_coverage[func_name] = 0

            # Heuristic: assume all buildings call these
            if func_name in ("create_walls", "cut_windows", "cut_doors"):
                function_coverage[func_name] += 1
            elif func_name == "create_flat_roof" and "flat" in roof_type:
                function_coverage[func_name] += 1
            elif func_name == "create_gable_roof" and "gable" in roof_type and "cross" not in roof_type:
                function_coverage[func_name] += 1
            elif func_name in ("create_cross_gable_roof", "create_gable_walls") and ("cross" in roof_type or "bay" in roof_type):
                function_coverage[func_name] += 1
            elif func_name == "create_hip_roof" and "hip" in roof_type:
                function_coverage[func_name] += 1
            elif func_name == "create_storefront" and has_storefront:
                function_coverage[func_name] += 1

    print(f"  Fully compatible: {fully_compatible}/{len(active_params)}")
    print(f"  Warnings found: {len(all_warnings)}")

    # Build output
    output = {
        "contract_map": contract_map,
        "buildings_checked": len(active_params),
        "fully_compatible": fully_compatible,
        "warnings": sorted(all_warnings, key=lambda w: (w["address"], w["function"])),
        "function_coverage": dict(sorted(function_coverage.items())),
    }

    # Create output directory if needed
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"[AUDIT] Results saved to {OUTPUT_FILE}")

    # Summary
    if all_warnings:
        severity_counts = {}
        for warning in all_warnings:
            sev = warning.get("severity", "unknown")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        print(f"  Severity breakdown: {severity_counts}")

        # Group by function
        func_warnings = {}
        for warning in all_warnings:
            func = warning["function"]
            func_warnings[func] = func_warnings.get(func, 0) + 1
        print(f"  Top functions with warnings: {dict(sorted(func_warnings.items(), key=lambda x: -x[1])[:5])}")


if __name__ == "__main__":
    main()
