# API Reference — Kensington Market 3D Pipeline

404 Python scripts in the `scripts/` directory. Run with `python scripts/<path>`.

## Stage 0: ACQUIRE

| Script | Description | Key Args |
|--------|-------------|----------|
| `export_db_params.py` | Export building params from PostGIS | `--overwrite`, `--street`, `--address` |
| `acquire/acquire_streetview.py` | Download Mapillary street view | `--source`, `--bbox` |
| `acquire/acquire_ipad_scans.py` | Ingest iPad LiDAR scans | `--input`, `--output` |
| `acquire/acquire_extract_elements.py` | Extract elements from LiDAR | `--input`, `--output` |
| `acquire/acquire_open_data.py` | Download open data sources | `--sources` |
| `acquire/build_asset_index.py` | Build asset library index | — |
| `acquire/download_ambientcg.py` | Download AmbientCG PBR textures | — |
| `acquire/download_polyhaven.py` | Download Poly Haven assets | — |

## Stage 1: SENSE

| Script | Description | Key Args |
|--------|-------------|----------|
| `sense/extract_depth.py` | Depth maps via Depth Anything v2 | `--input`, `--output`, `--model` |
| `sense/segment_facades.py` | Facade segmentation (YOLO+SAM2) | `--input`, `--output`, `--model` |
| `sense/extract_features.py` | LightGlue+SuperPoint keypoints | `--input-dir`, `--output-dir`, `--limit` |
| `sense/extract_normals.py` | Surface normals (DSINE) | `--input`, `--output` |
| `sense/extract_signage.py` | OCR signage extraction | `--input`, `--output` |

## Stage 2: RECONSTRUCT

| Script | Description | Key Args |
|--------|-------------|----------|
| `reconstruct/select_candidates.py` | Find buildings with 3+ photos | `--min-views`, `--street` |
| `reconstruct/run_photogrammetry.py` | Per-building COLMAP | `--address`, `--street`, `--dense` |
| `reconstruct/run_photogrammetry_block.py` | Per-street block COLMAP | `--street`, `--dense`, `--list-blocks` |
| `reconstruct/run_dust3r.py` | DUSt3R single-view 3D | `--input`, `--output` |
| `reconstruct/train_splats.py` | Gaussian splatting training | `--input`, `--batch`, `--prepare-cloud` |
| `reconstruct/clip_block_mesh.py` | Clip block mesh per building | `--block-mesh`, `--footprints` |
| `reconstruct/retopologize.py` | Instant Meshes quad remesh | `--input`, `--target-faces` |
| `reconstruct/calibrate_defaults.py` | Calibrate element defaults | `--elements` |
| `reconstruct/extract_elements.py` | Extract elements from meshes | `--meshes`, `--segmentation` |

## Stage 3: ENRICH

| Script | Description | Key Args |
|--------|-------------|----------|
| `translate_agent_params.py` | Convert agent flat output to structured | — |
| `enrich_skeletons.py` | Fill missing params from typology/era | — |
| `enrich_facade_descriptions.py` | Generate prose facade descriptions | — |
| `normalize_params_schema.py` | Normalize boolean/string fields | — |
| `patch_params_from_hcd.py` | Merge HCD decorative features | — |
| `infer_missing_params.py` | Final gap-fill (run LAST) | — |
| `enrich/fuse_depth.py` | Fuse depth map data into params | `--depth-maps`, `--params` |
| `enrich/fuse_segmentation.py` | Fuse segmentation results | `--segmentation`, `--params` |
| `rebuild_colour_palettes.py` | Rebuild colour palettes | — |
| `diversify_colour_palettes.py` | Diversify similar palettes | — |
| `match_photos_to_params.py` | Match field photos to buildings | — |
| `build_adjacency_graph.py` | Build spatial adjacency graph | — |
| `analyze_streetscape_rhythm.py` | Analyze streetscape patterns | — |
| `enrich/fuse_signage.py` | Fuse OCR signage results | `--signage`, `--params` |
| `enrich/fuse_lidar.py` | Fuse LiDAR data | `--lidar`, `--params` |
| `enrich/fuse_photogrammetry.py` | Fuse photogrammetric meshes | `--meshes`, `--params` |
| `deep_facade_pipeline.py` | Deep facade analysis workflow | `merge`, `merge-street`, `promote`, `audit`, `report` |
| `enrich_storefronts_advanced.py` | Advanced storefront enrichment | — |
| `enrich_porch_dimensions.py` | Porch dimension inference | — |
| `infer_setbacks.py` | Setback inference | — |
| `consolidate_depth_notes.py` | Consolidate depth notes | — |

