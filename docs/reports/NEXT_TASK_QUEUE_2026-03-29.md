# Next Task Queue — 2026-03-29

## Completed Today

- [x] Fix 284 inflated heights (TASK-20260327-017)
- [x] Reconcile 168 material mismatches (TASK-MATERIAL-AUDIT)
- [x] Fix 8 window count mismatches (TASK-20260327-016)
- [x] Deep facade backfill: 1,138 buildings → 100% coverage
- [x] Multi-volume expansion: 20 wide buildings
- [x] Generation defaults applied: 1,241 buildings
- [x] Test expansion: 89 → 165 tests
- [x] All audits refreshed
- [x] Export deliverables: CSV, JSON, GeoJSON, HTML
- [x] Schema validation + auto-fix
- [x] Changelog + dashboard

## P0 — Requires Local Machine

- [ ] DB writeback: `python scripts/writeback_to_db.py`
- [ ] GIS scene regen: `python scripts/export_gis_scene.py`

## P1 — Blender Rendering

- [ ] Test regen (10 buildings): `blender --background --python generate_building.py -- --params params/ --batch-individual --match "Baldwin" --limit 10 --render --output-dir outputs/test_regen/`
- [ ] Full batch render (1,241 buildings): `blender --background --python generate_building.py -- --params params/ --batch-individual --render --output-dir outputs/full/`
- [ ] SSIM photo-vs-render comparison after regen

## P2 — 3D Reconstruction

- [ ] GLOMAP binary update (replace COLMAP mapper)
- [ ] Pilot photogrammetry: 5 buildings with best photo coverage
- [ ] RealESRGAN upscale pilot (photo enhancement before reconstruction)

## P3 — Web/Engine Export

- [ ] GLB web export batch (Blender → glTF for web viewer)
- [ ] Unreal Engine import bundle generation (47 UE scripts exist, need data)

## P4 — Data Gaps

- [ ] Fix 46 missing bay_window decorative elements (HCD mentions, not in params)
- [ ] Fix 1 missing quoin (1A Leonard Ave)
- [ ] Resolve 140 storefront_inconsistency issues
- [ ] Resolve 63 suspicious_dimensions issues

## Sync Command (after local work)

```powershell
robocopy C:\Users\liam1\blender_buildings\params D:\liam1_transfer\blender_buildings\params /MIR
robocopy C:\Users\liam1\blender_buildings\scripts D:\liam1_transfer\blender_buildings\scripts /MIR
robocopy C:\Users\liam1\blender_buildings\tests D:\liam1_transfer\blender_buildings\tests /MIR
robocopy C:\Users\liam1\blender_buildings\outputs D:\liam1_transfer\blender_buildings\outputs /E
robocopy C:\Users\liam1\blender_buildings\docs D:\liam1_transfer\blender_buildings\docs /E
```
