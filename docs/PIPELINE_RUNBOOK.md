# Pipeline Runbook — Kensington Market 3D Heritage Reconstruction

Step-by-step guide for running the complete V7 pipeline from raw data to deliverables.

## Prerequisites

- Python 3.10+ with: geopandas, osmnx, momepy, lxml, shapely
- Blender 5.0+ / 5.1 (for Stage 4-6)
- PostgreSQL 18 with PostGIS (for Stage 0)
- ~20 GB disk for outputs

## Quick Status Check

```bash
python scripts/validate_all_exports.py          # 7-check export validation
python scripts/monitor/sprint_progress.py       # sprint progress vs targets
python scripts/run_blender_buildings_workflows.py dashboard --once-json
```

## Stage 0: ACQUIRE

```bash
# Export building params from PostGIS
python scripts/export_db_params.py --overwrite

# Photo matching
python scripts/match_photos_to_params.py
```

## Stage 1: SENSE (GPU)

```bash
# Depth maps (Depth Anything v2)
python scripts/sense/extract_depth.py --model depth-anything-v2 --input "PHOTOS KENSINGTON/" --output depth_maps/

# Facade segmentation (YOLOv11 + SAM2)
python scripts/sense/segment_facades.py --input "PHOTOS KENSINGTON/" --output segmentation/ --model yolov11+sam2

# Surface normals
python scripts/sense/extract_normals.py --model dsine --input "PHOTOS KENSINGTON/"

# Signage OCR
python scripts/sense/extract_signage.py --model paddleocr --input "PHOTOS KENSINGTON/" --output signage/

# Feature matching for photogrammetry
python scripts/sense/extract_features.py --model lightglue+superpoint --input "PHOTOS KENSINGTON/" --output features/
```

## Stage 2: RECONSTRUCT

```bash
# Find photogrammetry candidates (3+ photos)
python scripts/reconstruct/select_candidates.py --params params/ --photos "PHOTOS KENSINGTON/" --min-views 3

# Per-building COLMAP
python scripts/reconstruct/run_photogrammetry.py --candidates reconstruction_candidates.json --output point_clouds/colmap/

# Per-street block COLMAP
python scripts/reconstruct/run_photogrammetry_block.py --block-graph outputs/spatial/adjacency_graph.json

# Single-view 3D (DUSt3R)
python scripts/reconstruct/run_dust3r.py --input "PHOTOS KENSINGTON/" --params params/ --max-views 2

# Retopologize photogrammetric meshes
python scripts/reconstruct/retopologize.py --input meshes/raw/ --output meshes/retopo/ --method instant-meshes

# Gaussian splats
python scripts/reconstruct/train_splats.py --input point_clouds/colmap/ --output splats/
```

## Stage 3: ENRICH (run in order, each idempotent)

```bash
python scripts/translate_agent_params.py
python scripts/enrich_skeletons.py
python scripts/enrich_facade_descriptions.py
python scripts/normalize_params_schema.py
python scripts/patch_params_from_hcd.py
python scripts/infer_missing_params.py

# Fusion scripts (1,035 buildings with depth+segmentation data)
python scripts/enrich/fuse_depth.py --depth-maps depth_maps/ --params params/
python scripts/enrich/fuse_segmentation.py --segmentation segmentation/ --params params/
python scripts/enrich/fuse_signage.py --signage signage/ --params params/

# Deep facade analysis (3D-reconstruction-grade observations)
python scripts/deep_facade_pipeline.py merge-street baldwin --promote
python scripts/deep_facade_pipeline.py audit

# Post-enrichment
python scripts/rebuild_colour_palettes.py
python scripts/diversify_colour_palettes.py
python scripts/enrich_storefronts_advanced.py
python scripts/enrich_porch_dimensions.py
python scripts/infer_setbacks.py
python scripts/consolidate_depth_notes.py
python scripts/build_adjacency_graph.py
python scripts/analyze_streetscape_rhythm.py
```

## Stage 4: GENERATE (Blender)

```bash
# Single building
blender --background --python generate_building.py -- --params params/22_Lippincott_St.json

# All buildings (batch)
blender --background --python generate_building.py -- --params params/ --batch-individual --skip-existing
```

## Stage 5: EXPORT (Blender batch)