## Stage 4: GENERATE (Blender)

| Script | Description | Key Args |
|--------|-------------|----------|
| `generate_building.py` | Main parametric generator | `--params`, `--batch-individual`, `--render` |

## Stage 5: TEXTURE

| Script | Description | Key Args |
|--------|-------------|----------|
| `texture/match_textures.py` | Match facade colour to PBR textures | `--params`, `--assets` |
| `texture/extract_pbr.py` | Extract normal/AO/roughness from photos | `--input`, `--method`, `--prepare-cloud` |
| `texture/upscale_textures.py` | RealESRGAN 4x upscale | `--input`, `--output`, `--scale` |
| `texture/project_textures.py` | Project photo onto mesh | `--mesh`, `--photo` |
| `texture/match_textures.py` | Match facade colour to PBR textures | `--params`, `--assets` |

## Stage 6: OPTIMIZE (Blender)

| Script | Description | Key Args |
|--------|-------------|----------|
| `generate_lods.py` | LOD generation | `--source-dir`, `--skip-existing` |
| `generate_collision_mesh.py` | Collision mesh generation | `--source-dir` |
| `optimize_meshes.py` | Pymeshlab mesh cleanup | `--source-dir` |
| `validate_export_pipeline.py` | Trimesh QA on exports | `--source-dir` |

## Stage 7-8: ASSEMBLE + EXPORT

| Script | Description | Key Args |
|--------|-------------|----------|
| `export_gis_scene.py` | Export GIS scene JSON | — |
| `export_building_fbx.py` | Single FBX export (Blender) | `--address` |
| `batch_export_unreal.py` | Batch FBX for Unreal | `--source-dir` |
| `export_deliverables.py` | Generate all deliverables | — |
| `export/export_citygml.py` | CityGML LOD2/3 export | `--lod`, `--output` |
| `export/export_3dtiles.py` | 3D Tiles tileset | `--input`, `--output` |
| `export/export_potree.py` | Potree point cloud conversion | `--input`, `--output` |
| `export/package_splats.py` | Package splats for web viewer | `--input`, `--output` |
| `export/build_web_data.py` | Slim params JSON for web | `--output` |
| `export/build_web_app_data.py` | Full web app data package | — |
| `export/build_web_geojson.py` | Building footprints GeoJSON | — |

## Stage 9: VERIFY

| Script | Description | Key Args |
|--------|-------------|----------|
| `qa_params_gate.py` | QA parameter gate | `--ci` |
| `audit_params_quality.py` | Audit parameter quality | — |
| `audit_structural_consistency.py` | Structural consistency check | — |
| `audit_generator_contracts.py` | Generator contract verification | — |
| `generate_qa_report.py` | Generate QA report | — |
| `verify/visual_regression.py` | Visual regression testing | — |

## Stage 10: MONITOR

| Script | Description | Key Args |
|--------|-------------|----------|
| `monitor/morning_report.py` | Overnight results summary | `--format` |
| `monitor/error_recovery.py` | Auto-fix common errors | — |
| `monitor/batch_health.py` | Batch job health check | — |
| `monitor/sprint_progress.py` | Sprint progress tracker | `--format` |
| `sentry_init.py` | Sentry error tracking setup | — |

## Stage 11: SCENARIOS

