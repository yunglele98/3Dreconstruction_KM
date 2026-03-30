# Codex CLI Batch 3 — Task Prompt (2026-03-28)

Paste this entire prompt into Codex CLI. Work through tasks in order. After each task, write output to the specified path and print a summary.

Working directory: `D:\liam1_transfer\blender_buildings`

---

## Task 1: Fix 2 Known Bugs in enrich_skeletons.py

Edge-case tests (tests/test_generator_edge_cases.py) found 2 real bugs:

**Bug 1:** `infer_facade_hex()` crashes when `facade_material` is None.
- Line ~64: `material_str.lower()` called without null check.
- Fix: Add `if not material_str: return None` at function start.

**Bug 2:** `enrich_depth()` crashes when `facade_width_m` is None.
- Line ~169: `width <= 5.0` comparison fails on None.
- Fix: Add `if width is None: return params` early return.

**Do this:**
1. Open `scripts/enrich_skeletons.py`
2. Fix both bugs as described
3. Run: `python -m pytest tests/test_generator_edge_cases.py -v` — all 49 tests should pass
4. Run: `python -m pytest tests/ -q` — full suite should show 294+ passed
5. Write: `docs/reports/enrich_bugfix_2026-03-28.md` with lines changed and test results

---

## Task 2: Create Unified QA Report Generator

Several scripts reference `--qa-report` but no unified QA report exists. Create one.

