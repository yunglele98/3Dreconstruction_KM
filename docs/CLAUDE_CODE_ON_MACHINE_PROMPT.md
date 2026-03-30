# Claude Code On-Machine Prompt — Kensington Market Buildings

Paste this entire prompt into Claude Code on the Alienware Aurora R9.
Working directory: `C:\Users\liam1\blender_buildings` (writable copy of `D:\liam1_transfer\blender_buildings`).

Read `CLAUDE.md` thoroughly before starting any work.

---

## Machine Context

**Hardware:** Alienware Aurora R9, i7-9700 (8C/8T), RTX 2080 SUPER 8GB, 32GB DDR4 2400MHz, NVMe SSD.
**Blender:** 5.1.0 at `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe`
**Python:** 3.12+ (system), plus Blender's bundled Python.
**COLMAP:** `C:\Tools\COLMAP\COLMAP.bat`
**OpenMVS:** `C:\Tools\OpenMVS\` (InterfaceCOLMAP.exe, DensifyPointCloud.exe, ReconstructMesh.exe, TextureMesh.exe)
**PostgreSQL:** 18, localhost:5432, db=kensington, user=postgres, pw=test123

**Style rules:** 4-space indent, snake_case, pathlib, json indent=2, encoding="utf-8". Stamp `_meta` with fix name + UTC timestamp. NEVER overwrite `total_height_m`, `facade_width_m`, `facade_depth_m`, `site.*`, `city_data.*`, `hcd_data.*`.

---

## Current Data State (after Cowork enrichment — all verified)

Everything below was already applied in Cowork. Do NOT re-run these scripts with `--apply`:

| Metric | Value |
|---|---|
| Active buildings | 1,241 |
| Tests passing | 1,627 (56 test files) |
| QA score | 100.0% zero-issue, avg 100.0/100 |
| Colour palettes (4/4 hex) | 1,241/1,241 (100%) |
| Unique facade hexes | 949 |
| Unique trim/roof/mortar | 615 / 368 / 857 |
| Monotone streets | 0 (was 15) |
| Photo matched | 1,224/1,241 (98.6%) |
| Deep facade analysis | 1,241/1,241 (100%) |
| Windows detail | 1,241/1,241 |
| Doors detail | 1,241/1,241 |
| Storefronts (awning/signage) | 569 (516 awnings, 396 signage) |
| Porches with dimensions | 87/88 |
| Setback coverage | 1,241/1,241 (800 from DB + 441 inferred) |
| Depth notes complete | 1,241/1,241 |
| Multi-volume buildings | 27 |
| Adjacency graph | 1,219 entries, 287 blocks |
| Generator contract warnings | 0 |

Scripts already applied (do NOT re-run): `rebuild_colour_palettes.py`, `diversify_colour_palettes.py`, `match_photos_to_params.py`, `enrich_storefronts_advanced.py`, `enrich_porch_dimensions.py`, `infer_setbacks.py`, `consolidate_depth_notes.py`, `build_adjacency_graph.py`, `analyze_streetscape_rhythm.py`, `audit_generator_contracts.py`, `fix_generator_contract_gaps.py`, `generate_qa_report.py`, `export_building_summary_csv.py`, `export_geojson.py`, `export_street_profile_json.py`.

**Session 7 changes (2026-03-29):** Corrected 6 building heights (160 Baldwin, 297/317 College, 311 Augusta, 355 College, 35 Bellevue). Improved QA height_mismatch filter to skip aggregated massing data. Added 3 photo matching strategies (composite_prefix, alias_expansion, trailing address). Deleted 7.7GB archive bloat. Added docstrings to 20 scripts. Cleaned 35 smoke test dirs. 270 scripts, 56 test files, 1,627 tests all passing.

---

## PHASE 1 — Batch Regeneration (~4-8 hours GPU)

All 1,241 buildings need regeneration since params have been heavily enriched with new colours, storefronts, porches, setbacks, and depth notes.

### 1A. Run regeneration

```powershell
cd C:\Users\liam1\blender_buildings

# Full batch regen (25 batches of 50, pre-built)
.\outputs\regen_batches\run_all.ps1