| Script | Description | Key Args |
|--------|-------------|----------|
| `planning/apply_scenario.py` | Apply scenario overlay | `--scenario`, `--dry-run` |
| `planning/analyze_density.py` | Density metrics comparison | `--baseline`, `--scenario` |
| `planning/heritage_impact.py` | Heritage impact assessment | `--scenario` |
| `planning/shadow_impact.py` | Shadow impact estimation | `--scenario`, `--season` |
| `planning/compare_scenarios.py` | Cross-scenario comparison | `--scenarios` |
| `planning/generate_scenarios.py` | Generate scenario data | — |

## Urban Analysis

| Script | Description | Key Args |
|--------|-------------|----------|
| `analyze/network_analysis.py` | Street network metrics (OSMnx) | `--output` |
| `analyze/morphology.py` | Urban morphology (momepy) | `--output` |
| `analyze/accessibility.py` | Walkability scoring | `--output` |
| `analyze/shadow_analysis.py` | Annual sun hours estimation | `--output` |
| `analyze/viewshed.py` | Visibility from streets | `--output` |

## Heritage

| Script | Description | Key Args |
|--------|-------------|----------|
| `heritage/extract_hcd_features.py` | Extract features from HCD text | `--dry-run`, `--address` |
| `heritage/heritage_score.py` | Heritage significance scoring | `--output` |
| `heritage/generate_heritage_report.py` | Per-street heritage reports | `--street`, `--output` |
| `heritage/crossref_hcd_params.py` | Cross-reference HCD vs params | — |
| `heritage/parse_hcd_pdf.py` | Parse HCD PDF document | — |
| `heritage/deep_parse_update.py` | Deep parse HCD updates | — |

## Phase 0: Visual Audit

| Script | Description | Key Args |
|--------|-------------|----------|
| `visual_audit/run_full_audit.py` | Full render-vs-photo audit | `--limit` |
| `visual_audit/run_audit.py` | Core audit runner | — |
| `visual_audit/compare_render_to_photo.py` | SSIM comparison | — |
| `visual_audit/pair_renders_to_photos.py` | Match renders to field photos | — |
| `visual_audit/score_and_rank.py` | Score and rank buildings | — |
| `visual_audit/element_gaps.py` | Detect missing elements | — |
| `visual_audit/layer2_structural.py` | Structural comparison layer | — |
| `visual_audit/layer4_gemini_api.py` | Gemini vision API comparison | — |
| `visual_audit/merge_gemini_analysis.py` | Merge Gemini analysis results | — |
| `visual_audit/apply_audit_fixes.py` | Auto-apply audit fixes | — |
| `visual_audit/colmap_priority.py` | COLMAP priority queue | — |
| `visual_audit/fusion.py` | Multi-layer fusion | — |
| `visual_audit/generate_dashboard.py` | Generate audit dashboard | — |
| `visual_audit/generate_grid_html.py` | Generate comparison grid | — |
| `visual_audit/street_summary.py` | Per-street summary stats | — |

## ML Training

| Script | Description | Key Args |
|--------|-------------|----------|
| `train/prepare_training_data.py` | Select best photos for annotation | `--limit`, `--dry-run` |
| `train/export_coco.py` | Label Studio -> COCO format | `--input`, `--split` |
| `train/train_yolo_facade.py` | Fine-tune YOLOv11 | `--data`, `--epochs`, `--model` |
| `train/adapt_facades.py` | CMP Facade domain adaptation | `--cmp-dir`, `--method` |
| `train/evaluate_model.py` | FiftyOne model evaluation | `--model`, `--launch` |
| `train/bootstrap_annotations.py` | Bootstrap annotation data | — |
| `train/generate_pseudo_labels.py` | Generate pseudo-labels for training | — |
| `train/run_training_pipeline.py` | Full training pipeline runner | — |

## Cloud GPU

| Script | Description | Key Args |
|--------|-------------|----------|
| `cloud/prepare_session.py` | Package data for cloud GPU | `--type`, `--limit`, `--list` |
