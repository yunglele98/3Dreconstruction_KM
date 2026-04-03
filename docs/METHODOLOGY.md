# Methodology — Kensington Market 3D Heritage Reconstruction

## 1. Overview

This project reconstructs ~1,064 historic buildings in Toronto's Kensington Market neighbourhood as detailed 3D models for heritage documentation and urban planning analysis. The pipeline combines parametric generation, photogrammetry, machine learning, and GIS data fusion to produce multi-format outputs (Blender, Unreal Engine, CityGML, 3D Tiles, web viewer).

## 2. Study Area

- **Bounds:** Dundas St W (north), Bathurst St (east), College St (south), Spadina Ave (west)
- **Scope:** Market-facing side of perimeter streets only
- **CRS:** EPSG 2952 (NAD83 / Ontario MTM Zone 10)
- **Heritage designation:** Kensington Market Heritage Conservation District (HCD), designated under Part V of the Ontario Heritage Act

## 3. Data Sources

### 3.1 Primary Sources
- **PostGIS database** (`kensington`): 1,075 building assessment records with LiDAR heights, lot dimensions, HCD classification
- **Field photography:** 1,930 geotagged photos (March 2026, iPhone 15 Pro)
- **HCD Plan Vol. 2:** Per-building heritage statements, construction dates, architectural features
- **Toronto Open Data:** Building footprints (2D polygons), 3D massing models, road centerlines, street trees

### 3.2 Derived Sources
- **Depth maps:** Monocular depth estimates (Depth Anything v2), fused into 1,035 building params
- **Facade segmentation:** YOLOv11 + SAM2 instance segmentation
- **Feature matching:** LightGlue + SuperPoint keypoints for photogrammetry

## 4. Pipeline Architecture

### 4.1 Parametric Generation (Primary Method)
Each building is generated procedurally from a JSON parameter file containing:
- Dimensional data (height, width, depth from LiDAR/city data)
- Architectural features (from HCD plan + photo analysis)
- Material specifications (brick colour, trim, roof from observation)

The generator (`generate_building.py`, ~2,931-line orchestrator + 11 extracted modules totalling ~7,401 lines) executes 30+ sequential `create_*` functions within Blender's Python environment, producing walls, windows, doors, roofs, decorative elements, and storefronts. Modules: materials, geometry, walls, windows, doors, roofs, decorative, storefront, structure, colours.

### 4.2 Photogrammetric Reconstruction (When Available)
Buildings with 3+ field photos from different angles undergo COLMAP sparse+dense reconstruction. The resulting mesh is retopologized (Instant Meshes), then combined with parametric details for unseen faces.

### 4.3 Hybrid Selection
```
if retopologized_mesh exists AND photo_count >= 3 AND contributing:
    method = "photogrammetric"  # import mesh + procedural materials
else:
    method = "parametric"       # full procedural generation
```

## 5. Enrichment Pipeline

Eight sequential scripts enrich raw building parameters:
1. **translate_agent_params** — Converts flat agent output to structured data
2. **enrich_skeletons** — Fills gaps from typology/era lookup tables
3. **enrich_facade_descriptions** — Generates prose heritage descriptions
4. **normalize_params_schema** — Standardizes field formats
5. **patch_params_from_hcd** — Merges HCD Vol. 2 decorative features
6. **infer_missing_params** — Final gap-fill for 7 remaining keys
7. **deep_facade_pipeline** — Promote 3D-reconstruction-grade photo analysis to param fields
8. **diversify_colour_palettes** — Increase material variety across the district

Post-enrichment fusion scripts integrate depth maps (1,035 buildings), segmentation masks (1,035 buildings), signage OCR, and photo observations into params.

## 6. Quality Assurance

### 6.1 Visual Audit
Automated comparison of parametric renders against field photos using structural similarity (SSIM) and perceptual metrics. Produces a ranked priority queue for reconstruction refinement.

### 6.2 Parameter QA Gate
Validates all parameter files against the expected schema, checking for:
- Required fields present and correctly typed
- Height/width/depth within physical bounds
- HCD data consistency
- Colour hex validity

### 6.3 Generator Contract Verification
Ensures all 36 `create_*` functions in the generation chain produce valid Blender objects with correct naming prefixes for the join-by-prefix post-processing step.

### 6.4 Automated Test Suite
70 pytest test files (~20,000 lines) covering enrichment pipeline, generator contracts, asset export, spatial analysis, deep facade tooling, and Blender-adjacent utilities.

## 7. Urban Analysis

### 7.1 Network Analysis
Street network metrics (betweenness centrality, closeness centrality, connectivity) computed via OSMnx from OpenStreetMap data, assigned to buildings by nearest node.

### 7.2 Morphology
Building-level morphometric indicators (compactness, elongation, orientation, coverage ratio) computed via momepy from real building footprints.

### 7.3 Accessibility
Walking distance to amenities (transit, food, restaurants, parks) using Euclidean distance from OSM POI data. Composite walkability score (0-100).

### 7.4 Shadow Analysis
Annual sun hours per building estimated from heights, positions, and Toronto solar geometry across four seasons. Identifies buildings receiving critically low sunlight.

## 8. Scenario Framework

Five 10-year urban planning scenarios modelled as JSON overlays on baseline parameters:
1. **Heritage First** — Maximum preservation, facade restoration
2. **Gentle Density** — Laneway housing, coach houses, third floors
3. **Mixed Use** — Ground-floor commercial conversion
4. **Green Infrastructure** — Green roofs, street trees
5. **Sustainable Mobility** — Pedestrianization, bike infrastructure

Each scenario includes density analysis, heritage impact assessment, and shadow impact estimation.

## 9. Output Formats

| Format | Use Case | Coverage |
|--------|----------|----------|
| Blender `.blend` | Source models | ~1,064 buildings |
| FBX | Unreal Engine import | Batch export ready (Blender-dependent) |
| CityGML LOD2 | Heritage archives, GIS | ~1,064 buildings |
| 3D Tiles | Web viewer (CesiumJS) | ~1,064 building tiles |
| GeoJSON | Web platform (MapLibre) | ~1,062 footprints |
| Datasmith XML | Unreal scene assembly | ~1,064 actors + LOD groups |
| Unity manifest | Unity import | ~1,064 buildings |
| Heritage scores | Per-building significance | 374 HCD buildings scored |
| Scenario overlays | 5 planning scenarios | density/heritage/shadow analysis |

## 10. Limitations

- Rear and party-wall facades are procedurally estimated, not photo-verified
- Interior layouts are not modelled
- Vegetation and temporary structures are excluded
- Building heights use LiDAR averages, not per-corner measurements
- Material textures are procedural, not photo-projected (except photogrammetric buildings)
- Shadow analysis uses simplified solar geometry without terrain modelling