# OR if run_all.ps1 has issues, use direct command:
blender --background --python generate_building.py -- --params params/ --batch-individual --skip-existing --output-dir outputs/full_v3/
```

### 1B. Verify regeneration

```bash
python scripts/verify_regen.py
python scripts/fingerprint_params.py   # re-fingerprint to mark as fresh
```

### 1C. Smoke test 5 typology samples

```powershell
$samples = @("22_Lippincott_St", "81_Bellevue_Ave", "103_Bellevue_Ave", "200_Augusta_Ave", "132_Bellevue_Ave")
foreach ($s in $samples) {
    blender --background --python generate_building.py -- --params "params/$s.json" --render --output-dir outputs/qa_regen/
}
```

Compare renders against field photos in `PHOTOS KENSINGTON/` for visual QA.

---

## PHASE 2 — FBX Export + Material Baking (~3-5 hours GPU)

### 2A. Test export on 5 buildings first

```powershell
$testBuildings = @(
    "outputs/full/22_Lippincott_St.blend",           # row house
    "outputs/full/81_Bellevue_Ave.blend",             # semi-detached
    "outputs/full/103_Bellevue_Ave.blend",            # bay-and-gable
    "outputs/full/200_Augusta_Ave.blend",             # storefront
    "outputs/full/132_Bellevue_Ave.blend"             # multi-volume
)
foreach ($b in $testBuildings) {
    $addr = [System.IO.Path]::GetFileNameWithoutExtension($b)
    blender --background "$b" --python scripts/export_building_fbx.py -- --address "$addr" --texture-size 2048
}
```

Verify outputs in `outputs/exports/<address>/` — should have `.fbx` + `textures/` + `export_meta.json`.

### 2B. Batch export all

```powershell
blender --background --python scripts/batch_export_unreal.py -- --source-dir outputs/full/ --skip-existing
```

This produces `outputs/exports/manifest.csv` mapping every building to its FBX + textures.

---

## PHASE 3 — LOD Generation + Collision (~2-4 hours GPU)

### 3A. Generate 4 LOD levels

```powershell
blender --background --python scripts/generate_lods.py -- --source-dir outputs/full/ --output-dir outputs/exports/lods/ --skip-existing
```

LOD0 (full detail) → LOD1 (50%) → LOD2 (15%, no decorative elements) → LOD3 (box massing).

### 3B. Generate collision meshes

```powershell
blender --background --python scripts/generate_collision_mesh.py -- --source-dir outputs/full/ --skip-existing
```

Convex hull per building for Unreal/Unity physics.

---

## PHASE 4 — Texture Atlas + Scene Export (~1-2 hours)

### 4A. Bake texture atlas

```powershell
blender --background --python scripts/build_texture_atlas.py -- --tile-size 512 --atlas-size 4096
```

Packs all unique procedural materials (brick variants, paint, trim, roof) into one 4K atlas with UV mapping JSON. Reduces draw calls from hundreds to ~10.

### 4B. Full scene export

```powershell
# Web preview (single GLB with Draco compression)
blender --background --python scripts/export_full_scene.py -- --format glb

# Partitioned FBX per street for Unreal
blender --background --python scripts/export_full_scene.py -- --format fbx --partition-by-block
```

---

## PHASE 5 — Post-Processing (standalone Python, ~30 min)

### 5A. Install dependencies

```bash
pip install pymeshlab trimesh
```

### 5B. Mesh optimization

```bash
python scripts/optimize_meshes.py --input-dir outputs/exports/
```

Removes duplicate verts, fixes non-manifold edges, recomputes normals. Reports per-building stats.

### 5C. Export validation

```bash
python scripts/validate_export_pipeline.py --exports-dir outputs/exports/
```

Checks: watertight, normals consistent, no degenerate faces, UV coverage >95%, LOD face counts monotonically decreasing, collision mesh convex.

### 5D. Unreal/Unity scene descriptors

```bash
python scripts/build_unreal_datasmith.py
python scripts/build_unity_prefab_manifest.py
python scripts/map_megascans_materials.py --megascans-lib "C:\Tools\Megascans\Downloaded"
```

---

## PHASE 6 — DB Writeback + Photogrammetry (optional)

### 6A. Database writeback

```bash
python scripts/writeback_to_db.py --migrate   # adds new columns
python scripts/writeback_to_db.py             # writes all enriched params
```

### 6B. Photogrammetry (3 candidate buildings)

Best candidates: Toronto Fire Station 315 (16 photos), St. Stephen's Church (18 photos), 160 Baldwin St (12 photos).

```powershell
python scripts/run_photogrammetry_batch.py --address "Toronto Fire Station 315" --quality medium
python scripts/run_photogrammetry_batch.py --all --skip-existing
python scripts/compare_photogrammetry_vs_parametric.py --all
pip install opencv-python-headless numpy
python scripts/extract_facade_textures.py --all --output-size 2048
```

---

## PHASE 7 — Machine Maintenance (between batches)

1. **Enable XMP in BIOS** (reboot): RAM 2400 → 2666 MHz
2. **Delete .blend1 backups** (~256 MB): `Get-ChildItem outputs -Recurse -Filter "*.blend1" | Remove-Item -Force`
3. **Compress archive/**: `7z a archive.7z archive/ -mx=5`
4. **Update Intel UHD 630 driver** via Intel Driver & Support Assistant
5. **Sync working copy**: `robocopy "D:\liam1_transfer\blender_buildings" "C:\Users\liam1\blender_buildings" /MIR /XD .git __pycache__ node_modules /XF *.blend1`

---

## Execution Order

```
Phase 1: Batch regen (4-8 hrs GPU, mostly unattended)
Phase 2: FBX export (3-5 hrs GPU, mostly unattended)
Phase 3: LODs + collision (2-4 hrs GPU)
Phase 4: Atlas + scene export (1-2 hrs)
Phase 5: Post-processing (30 min, standalone Python)
Phase 6: DB writeback + photogrammetry (optional, 2 hrs)
Phase 7: Maintenance (between batches)
```

Total: ~12-20 hours of compute, most of it unattended GPU batching.
Run `python -m pytest tests/ -p no:cacheprovider` after each phase to verify no regressions.
