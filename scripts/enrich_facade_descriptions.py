#!/usr/bin/env python3
"""Add richer facade descriptions to existing param JSON files."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def _atomic_write_json(filepath, data, ensure_ascii=True):
    """Write JSON atomically via temp file + rename to prevent corruption."""
    filepath = Path(filepath)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=filepath.parent, delete=False,
        suffix=".tmp", encoding="utf-8",
    ) as tmp:
        json.dump(data, tmp, indent=2, ensure_ascii=ensure_ascii)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(str(tmp_path), str(filepath))


PARAMS_DIR = Path(__file__).parent.parent / "params"


def _configure_utf8_stdout() -> None:
    """Avoid Windows cp1252 encode crashes when printing non-ASCII filenames."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def title_case_address(name: str) -> str:
    text = str(name).replace("_", " ").replace(", Toronto, ON", "").strip()
    return text


def clean_phrase(value: str) -> str:
    text = str(value or "").replace("_", " ").strip()
    replacements = {
        "flat with parapet": "flat parapet",
        "flat with partial hip": "flat roof with a partial hip element",
        "double hung sash": "double-hung sash",
        "house form": "house-form",
        "bay and gable": "bay-and-gable",
    }
    lowered = text.lower()
    for src, dst in replacements.items():
        lowered = lowered.replace(src, dst)
    return lowered


def dedupe_words(text: str) -> str:
    parts = text.split()
    cleaned = []
    for part in parts:
        if cleaned and cleaned[-1].lower().strip(".,") == part.lower().strip(".,"):
            continue
        cleaned.append(part)
    return " ".join(cleaned)


