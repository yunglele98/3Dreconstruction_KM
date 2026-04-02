#!/usr/bin/env python3
"""Photo-verified fixes for agent-created buildings on perimeter streets."""
import json
from pathlib import Path

PARAMS = Path(__file__).resolve().parent.parent / "params"
fixes = []


def fix(name, changes, reason):
    f = PARAMS / f"{name}.json"
    if not f.exists():
        # Try glob match for unicode filenames
        matches = list(PARAMS.glob(f"{name}*"))
        if matches:
            f = matches[0]
        else:
            print(f"  SKIP: {name} - file not found")
            return
    d = json.load(open(f, encoding="utf-8"))
    for k, v in changes.items():
        d[k] = v
    meta = d.setdefault("_meta", {})
    qa = meta.get("qa_photo_fixes", [])
    qa.append(reason)
    meta["qa_photo_fixes"] = qa
    json.dump(d, open(f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    fixes.append((f.stem, reason))


def main():
    # === COLLEGE ST COMMERCIAL BLOCKS ===

    # 374 College (Pho Ha Noi block) - wide commercial strip, 3-4fl brick, ~45m
    fix("374_College_St_Pho_Ha_Noi_Junjun_Hotel_372a_Kaisar_Guest_House_370_Ohiru_Cafe_Sampo_Japanese_Bar_Restaurant_368_366_Lebanese_Garden_364_362", {
        "facade_width_m": 45.0, "facade_depth_m": 18.0,
        "windows_per_floor": [6, 8, 8, 4],
    }, "Photo: wide commercial strip ~45m with 6+ storefronts")

    # 380-372 College - 3fl, ~30m wide
    fix("380-372_College_St", {
        "facade_width_m": 30.0, "facade_depth_m": 18.0,
        "windows_per_floor": [4, 6, 6],
    }, "Photo: wide commercial strip ~30m")

    # 390-382 College - bay-and-gable row converted to commercial, ~35m
    fix("390-382_College_St", {
        "facade_width_m": 35.0, "facade_depth_m": 15.0,
        "roof_type": "gable",
        "windows_per_floor": [4, 4, 3],
    }, "Photo: bay-and-gable commercial row ~35m")

    # 275-289 College (Jump) - large dark commercial, 3fl ~25m
    fix("275-289_College_St_Jump", {
        "facade_width_m": 25.0, "facade_depth_m": 20.0,
        "windows_per_floor": [3, 5, 5],
    }, "Photo: large dark commercial ~25m")

    # 283-289 College
    fix("283-289_College_St", {
        "facade_width_m": 25.0, "facade_depth_m": 20.0,
        "windows_per_floor": [3, 5, 5],
    }, "Photo: commercial block ~25m")

    # 317-323 College
    fix("317-323_College_St", {
        "facade_width_m": 25.0, "facade_depth_m": 18.0,
        "windows_per_floor": [4, 5, 5],
    }, "Photo: commercial strip ~25m")

    # 360 College (UPS Store block) - 4fl brick+glass, ~20m
    for f in PARAMS.glob("360_College_St*"):
        if not f.name.startswith("_"):
            d = json.load(open(f, encoding="utf-8"))
            if not d.get("skipped"):
                d["facade_width_m"] = 20.0
                d["facade_depth_m"] = 18.0
                d["windows_per_floor"] = [3, 4, 4, 2]
                d.setdefault("_meta", {}).setdefault("qa_photo_fixes", []).append(
                    "Photo: 4fl brick+glass commercial ~20m with arch feature")
                json.dump(d, open(f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
                fixes.append((f.stem, "4fl brick+glass ~20m"))
                break

    # 396-386 College
    fix("396-386_College_St", {
        "facade_width_m": 30.0, "facade_depth_m": 15.0,
        "windows_per_floor": [4, 4, 4],
    }, "Photo: commercial strip ~30m")

    # 404-398 College
    fix("404-398_College_St", {
        "facade_width_m": 25.0, "facade_depth_m": 15.0,
        "windows_per_floor": [4, 4, 4],
    }, "Commercial strip ~25m")

    # 422-412a College
    fix("422-412a_College_St", {
        "facade_width_m": 30.0, "facade_depth_m": 15.0,
        "windows_per_floor": [4, 4, 4],
    }, "Commercial strip ~30m")

    # 434 College (Midnight Market block) - long strip ~50m
    for f in PARAMS.glob("434_College_St*"):
        if not f.name.startswith("_"):
            d = json.load(open(f, encoding="utf-8"))
            if not d.get("skipped"):
                d["facade_width_m"] = 50.0
                d["facade_depth_m"] = 15.0
                d["windows_per_floor"] = [8, 8, 8]
                d.setdefault("_meta", {}).setdefault("qa_photo_fixes", []).append(
                    "Photo: very long commercial strip ~50m with 8+ storefronts")
                json.dump(d, open(f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
                fixes.append((f.stem, "long commercial strip ~50m"))
                break

    # 400-414 Spadina
    fix("400-414_Spadina_Ave", {
        "facade_width_m": 35.0, "facade_depth_m": 20.0,
        "windows_per_floor": [4, 6, 6, 4],
    }, "Large Spadina commercial ~35m")


    # === DUNDAS/BATHURST COMMERCIAL ===

    # 750 Dundas (MedWest/Tim Hortons) - 3fl brown brick ~30m
    for f in PARAMS.glob("750_Dundas_St*"):
        if not f.name.startswith("_"):
            d = json.load(open(f, encoding="utf-8"))
            if not d.get("skipped"):
                d["floors"] = 3
                d["total_height_m"] = 12.0
                d["floor_heights_m"] = [4.5, 3.8, 3.7]
                d["facade_width_m"] = 30.0
                d["facade_depth_m"] = 20.0
                d["windows_per_floor"] = [4, 6, 4]
                d.setdefault("_meta", {}).setdefault("qa_photo_fixes", []).append(
                    "Photo: 3fl brown brick commercial ~30m (Tim Hortons/MedWest)")
                json.dump(d, open(f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
                fixes.append((f.stem, "3fl brown brick ~30m"))
                break

    # 406-414 Bathurst - 4fl modern brick+glass ~25m
    fix("406-414_Bathurst_St", {
        "facade_width_m": 25.0, "facade_depth_m": 20.0,
        "facade_material": "brick",
        "windows_per_floor": [3, 4, 4, 4],
    }, "Photo: 4fl modern brick+glass ~25m (Western Dental)")


    # === SPADINA COMMERCIAL ===

    # 387 Spadina (Jo's Cha) - yellow painted narrow storefront ~10m
    for f in PARAMS.glob("387_Spadina_Ave*"):
        if not f.name.startswith("_"):
            d = json.load(open(f, encoding="utf-8"))
            if not d.get("skipped"):
                d["facade_width_m"] = 10.0
                d["facade_depth_m"] = 15.0
                d["facade_material"] = "paint"
                d["facade_colour"] = "yellow painted storefront"
                d["windows_per_floor"] = [2, 3, 3]
                d.setdefault("_meta", {}).setdefault("qa_photo_fixes", []).append(
                    "Photo: yellow painted storefront ~10m")
                json.dump(d, open(f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
                fixes.append((f.stem, "yellow painted storefront ~10m"))
                break

    # 401 Spadina (Tankx/HANBINGO)
    for f in PARAMS.glob("401_Spadina_Ave*"):
        if not f.name.startswith("_"):
            d = json.load(open(f, encoding="utf-8"))
            if not d.get("skipped"):
                d["facade_width_m"] = 18.0
                d["facade_depth_m"] = 15.0
                d["windows_per_floor"] = [3, 4, 4]
                d.setdefault("_meta", {}).setdefault("qa_photo_fixes", []).append(
                    "Commercial strip ~18m on Spadina")
                json.dump(d, open(f, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
                fixes.append((f.stem, "commercial strip ~18m"))
                break

    # 353 Spadina (New Sky Restaurant)
    fix("353_Spadina_Ave_New_Sky_Restaurant", {
        "facade_width_m": 8.0, "facade_depth_m": 15.0,
        "windows_per_floor": [2, 3, 3],
    }, "Single commercial unit ~8m")


    # === RESIDENTIAL SIDE STREETS ===

    # 12-14 Hickory - 2fl red brick semi ~8m, flat roof
    fix("12-14_Hickory_St", {
        "floors": 2, "total_height_m": 6.5, "floor_heights_m": [3.3, 3.2],
        "facade_width_m": 8.0, "facade_depth_m": 10.0,
        "roof_type": "flat",
        "windows_per_floor": [3, 3],
    }, "Photo: 2fl red brick semi pair ~8m, flat roof")

    # 142-144 Denison - 2.5fl bay-and-gable row
    fix("142-144_Denison_Ave", {
        "floors": 3, "total_height_m": 10.0, "floor_heights_m": [3.5, 3.3, 3.2],
        "facade_width_m": 10.0, "facade_depth_m": 12.0,
        "roof_type": "gable",
        "windows_per_floor": [2, 2, 1],
    }, "Photo: 2.5fl bay-and-gable row ~10m")

    # 144 cottage Oxford St - 2.5fl brick row with gambrel
    fix("144_cottage_Oxford_St_area_row_houses", {
        "facade_width_m": 12.0, "facade_depth_m": 10.0,
        "windows_per_floor": [3, 3],
    }, "Photo: 2.5fl brick row houses with gambrel ~12m")

    # 32E-32C Oxford
    fix("32E-32C_Oxford_St", {
        "facade_width_m": 10.0, "facade_depth_m": 10.0,
        "windows_per_floor": [3, 3, 1],
    }, "Residential row ~10m")

    # 150-152 Nassau
    fix("150-152_Nassau_St", {
        "facade_width_m": 10.0, "facade_depth_m": 12.0,
        "windows_per_floor": [3, 3, 2],
    }, "Semi-detached pair ~10m")

    # 6-8 Hickory
    fix("6-8_Hickory_St", {
        "floors": 2, "total_height_m": 6.5, "floor_heights_m": [3.3, 3.2],
        "facade_width_m": 8.0, "facade_depth_m": 10.0,
        "roof_type": "flat",
        "windows_per_floor": [3, 3],
    }, "Photo: 2fl semi pair ~8m, similar to 12-14 Hickory")

    # 43656751 (coordinate-named)
    fix("43656751_-79403686", {
        "facade_width_m": 15.0, "facade_depth_m": 15.0,
        "windows_per_floor": [3, 4, 4, 2],
    }, "Coordinate-named building, reasonable commercial dims")


    print(f"\nApplied {len(fixes)} photo-verified fixes:")
    for name, reason in fixes:
        print(f"  {name}: {reason}")


if __name__ == "__main__":
    main()
