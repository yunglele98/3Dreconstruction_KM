#!/usr/bin/env python3
"""
Full Facade Analysis Orchestrator
-----------------------------------
Runs brick texture + facade feature analysis across all photo sources,
cross-references with the photo address index, and generates:
  1. Per-building combined analysis JSONs
  2. Comprehensive special_features_inventory.json
  3. Neighbourhood-wide statistics summary
"""

import os
import sys
import json
import csv
from collections import defaultdict

# Add script directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyse_brick_texture import analyse_image as analyse_brick
from analyse_facade_features import analyse_facade


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOTOS_DIR = BASE_DIR  # field photos in root
HCD_DIR = os.path.join(BASE_DIR, "hcd_photos")
SV_DIR = os.path.join(BASE_DIR, "streetview_images")
PARAMS_DIR = os.path.join(BASE_DIR, "params")
OUTPUT_DIR = os.path.join(PARAMS_DIR, "_analysis_results")
INDEX_CSV = os.path.join(BASE_DIR, "photo_address_index.csv")


def load_address_index():
    """Load the photo-to-address CSV index."""
    index = {}
    if os.path.exists(INDEX_CSV):
        with open(INDEX_CSV, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                index[row['filename']] = row.get('address_or_location', '')
    return index


def get_photo_list(directory, extensions={'.jpg', '.jpeg', '.png'}):
    """Get sorted list of image files in a directory."""
    if not os.path.isdir(directory):
        return []
    return sorted([
        f for f in os.listdir(directory)
        if os.path.splitext(f)[1].lower() in extensions
        and not f.startswith('.')
    ])


def classify_feature(feature, all_features):
    """
    Enhanced feature classification with cross-referencing.
    Combines raw detected features into architectural feature types.
    """
    feat_type = feature.get("type", "")
    subtype = feature.get("subtype", "")
    pos = feature.get("position_pct", 50)

    # Build richer classification
    if feat_type == "arch":
        if pos < 25:
            return {"category": "arch", "location": "upper_facade",
                    "likely_type": "window_head_arch_or_dormer"}
        elif pos < 60:
            return {"category": "arch", "location": "mid_facade",
                    "likely_type": "second_floor_window_arch"}
        else:
            return {"category": "arch", "location": "lower_facade",
                    "likely_type": "door_or_ground_window_arch"}

    elif feat_type == "polychromatic_banding":
        return {"category": "polychromatic", "num_bands": feature.get("num_bands", 0),
                "likely_type": "horizontal_belt_courses"}

    elif feat_type == "chimney":
        return {"category": "chimney", "position_pct": pos,
                "likely_type": "brick_chimney_stack"}

    elif feat_type == "cornice_or_parapet":
        return {"category": "cornice", "position_pct": pos,
                "likely_type": "corbelled_brick_cornice_or_parapet"}

    elif feat_type == "belt_course_or_lintel_line":
        return {"category": "belt_course", "position_pct": pos,
                "likely_type": "stone_or_brick_belt_course_or_continuous_lintel"}

    elif feat_type == "pilaster_or_bay_edge":
        return {"category": "pilaster_or_bay", "position_pct": pos,
                "likely_type": "brick_pilaster_or_bay_window_edge"}

    elif feat_type == "quoin_or_building_edge":
        return {"category": "quoin", "position_pct": pos,
                "likely_type": "quoin_or_building_corner"}

    elif feat_type == "painted_brick":
        return {"category": "painted_brick",
                "coverage_pct": feature.get("coverage_pct", 0)}

    elif feat_type == "symmetry":
        return {"category": "symmetry",
                "score": feature.get("score", 0),
                "classification": feature.get("classification", "")}

    elif feat_type == "building_form":
        return {"category": "building_form",
                "storeys": feature.get("feature", ""),
                "bays": feature.get("bays", 0)}

    return {"category": feat_type}


def run_analysis_on_directory(directory, label, address_index=None):
    """Run both analyses on all photos in a directory."""
    files = get_photo_list(directory)
    if not files:
        print(f"  No images found in {directory}")
        return []

    print(f"\n{'='*60}")
    print(f"Analysing {len(files)} photos from: {label}")
    print(f"{'='*60}")

    results = []
    for i, fname in enumerate(files):
        path = os.path.join(directory, fname)
        entry = {
            "file": fname,
            "source": label,
            "path": path,
            "address": "",
        }

        # Look up address
        if address_index and fname in address_index:
            entry["address"] = address_index[fname]
        elif label == "hcd_photos":
            # HCD filename IS the address
            entry["address"] = os.path.splitext(fname)[0]
        elif label == "streetview":
            entry["address"] = os.path.splitext(fname)[0].replace('_', ' ')

        try:
            brick_result = analyse_brick(path)
            facade_result = analyse_facade(path)

            entry["brick"] = brick_result
            entry["facade"] = facade_result

            # Classify detected features
            classified = []
            for feat in facade_result.get("detected_features", []):
                cf = classify_feature(feat, facade_result["detected_features"])
                cf["raw"] = feat
                classified.append(cf)
            entry["classified_features"] = classified

            status = (f"{facade_result['divisions']['estimated_storeys']}sty, "
                     f"brick={facade_result['colour_zones'].get('brick', 0):.0f}%, "
                     f"{len(classified)} feats")

        except Exception as e:
            entry["error"] = str(e)
            status = f"ERROR: {e}"

        results.append(entry)

        if (i + 1) % 20 == 0 or (i + 1) == len(files):
            print(f"  [{i+1}/{len(files)}] {fname[:50]:50s} {status}")

    return results


def build_feature_inventory(all_results):
    """
    Build comprehensive feature inventory from all analysis results.
    Groups features by type across all buildings.
    """
    inventory = defaultdict(list)

    for entry in all_results:
        if "error" in entry:
            continue

        address = entry.get("address", entry["file"])
        source = entry.get("source", "unknown")

        for feat in entry.get("classified_features", []):
            category = feat.get("category", "unknown")
            record = {
                "address": address,
                "source_photo": entry["file"],
                "photo_source": source,
            }
            record.update({k: v for k, v in feat.items() if k not in ("raw", "category")})
            inventory[category].append(record)

        # Also extract from brick analysis
        brick = entry.get("brick", {})
        if brick:
            colour = brick.get("colour", {})
            if colour.get("variance") == "high":
                inventory["high_colour_variance"].append({
                    "address": address,
                    "source_photo": entry["file"],
                    "base_hex": colour.get("base_hex", ""),
                    "all_colours": colour.get("all_brick_colours", []),
                })

            texture = brick.get("texture", {})
            if texture.get("classification", "").startswith("rough"):
                inventory["rough_texture"].append({
                    "address": address,
                    "source_photo": entry["file"],
                    "roughness_score": texture.get("roughness_score", 0),
                    "classification": texture.get("classification", ""),
                })

            mortar = brick.get("mortar", {})
            if mortar.get("estimated_joint_mm", 0) >= 14:
                inventory["wide_mortar_joints"].append({
                    "address": address,
                    "source_photo": entry["file"],
                    "estimated_mm": mortar.get("estimated_joint_mm", 0),
                    "classification": mortar.get("classification", ""),
                })

    return dict(inventory)


def build_statistics(all_results):
    """Build neighbourhood-wide statistics."""
    stats = {
        "total_photos_analysed": len(all_results),
        "successful_analyses": sum(1 for r in all_results if "error" not in r),
        "errors": sum(1 for r in all_results if "error" in r),
        "by_source": defaultdict(int),
        "brick_coverage": {"high": 0, "medium": 0, "low": 0, "none": 0},
        "storey_distribution": defaultdict(int),
        "symmetry_distribution": defaultdict(int),
        "colour_distribution": defaultdict(int),
        "painted_count": 0,
        "polychromatic_count": 0,
        "with_arches": 0,
        "with_chimneys": 0,
    }

    for entry in all_results:
        stats["by_source"][entry.get("source", "unknown")] += 1

        if "error" in entry:
            continue

        facade = entry.get("facade", {})
        brick = entry.get("brick", {})

        # Brick coverage
        brick_pct = facade.get("colour_zones", {}).get("brick", 0)
        if brick_pct > 30:
            stats["brick_coverage"]["high"] += 1
        elif brick_pct > 10:
            stats["brick_coverage"]["medium"] += 1
        elif brick_pct > 2:
            stats["brick_coverage"]["low"] += 1
        else:
            stats["brick_coverage"]["none"] += 1

        # Storeys
        storeys = facade.get("divisions", {}).get("estimated_storeys", 0)
        stats["storey_distribution"][str(storeys)] += 1

        # Symmetry
        sym_class = facade.get("symmetry", {}).get("classification", "unknown")
        stats["symmetry_distribution"][sym_class] += 1

        # Colour variance
        variance = brick.get("colour", {}).get("variance", "unknown")
        stats["colour_distribution"][variance] += 1

        # Painted
        if facade.get("painted", {}).get("is_painted"):
            stats["painted_count"] += 1

        # Polychromatic
        if facade.get("polychromatic", {}).get("polychromatic"):
            stats["polychromatic_count"] += 1

        # Arches
        if facade.get("arches", {}).get("num_arch_candidates", 0) > 0:
            stats["with_arches"] += 1

        # Chimneys
        if len(facade.get("roof_features", {}).get("roof_features", [])) > 0:
            stats["with_chimneys"] += 1

    # Convert defaultdicts
    stats["by_source"] = dict(stats["by_source"])
    stats["storey_distribution"] = dict(stats["storey_distribution"])
    stats["symmetry_distribution"] = dict(stats["symmetry_distribution"])
    stats["colour_distribution"] = dict(stats["colour_distribution"])

    return stats


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    address_index = load_address_index()
    print(f"Loaded {len(address_index)} entries from photo address index")

    all_results = []

    # 1. HCD photos (highest priority — address-named facade shots)
    hcd_results = run_analysis_on_directory(HCD_DIR, "hcd_photos")
    all_results.extend(hcd_results)

    # Save intermediate
    with open(os.path.join(OUTPUT_DIR, "hcd_analysis.json"), 'w') as f:
        json.dump(hcd_results, f, indent=2)
    print(f"  → Saved hcd_analysis.json ({len(hcd_results)} entries)")

    # 2. Field photos (close-ups, details)
    field_files = get_photo_list(PHOTOS_DIR)
    if field_files:
        field_results = run_analysis_on_directory(PHOTOS_DIR, "field_photos", address_index)
        all_results.extend(field_results)

        with open(os.path.join(OUTPUT_DIR, "field_analysis.json"), 'w') as f:
            json.dump(field_results, f, indent=2)
        print(f"  → Saved field_analysis.json ({len(field_results)} entries)")

    # 3. Build feature inventory
    print(f"\n{'='*60}")
    print("Building comprehensive feature inventory...")
    print(f"{'='*60}")
    inventory = build_feature_inventory(all_results)

    # Sort and format
    for category in inventory:
        inventory[category].sort(key=lambda x: x.get("address", ""))

    with open(os.path.join(OUTPUT_DIR, "special_features_inventory.json"), 'w') as f:
        json.dump(inventory, f, indent=2)

    print("\nFeature inventory summary:")
    for cat, entries in sorted(inventory.items(), key=lambda x: -len(x[1])):
        unique_addresses = len(set(e.get("address", "") for e in entries))
        print(f"  {cat:40s} {len(entries):4d} detections across {unique_addresses:3d} buildings")

    # 4. Build statistics
    stats = build_statistics(all_results)
    with open(os.path.join(OUTPUT_DIR, "neighbourhood_statistics.json"), 'w') as f:
        json.dump(stats, f, indent=2)

    print(f"\n{'='*60}")
    print("NEIGHBOURHOOD STATISTICS")
    print(f"{'='*60}")
    print(f"Total photos analysed:  {stats['total_photos_analysed']}")
    print(f"Successful:             {stats['successful_analyses']}")
    print(f"Errors:                 {stats['errors']}")
    print(f"Brick coverage (high):  {stats['brick_coverage']['high']}")
    print(f"Painted brick:          {stats['painted_count']}")
    print(f"Polychromatic:          {stats['polychromatic_count']}")
    print(f"With arches:            {stats['with_arches']}")
    print(f"With chimneys:          {stats['with_chimneys']}")
    print(f"\nStorey distribution:    {dict(stats['storey_distribution'])}")
    print(f"Symmetry:               {dict(stats['symmetry_distribution'])}")
    print(f"Colour variance:        {dict(stats['colour_distribution'])}")

    print(f"\nAll results saved to: {OUTPUT_DIR}/")
    print("Files generated:")
    print("  hcd_analysis.json              — per-photo HCD analysis")
    print("  field_analysis.json            — per-photo field analysis")
    print("  special_features_inventory.json — comprehensive feature inventory")
    print("  neighbourhood_statistics.json  — aggregate statistics")


if __name__ == "__main__":
    main()
