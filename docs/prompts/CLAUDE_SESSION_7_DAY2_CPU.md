# Claude Code Session 7 — Day 2 CPU Worker (Post-LOD)

You are a Claude Code agent on the Kensington Market 3D Heritage reconstruction project. LOD generation is complete (1,244/1,249 buildings). Collision meshes are done (1,254). Your job is **pipeline completions, exports, validation, and hardening** — pure CPU work, no Blender.

## Setup

```bash
cd /c/users/liam1/blender_buildings
```

Read `CLAUDE.md` for full context. Key state (Day 2, April 3, 2026):
- 1,241 active buildings, 1,224 FBX exports, 1,244 LODs, 1,254 collision meshes
- Depth fused: 1,200 | Seg fused: 1,224 | Signage fused: 71/313
- Visual audit: 371 critical, 124 medium, 247 low, 245 acceptable
- Gemini Layer 4: 97/1,051 done (stalled — rate-limited)
- CityGML and 3D Tiles scripts exist but output may be stale
- CI pipeline exists (`.github/workflows/qa.yml`)
- Scenarios dir has 5 scenario folders but no `apply_scenario.py` integration
- Tests: 1,916 collected

## Your Tasks (priority order)

### 1. Rebuild Datasmith + Unity Manifests

LODs and collision are done. Rebuild the engine manifests:
```bash
python scripts/build_unreal_datasmith.py
python scripts/build_unity_prefab_manifest.py
```
Verify outputs include LOD and collision references. Check `outputs/exports/kensington_scene.udatasmith` and `outputs/exports/unity_manifest.json`.

### 2. Regenerate CityGML + 3D Tiles Exports

```bash
python scripts/export/export_citygml.py --lod 2 --output citygml/kensington_lod2.gml
python scripts/export/export_3dtiles.py --output tiles_3d/
```
Validate: CityGML should have 1,200+ buildings. tileset.json should have children array length > 500.

### 3. Signage Fusion Gap

Only 71/313 signage files are fused. Investigate and fix:
- Check `scripts/enrich/fuse_signage.py` for errors
- Run it: `python scripts/enrich/fuse_signage.py --signage signage/ --params params/`
- Target: 200+ fused (from 313 available signage files)

### 4. Regenerate Coverage Matrix + Visual Audit Dashboard

After manifests and signage fix:
```bash
python scripts/run_blender_buildings_workflows.py dashboard --once-json > /dev/null
python scripts/visual_audit/generate_dashboard.py --input outputs/visual_audit/priority_queue.json
```

### 5. Gemini Layer 4 Recovery

Gemini analysis stalled at 97/1,051. Check for errors and resume:
```bash
python scripts/visual_audit/layer4_gemini_api.py --help
```
Check rate limit status. If API is available, resume with `--skip-existing`. When done or if still blocked:
```bash
python scripts/visual_audit/merge_gemini_analysis.py
python scripts/visual_audit/fusion.py
```

### 6. Export Validation Script

Create `scripts/validate_all_exports.py` — a single script that checks:
- FBX count >= 1,200 with valid headers
- LOD1/LOD2/LOD3 exist for each FBX
- Collision mesh exists for each FBX
- CityGML file has correct building count
- tileset.json has matching building count
- Datasmith XML references all buildings
- Unity manifest references all buildings
- Print summary table with pass/fail per check

### 7. Web Platform Data Rebuild

Regenerate web data for the planning dashboard:
```bash
python scripts/export/build_web_data.py
python scripts/export/build_web_geojson.py
python scripts/export/build_web_app_data.py
```
Verify outputs in `outputs/web/` or `outputs/deliverables/`.

### 8. Sprint Progress Report

```bash
python scripts/monitor/sprint_progress.py --json
```
Save output to `outputs/sprint_day2_report.json`. Compare against Day 2 targets.

## Code Conventions

- 4-space indent, `snake_case` functions/files, `UPPER_SNAKE_CASE` constants
- `pathlib.Path` for paths, `json` with `indent=2` for output
- All file I/O: `encoding="utf-8"`
- Atomic writes: tempfile + os.replace for param modifications
- Track provenance in `_meta` dict
- Every new script gets a test file

## Protected Fields (NEVER modify)

`total_height_m`, `facade_width_m`, `facade_depth_m`, `site.*`, `city_data.*`, `hcd_data.*`

## Coordination

- **Don't touch:** `outputs/exports/*.fbx` (stable, complete)
- **Don't run Blender** (no GPU work this session)
- **Do touch:** `scripts/`, `outputs/deliverables/`, `outputs/web/`, `citygml/`, `tiles_3d/`, `tests/`

## Start

Begin with Task 1 (manifests) — fast, unblocks Task 2 and 7. Then Task 3 (signage gap). Then Tasks 2, 4, 6, 7, 8 can mostly run in sequence.