```bash
# FBX export (run inside Blender)
blender --background --python scripts/fast_fbx_export.py -- --chunk outputs/fbx_chunk.txt

# LOD generation
blender --background --python scripts/fast_lod_generate.py -- --chunk outputs/lod_chunk.txt

# Collision meshes
blender --background --python scripts/fast_collision_generate.py -- --chunk outputs/collision_chunk.txt
```

## Stage 6: ENGINE MANIFESTS

```bash
python scripts/build_unreal_datasmith.py
python scripts/build_unity_prefab_manifest.py

# Unreal-specific
python scripts/unreal/generate_level_blueprint.py
python scripts/unreal/configure_nanite.py
python scripts/unreal/place_vegetation.py
python scripts/unreal/assign_megascans.py
```

## Stage 7: SPATIAL EXPORTS

```bash
python scripts/export/export_citygml.py --lod 2 --output citygml/kensington_lod2.gml
python scripts/export/export_3dtiles.py --output tiles_3d/
python scripts/export/build_web_data.py
python scripts/export/build_web_geojson.py
python scripts/export/build_web_app_data.py
```

## Stage 8: URBAN ANALYSIS

```bash
python scripts/analyze/network_analysis.py --output outputs/spatial/network_analysis.json
python scripts/analyze/morphology.py --output outputs/spatial/morphology.json
python scripts/analyze/shadow_analysis.py --output outputs/spatial/shadow_analysis.json
python scripts/analyze/accessibility.py --output outputs/spatial/accessibility.json
python scripts/analyze/viewshed.py --output outputs/spatial/viewshed.json
```

## Stage 9: HERITAGE

```bash
python scripts/heritage/parse_hcd_pdf.py
python scripts/heritage/extract_hcd_features.py
python scripts/heritage/heritage_score.py
python scripts/heritage/generate_heritage_report.py
python scripts/heritage/crossref_hcd_params.py
```

## Stage 10: SCENARIOS

```bash
# Apply all 5 scenarios
for scenario in 10yr_gentle_density 10yr_green_infra 10yr_heritage_first 10yr_mixed_use 10yr_mobility; do
    python scripts/planning/apply_scenario.py --scenario scenarios/$scenario/ --output outputs/scenarios/$scenario/
done

# Impact analysis
for scenario in 10yr_gentle_density 10yr_green_infra 10yr_heritage_first 10yr_mixed_use 10yr_mobility; do
    python scripts/planning/analyze_density.py --baseline params/ --scenario outputs/scenarios/$scenario/ --output scenarios/$scenario/density_analysis.json
    python scripts/planning/heritage_impact.py --baseline params/ --scenario scenarios/$scenario/ --output scenarios/$scenario/heritage_impact.json
    python scripts/planning/shadow_impact.py --baseline params/ --scenario scenarios/$scenario/ --output scenarios/$scenario/shadow_analysis.json
done

# Cross-scenario comparison
python scripts/planning/compare_scenarios.py --scenarios scenarios/10yr_* --output outputs/scenario_comparison.json
python scripts/analyze/enrich_scenario_metrics.py
```

## Stage 11: URBAN ELEMENTS

```bash
for script in scripts/build_unreal_*_import_bundle.py; do python "$script"; done
```

## Stage 12: QA + DELIVERABLES

```bash
python scripts/generate_qa_report.py
python scripts/export_building_summary_csv.py
python scripts/export_geojson.py
python scripts/export_street_profile_json.py
python scripts/validate_all_exports.py
python -m pytest tests/ -q
```

## Key Outputs

| Output | Path | Contents |
|--------|------|----------|
| Building params | `params/*.json` | ~1,062 enriched building definitions |
| FBX exports | `outputs/exports/` | Batch export ready (Blender-dependent) |
| CityGML | `citygml/kensington_lod2.gml` | ~1,064 buildings |
| 3D Tiles | `tiles_3d/tileset.json` | ~1,064 building tiles |
| Datasmith | `outputs/exports/kensington_scene.udatasmith` | UE5 scene (Blender-dependent) |
| Spatial analysis | `outputs/spatial/` | network, morphology, shadow, accessibility |
| Heritage | `outputs/heritage/` | scores, features, reports (1,059 HCD buildings) |
| Scenarios | `scenarios/*/` | 5 scenario overlays + impact analysis |
| QA report | `outputs/qa_report.json` | parameter quality scores |
| Deliverables | `outputs/deliverables/` | CSV, GeoJSON, street profiles |
