# Claude Code — Post-Corruption Repair + colour_palette Gap Fill

Working directory: `D:\liam1_transfer\blender_buildings`

## Context
Cowork session just repaired 1,245 corrupted JSON param files (null-byte padding + truncated JSON) and 43 corrupted Python scripts. enrich_skeletons.py was truncated at line 671 and patched. All 86 tests passing.

## Task 1: Verify all param files are valid JSON
```python
import json, pathlib
d = pathlib.Path("params")
broken = []
for f in sorted(d.glob("*.json")):
    try: json.loads(f.read_text(encoding="utf-8"))
    except: broken.append(f.name)
print(f"Broken: {len(broken)}")
for b in broken: print(f"  {b}")
```
If any broken, fix them. Goal: 0 broken.

## Task 2: Fill colour_palette gap (94% missing)
Only 75/1,241 buildings have colour_palette.facade set. Run `infer_missing_params.py` to fill:
```bash
python scripts/infer_missing_params.py
```
Verify coverage improved. If it doesn't fill colour_palette, check why — the script's `infer_colour_palette()` should derive it from `facade_detail.brick_colour_hex` and `facade_detail.trim_colour_hex` which are at 100% coverage.

## Task 3: Verify enrich_skeletons.py completeness
The file was truncated and patched. Verify the `main()` function is complete — it should:
1. Iterate params/*.json
2. Call enrich_file() on each
3. Print summary stats
4. Have `if __name__ == "__main__": main()` at the end

If anything looks incomplete beyond the print statement repair, check git history:
```bash
git log --oneline -5 scripts/enrich_skeletons.py
git diff HEAD scripts/enrich_skeletons.py
```

## Task 4: Run full test suite
```bash
python -m pytest tests/ -v
```
All 86 tests should pass. If any fail, fix them.

## Task 5: Spot-check 5 repaired param files
Pick 5 buildings that were repaired (truncated deep_facade_analysis). Verify:
- Valid JSON
- deep_facade_analysis section present (may be partial — that's OK, data was truncated)
- All protected fields intact (total_height_m, facade_width_m, site.*, hcd_data.*)
- Building is generation-ready (has floors, height, width, material, roof_type)

Good candidates: 100_Bellevue_Ave.json, 100_Nassau_St.json, 102_Bellevue_Ave.json, 104_Augusta_Ave.json, 106_Oxford_St.json