def normalize_typology(value: str) -> str:
    text = clean_phrase(value)
    replacements = {
        "house-form semi-detached bay-and-gable": "semi-detached bay-and-gable house-form",
        "house-form, semi-detached, bay-and-gable": "semi-detached bay-and-gable house-form",
        "multi-residential": "multi-residential",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text.strip(" ,")


def classify_typology(value: str) -> str:
    text = normalize_typology(value)
    if "commercial" in text:
        return "commercial"
    if "institutional" in text:
        return "institutional"
    if "multi-residential" in text:
        return "multi_residential"
    if "bay-and-gable" in text:
        return "bay_and_gable"
    if "row" in text:
        return "row_house"
    if "detached" in text:
        return "detached"
    if "semi-detached" in text:
        return "semi_detached"
    return "general"


def normalize_roof_phrase(value: str) -> str:
    text = clean_phrase(value)
    replacements = {
        "cross-gable (bay-and-gable typology)": "cross-gable",
        "flat parapet": "flat roof with a parapet",
        "flat_with_parapet": "flat roof with a parapet",
        "flat roof with a partial hip element": "flat roof with a partial hip",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def normalize_window_phrase(value: str) -> str:
    text = clean_phrase(value)
    replacements = {
        "double-hung sash with segmental arches": "segmental-arched double-hung sash",
        "double-hung sash with dark-painted surrounds": "double-hung sash with dark-painted surrounds",
        "commercial plate glass ground, double-hung upper": "commercial plate-glass openings at ground level and double-hung sash above",
        "double-hung sash": "double-hung sash windows",
        "double hung sash": "double-hung sash windows",
        "double hung 2 over 2": "double-hung 2-over-2 sash windows",
        "double-hung 2 over 2": "double-hung 2-over-2 sash windows",
        "flat headed": "flat-headed",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return dedupe_words(text)


def normalize_colour_phrase(value: str) -> str:
    text = clean_phrase(value)
    replacements = {
        "dark red brown": "dark red-brown",
        "red brown": "red-brown",
        "red orange": "red-orange",
        "light grey to buff": "light grey to buff",
        "red brick with decorative brickwork": "warm red brick",
        "brick with commercial storefront": "warm brick and storefront glazing",
        "red-orange, warm tone, well-maintained": "well-maintained red-orange brick",
        "red_orange": "red-orange brick",
        "red_brown": "red-brown brick",
        "dark_red_brown": "dark red-brown brick",
        "grey_tan": "grey-tan",
        "brick or frame": "mixed brick and frame",
        "flat headed": "flat-headed",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def normalize_feature_phrase(value: str) -> str:
    text = clean_phrase(value)
    replacements = {
        "flat headed": "flat-headed",
        "flat headed openings": "flat-headed openings",
        "flat headed window and door openings": "flat-headed window and door openings",
        "tall flat headed window openings": "tall flat-headed window openings",
        "stone lintels and windowsills": "stone lintels and sills",
        "ornamented cornice": "ornamented cornice",
        "cornice": "cornice",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def is_visual_feature(value: str) -> bool:
    text = clean_phrase(value)
    non_visual_markers = [
        "constructed ",
        "rebuilt ",
        "converted ",
        "associated with ",
        "founder of ",
        "original two campuses",
        "cultural heritage value",
        "landmark within the district",
        "public school",
        "walk-up apartment building",
    ]
    return not any(marker in text for marker in non_visual_markers)


def split_sentences(text: str) -> list[str]:
    parts = [part.strip(" .") for part in str(text or "").split(".")]
    return [part for part in parts if part]


def clean_summary_sentence(sentence: str) -> str:
    text = " ".join(str(sentence or "").split()).strip(" .")
    replacements = {
        "Landmark within the District": "District landmark",
        "Square clock tower is a prominent visual landmark": "Its square clock tower is a prominent visual landmark",
        "One of original two campuses of George Brown College": "One of the original two George Brown College campuses",
        "Constructed 1925 as public school": "Built in 1925 as a public school",
        "Converted to residential lofts 2000": "Later converted to residential lofts in 2000",
        "Rare purpose-built Victorian commercial structure at gateway to Augusta Avenue": "A rare purpose-built Victorian commercial building at the gateway to Augusta Avenue",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text.strip(" .")


def summarize_statement(statement: str) -> str:
    sentences = split_sentences(statement)
    if not sentences:
        return ""

    scored: list[tuple[int, str]] = []
    for sentence in sentences:
        low = clean_phrase(sentence)
        score = 0
        if any(
            marker in low
            for marker in [
                "rare ",
                "landmark",
                "well-preserved",
                "gateway",
                "prominent visual landmark",
                "pair of",
                "cross-gabled",
                "bay-and-gable",
                "decorative",
                "brickwork",
                "stonework",
                "clock tower",
                "gable brackets",
                "public school",
            ]
        ):
            score += 3
        if any(marker in low for marker in ["associated with ", "founder of "]):
            score -= 1
        if "cultural heritage value" in low:
            score -= 2
        if "constructed " in low or "built " in low:
            score += 1
        if "converted to " in low:
            score += 1
        scored.append((score, sentence))

    scored.sort(key=lambda item: (-item[0], len(item[1])))
    chosen = []
    for _, sentence in scored:
        cleaned = clean_summary_sentence(sentence)
        if cleaned and cleaned not in chosen:
            chosen.append(cleaned)
        if len(chosen) == 2:
            break

    if len(chosen) < 2:
        for sentence in sentences:
            cleaned = clean_summary_sentence(sentence)
            if cleaned and cleaned not in chosen:
                chosen.append(cleaned)
            if len(chosen) == 2:
                break

    text = ". ".join(chosen).strip()
    if text and not text.endswith("."):
        text += "."
    return text


def describe_openings(data: dict) -> str:
    category = classify_typology(data.get("hcd_data", {}).get("typology", ""))
    windows_per_floor = data.get("windows_per_floor", [])
    window_type = normalize_window_phrase(data.get("window_type", "windows"))
    door_count = data.get("door_count", 1)
    if isinstance(windows_per_floor, list) and windows_per_floor:
        upper = [v for v in windows_per_floor[1:] if isinstance(v, int) and v > 0]
        if windows_per_floor[0] == 0 and upper:
            upper_text = " and ".join(
                [
                    f"{upper[0]} upper-window bay{'s' if upper[0] != 1 else ''}",
                    *(
                        [f"{sum(upper[1:])} additional bay{'s' if sum(upper[1:]) != 1 else ''} above"]
                        if len(upper) > 1
                        else []
                    ),
                ]
            )
            text = f"The facade is organized as a storefront base with {upper_text}"
        elif category == "institutional":
            readable = ", ".join(str(v) for v in windows_per_floor)
            text = f"The elevation is ordered in broad vertical bays, with a {readable} opening rhythm from lower to upper levels"
        elif category in {"row_house", "bay_and_gable", "semi_detached", "detached"}:
            readable = ", ".join(str(v) for v in windows_per_floor)
            text = f"The facade keeps a domestic opening rhythm of {readable} window bays from lower to upper levels"
        else:
            readable = ", ".join(str(v) for v in windows_per_floor)
            text = f"The visible opening pattern is organized as {readable} window bays from lower to upper levels"
    else:
        text = "The opening rhythm is vertically ordered across the facade"
    if window_type:
        text += f", using {window_type}"
    if isinstance(door_count, int) and door_count > 0:
        text += f", and {door_count} principal entrance{'s' if door_count != 1 else ''}"
    return text + "."


def describe_materials(data: dict) -> str:
    category = classify_typology(data.get("hcd_data", {}).get("typology", ""))
    facade_material = clean_phrase(data.get("facade_material", "brick"))
    facade_colour = normalize_colour_phrase(data.get("facade_colour", ""))
    detail = data.get("facade_detail", {})
    bond = ""
    mortar = ""
    if isinstance(detail, dict):
        bond = clean_phrase(detail.get("bond_pattern", ""))
        mortar = clean_phrase(detail.get("mortar_colour", ""))
    special_material = {
        "red brick with decorative brickwork": "red brick enriched with decorative brickwork",
        "brick with commercial storefront": "brick above a commercial storefront",
        "brick with commercial ground floor alterations": "brick with commercialized ground-floor alterations",
        "red-orange brick in running bond pattern": "red-orange brick",
    }
    facade_material = special_material.get(facade_material, facade_material)

    if category == "commercial":
        text = f"The frontage is defined primarily by {facade_material}"
    elif category == "institutional":
        text = f"The principal elevation is faced primarily in {facade_material}"
    else:
        text = f"The facade reads primarily as {facade_material}"
    if facade_colour:
        colour_text = facade_colour
        if colour_text not in facade_material and facade_material not in colour_text:
            text += f" in a {colour_text} palette"
    if bond:
        text += f", laid in {bond}"
    if mortar:
        text += f" with {mortar} mortar joints"
    return text + "."


def describe_massing(data: dict) -> str:
    category = classify_typology(data.get("hcd_data", {}).get("typology", ""))
    width = data.get("facade_width_m")
    floors = data.get("floors")
    roof_type = normalize_roof_phrase(data.get("roof_type", ""))
    typology = normalize_typology(data.get("hcd_data", {}).get("typology", ""))
    if category == "commercial":
        text = "The street frontage"
    elif category == "institutional":
        text = "The principal elevation"
    else:
        text = "The street elevation"
    if isinstance(width, (int, float)):
        text += f" spans roughly {width:g} metres"
    if floors:
        text += f" across {floors} storeys"
    if roof_type:
        if category == "commercial":
            text += f" beneath a {roof_type}"
        else:
            text += f" and is capped by a {roof_type}"
    if typology:
        text += f", consistent with its {typology} typology"
    return text + "."


def describe_heritage_features(data: dict) -> str:
    category = classify_typology(data.get("hcd_data", {}).get("typology", ""))
    hcd = data.get("hcd_data", {})
    features = hcd.get("building_features", [])
    decorative = data.get("decorative_elements", {})
    feature_bits = []
    if isinstance(features, list):
        feature_bits.extend(str(f) for f in features[:6] if is_visual_feature(str(f)))
    if isinstance(decorative, dict):
        for key in ["string_courses", "quoins", "cornice", "gable_brackets", "stained_glass_transoms", "stone_lintels"]:
            value = decorative.get(key)
            if isinstance(value, dict) and value.get("present", True):
                feature_bits.append(key.replace("_", " "))
    if not feature_bits:
        return ""
    seen = []
    for item in feature_bits:
        low = normalize_feature_phrase(item)
        if low not in seen:
            seen.append(low)
    top = ", ".join(seen[:6])
    if category == "commercial":
        return f"Key storefront and facade features include {top}."
    if category == "institutional":
        return f"Key heritage elements on the principal elevation include {top}."
    return f"Character-defining facade elements include {top}."


def describe_porch(data: dict) -> str:
    porch = data.get("porch")
    if isinstance(porch, dict) and porch.get("present"):
        porch_type = clean_phrase(porch.get("type", "porch")).lower()
        if porch_type == "open front porch":
            return " and an open front porch"
        elif porch_type == "enclosed porch":
            return " and an enclosed porch"
        else:
            return " and a porch"
    return ""


def build_facade_description(data: dict) -> str:
    building_name = data.get("building_name") or title_case_address(data.get("_meta", {}).get("address", "This building"))
    typology = normalize_typology(data.get("hcd_data", {}).get("typology", ""))
    
    # Infer category if typology is missing but has_storefront is present
    if not typology and data.get("has_storefront"):
        category = "commercial"
    else:
        category = classify_typology(typology)
    
    article = "an" if typology[:1] in "aeiou" else "a"
    if typology: # Use typology if available
        if category == "commercial":
            intro = f"{building_name} is a commercial building with a street-level storefront."
        elif category == "institutional":
            intro = f"{building_name} is {article} {typology} building."
        elif category == "bay_and_gable":
            intro = f"{building_name} is a bay-and-gable house-form building."
        elif category == "row_house":
            intro = f"{building_name} is a row-house building."
        else:
            intro = f"{building_name} is {article} {typology} building."
    elif category == "commercial": # Use inferred commercial category if no typology
        intro = f"{building_name} is a commercial building with a street-level storefront."
    else: # Fallback
        intro = f"{building_name} is a building with a street-facing facade."
    parts = [
        intro,
        describe_massing(data),
        describe_materials(data),
        describe_openings(data),
    ]
    porch_desc = describe_porch(data)
    if porch_desc:
        # Append porch description to the last main part of the facade description, before heritage
        # For simplicity, let's append it to the openings description.
        # This requires modifying the last element of 'parts'
        parts[-1] = parts[-1].rstrip('.') + porch_desc + '.'

    heritage = describe_heritage_features(data)
    if heritage:
        parts.append(heritage)
    return " ".join(parts)


def enrich_file(path: Path) -> bool:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Skip non-building photos
    if data.get("skipped"):
        return False

    changed = False
    facade_detail = data.get("facade_detail")
    if not isinstance(facade_detail, dict):
        facade_detail = {}
        data["facade_detail"] = facade_detail
        changed = True

    description = build_facade_description(data)
    if data.get("facade_description") != description:
        data["facade_description"] = description
        changed = True

    composition = describe_massing(data)
    if facade_detail.get("composition") != composition:
        facade_detail["composition"] = composition
        changed = True
    opening_rhythm = describe_openings(data)
    if facade_detail.get("opening_rhythm") != opening_rhythm:
        facade_detail["opening_rhythm"] = opening_rhythm
        changed = True
    heritage = describe_heritage_features(data)
    if heritage and facade_detail.get("heritage_expression") != heritage:
        facade_detail["heritage_expression"] = heritage
        changed = True
    heritage_summary = summarize_statement(data.get("hcd_data", {}).get("statement_of_contribution", ""))
    if heritage_summary and data.get("heritage_summary") != heritage_summary:
        data["heritage_summary"] = heritage_summary
        changed = True
    if heritage_summary and facade_detail.get("heritage_summary") != heritage_summary:
        facade_detail["heritage_summary"] = heritage_summary
        changed = True

    if changed:
        _atomic_write_json(path, data)
    return changed


def main() -> None:
    _configure_utf8_stdout()
    changed = 0
    files = 0
    for path in sorted(PARAMS_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        files += 1
        if enrich_file(path):
            changed += 1
            print(f"[ENRICH] {path.name}")
    print(f"\nEnriched {changed} of {files} files")


if __name__ == "__main__":
    main()


