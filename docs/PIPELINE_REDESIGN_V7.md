# Pipeline Redesign V7

## Overview

V7 is a 12-stage hybrid pipeline for 3D reconstruction of ~1,064 historic Kensington Market buildings. It combines parametric generation (foundation), photogrammetry (ground truth), neural reconstruction (gap filling), ML segmentation (automation), and urban analysis (context). Deliverables target game engines (UE5/Unity), a web planning platform (CesiumJS), and heritage archives (CityGML).

## Pipeline Stages

| Stage | Name        | Description                                              | Key Scripts                                      |
|-------|-------------|----------------------------------------------------------|--------------------------------------------------|
| 0     | ACQUIRE     | Raw data ingestion (photos, PostGIS, LiDAR, street view) | `export_db_params.py`, `acquire_streetview.py`   |
| 1     | SENSE       | Depth, segmentation, normals, OCR, features              | `sense/extract_depth.py`, `sense/segment_facades.py` |
| 2     | RECONSTRUCT | COLMAP/OpenMVS photogrammetry, DUSt3R single-view        | `reconstruct/run_photogrammetry.py`, `reconstruct/run_dust3r.py` |
| 3     | ENRICH      | 6 existing + 5 fusion enrichment scripts                 | `enrich_skeletons.py`, `enrich/fuse_depth.py`    |
| 4     | GENERATE    | Hybrid selector: photogrammetric mesh or parametric      | `generate_building.py`                           |
| 5     | TEXTURE     | Procedural materials + PBR extraction + AI projection    | `texture/extract_pbr.py`, `texture/upscale_textures.py` |
| 6     | OPTIMIZE    | LOD generation, collision mesh, mesh repair               | `generate_lods.py`, `optimize_meshes.py`         |
| 7     | ASSEMBLE    | Buildings + 20 urban element categories + terrain        | `export_gis_scene.py`                            |
| 8     | EXPORT      | Datasmith, Unity, CityGML, 3D Tiles, Potree, web        | `export/export_citygml.py`, `export/export_3dtiles.py` |
| 9     | VERIFY      | pytest, param QA gate, visual regression, mesh validation | `qa_params_gate.py`, `verify/visual_regression.py` |
| 10    | MONITOR     | Sentry, n8n heartbeat, batch job health, dashboard       | `monitor/`, `agent_dashboard_server.py`          |
| 11    | SCENARIOS   | 5 urban planning scenarios as JSON overlays              | `planning/apply_scenario.py`, `planning/shadow_impact.py` |

## Generator Fallback Chain

Every `create_*` function follows: scanned element -> external asset library -> procedural generation.

## Hybrid Generation

Buildings with 3+ photos and a retopologized mesh use the photogrammetric path; all others use full parametric generation.

See CLAUDE.md for full technical details.