**Do this:**
1. Create `scripts/generate_qa_report.py` that:
   - Scans all params/*.json (skip `skipped: true`)
   - For each building, checks:
     - Height consistency: `total_height_m` vs `sum(floor_heights_m)` — flag if diff > 0.75m
     - Floor count: `floors` vs `len(floor_heights_m)` — flag mismatch
     - Missing critical fields: facade_width_m, total_height_m, floors, facade_material, roof_type
     - Storefront conflicts: has_storefront=true AND ground floor windows in windows_detail
     - Door count vs doors_detail length mismatch
     - Colour palette completeness: missing primary_hex or trim_hex
     - Readiness score < 80
   - Outputs JSON report: `outputs/qa_report.json`
   - Also outputs human-readable: `docs/reports/qa_report_2026-03-28.md`
   - Accepts `--fix` flag to auto-fix safe issues (height rounding, missing defaults)
2. Run it: `python scripts/generate_qa_report.py`
3. Run with fix: `python scripts/generate_qa_report.py --fix --dry-run` and report what would change
4. Write tests: `tests/test_qa_report.py` with at least 10 tests covering each check type

---

## Task 3: Add --validate Flag to generate_building.py

The generator should be able to validate params without generating geometry (useful for CI).

**Do this:**
1. Add argument parsing at the bottom of `generate_building.py`:
   ```python
   if __name__ == "__main__":
       import argparse
       parser = argparse.ArgumentParser()
       parser.add_argument("--validate", action="store_true", help="Validate params without generating")
       parser.add_argument("--params-dir", default="params", help="Params directory")
       parser.add_argument("--match", help="Only process buildings matching this string")
       args = parser.parse_args()

       if args.validate:
           import json
           from pathlib import Path
           params_dir = Path(args.params_dir)
           ok = 0; fail = 0; errors = []
           for f in sorted(params_dir.glob("*.json")):
               try:
                   p = json.loads(f.read_text(encoding="utf-8"))
                   if p.get("skipped"): continue
                   if args.match and args.match.lower() not in f.stem.lower(): continue
                   valid, errs = _validate_params(p)
                   if valid: ok += 1
                   else: fail += 1; errors.extend(errs)
               except Exception as e:
                   fail += 1; errors.append(f"{f.name}: {e}")
           print(f"Validated: {ok} OK, {fail} FAIL")
           for e in errors: print(f"  {e}")
           sys.exit(0 if fail == 0 else 1)
   ```
2. If `_validate_params` doesn't exist yet (Gemini Batch 3 Task 8), create a standalone version
3. Test: `python generate_building.py --validate --params-dir params --match Baldwin`
4. Verify syntax: `python -c "import ast; ast.parse(open('generate_building.py').read()); print('OK')"`

---

## Task 4: SSIM Comparison Tool for Render QA

Create a tool that compares rendered building images against reference renders to detect regressions.

**Do this:**
1. Create `scripts/ssim_compare.py`:
   - Accept `--reference-dir` and `--new-dir` arguments
   - For each matching filename in both dirs, compute SSIM score (0-1)
   - Flag renders with SSIM < 0.85 as "significant change"
   - Output JSON: `outputs/ssim_comparison.json` with per-building scores
   - Output summary: which buildings changed most, sorted by SSIM ascending
   - Support `--threshold 0.85` to customize
2. Also create `scripts/ssim_single.py` for comparing two individual images
3. Write: `tests/test_ssim_compare.py` with tests using synthetic test images (create small test PNGs in tmp_path)

---

## Task 5: Door Deduplication Script

Some buildings have duplicate entries in `doors_detail` (same position, same type).

**Do this:**
1. Create `scripts/dedup_doors.py`:
   - Scan all params/*.json for buildings with `doors_detail`
   - For each building, find doors with identical or near-identical positions (within 0.3m)
   - If duplicates found, keep the one with more complete data (more non-null fields)
   - Support `--dry-run` (report only) and `--fix` (write changes)
   - Add `_meta.doors_deduped: true` and `_meta.doors_dedup_count: N` to modified files
2. Run dry-run: `python scripts/dedup_doors.py --dry-run`
3. Report: how many buildings affected, total duplicates found
4. Write: `docs/reports/door_dedup_2026-03-28.md`

---

## Task 6: Coverage Matrix Generator

Create a comprehensive per-building feature coverage matrix.

**Do this:**
1. Create `scripts/generate_coverage_matrix.py`:
   - Scan all active params
   - For each building, check presence of 25 key fields:
     ```
     floors, total_height_m, facade_width_m, facade_depth_m, facade_material,
     roof_type, roof_pitch_deg, floor_heights_m, windows_per_floor, windows_detail,
     doors_detail, door_count, has_storefront, storefront, porch,
     colour_palette, facade_detail, decorative_elements, deep_facade_analysis,
     photo_observations, hcd_data, site.lon, site.lat, volumes, condition
     ```
   - Output CSV: `outputs/coverage_matrix.csv` — 1 row per building, 1 column per field (1/0)
   - Output summary: `docs/reports/coverage_matrix_2026-03-28.md`
     - Total coverage percentage per field
     - Buildings with lowest coverage (bottom 20)
     - Fields with lowest coverage (which data is most sparse)
2. Run it and report results

---

## Task 7: Bay Window Geometry Fix

Some buildings have bay windows with `projection_m` > `facade_depth_m`, which would create impossible geometry.

**Do this:**
1. Create `scripts/fix_bay_windows.py`:
   - Scan all params for buildings with `bay_window` or `bay_windows` in decorative_elements
   - Check: `projection_m` should be < `facade_depth_m * 0.4` (max 40% of depth)
   - If exceeded, clamp to `facade_depth_m * 0.3` (safe 30%)
   - Also check: `width_m` should be < `facade_width_m * 0.5`
   - Support `--dry-run` and `--fix`
   - Add `_meta.bay_window_clamped: true` to modified files
2. Run dry-run and report findings
3. Write: `docs/reports/bay_window_fix_2026-03-28.md`

---

## Task 8: String Course Spacing Validator

String courses (horizontal decorative bands) need consistent spacing relative to floor heights.

**Do this:**
1. Create `scripts/validate_string_courses.py`:
   - For buildings with `decorative_elements.string_courses`
   - Check: spacing between string courses should roughly match floor heights
   - Flag buildings where string course heights are outside floor boundaries
   - Check: string_course_height_m should be between 0.05m and 0.3m (reasonable range)
   - Support `--fix` to adjust out-of-range values to nearest valid value
2. Run and report
3. Write: `docs/reports/string_course_validation_2026-03-28.md`

---

## Context

- Working directory: `D:\liam1_transfer\blender_buildings`
- Generator: `generate_building.py` (~6,200 lines, runs inside Blender)
- Enrichment: `scripts/enrich_skeletons.py` (main enrichment logic)
- Params: `params/` (1,688 JSON files, 1,241 active after skipped filter)
- Tests: `tests/` (294 passing, 1 skipped)
- Protected fields (NEVER modify): `total_height_m`, `facade_width_m`, `facade_depth_m`, `site.*`, `city_data.*`, `hcd_data.*`
- After all tasks, run: `python -m pytest tests/ -q` as final verification — should show 294+ passed
- Task order: 1 first (bugfix), then 2-8 in any order
