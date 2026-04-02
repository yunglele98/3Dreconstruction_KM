# Unreal Engine 5 Import Guide — Kensington Market

Complete import pipeline: 1,223 buildings + LODs + collision + 20 urban element categories + vegetation + Megascans materials.

## Prerequisites

- Unreal Engine 5.4+
- Datasmith plugin enabled (Edit > Plugins > Datasmith Importer)
- Megascans plugin / Quixel Bridge
- 16 GB+ RAM recommended (scene is ~1,200 meshes)

## Step 1: Import Buildings via Datasmith

```
File > Import into Level > Datasmith
Select: outputs/exports/kensington_scene.udatasmith
```

**Import settings:**
- Scene Actors: StaticMeshActors
- Geometry: Static Meshes
- Materials: Create
- LODs: Import (the file includes LODGroup references)

This imports all 1,223 buildings with LOD groups and collision meshes. Buildings are positioned using SRID 2952 coordinates converted to UE centimetres.

**Manifests for reference:**
- `outputs/exports/unreal_import_manifest.json` — per-building actor list
- `outputs/exports/unity_manifest.json` — Unity equivalent

## Step 2: Configure Nanite

Run the Nanite configuration generator:
```bash
python scripts/unreal/configure_nanite.py
```

Output: `outputs/unreal/nanite_config.json`

For each building, the config specifies whether to enable Nanite (based on vertex count threshold, default 5,000 verts). Most Kensington buildings use traditional LODs since they're parametric meshes with moderate poly counts.

**In UE5:**
1. Select all imported StaticMesh assets in Content Browser
2. Right-click > Nanite > Enable
3. For buildings flagged as `traditional_lod`, keep manual LODs instead

## Step 3: Level Setup (Lighting, Post-Process)

```bash
python scripts/unreal/generate_level_blueprint.py --month 6 --time 14
```

Output: `outputs/unreal/level_blueprint.json`

Apply these settings manually in UE5:

### Directional Light (Sun)
- Rotation: use pitch/yaw from the JSON (Toronto solar angles for chosen month/time)
- Enable "Atmosphere Sun Light"
- Shadow Cascades: 4
- Dynamic Shadow Distance: 20,000

### Sky & Atmosphere
- Add SkyAtmosphere actor
- Add SkyLight with Real Time Capture enabled
- Add ExponentialHeightFog (fog density 0.005 for Toronto lake-effect haze)

### Post-Process Volume
- Infinite Extent: true
- Global Illumination: Lumen (Scene Lighting Quality: 3)
- Reflections: Lumen
- Exposure: Manual (EV100 range 6-16)
- Colour grading: warm white balance (6200K), slight desaturation

## Step 4: Assign Megascans Materials

```bash
python scripts/unreal/assign_megascans.py
```

Output: `outputs/unreal/megascans_assignments.json`

Each building gets a Megascans surface mapped by LAB colour distance:
- **exact** (Delta-E < 10): Direct Megascans surface, no tint needed
- **close** (Delta-E 10-25): Megascans surface + colour tint override
- **approximate** (Delta-E > 25): Megascans base + significant tint

**In UE5:**
1. Import Megascans surfaces via Quixel Bridge
2. Create Material Instances for each surface ID
3. Apply per-building using the assignments JSON
4. For buildings needing tint: set `Base Color Tint` parameter to `tint_override` hex

## Step 5: Place Vegetation (PCG)

```bash
python scripts/unreal/place_vegetation.py
```

Output: `outputs/unreal/vegetation_pcg.json`

Contains ~1,050 tree spawn points with:
- Species (Norway Maple, Honey Locust, Linden, Ginkgo, Silver Maple, Callery Pear)
- Location (WGS84 coordinates)
- Size variation (70-100% of mature height)
- Health status (good/fair/poor)
- Street classification and planter type

**PCG setup in UE5:**
1. Create PCG Graph for street trees
2. Import spawn points from JSON as PCG data source
3. Set up species-to-mesh mapping using `ue_mesh` paths
4. Apply biome rules (spacing, setback) per street type

## Step 6: Import Urban Elements

27 pre-built import bundle scripts cover all urban element categories:

| Category | Script | Elements |
|----------|--------|----------|
| Street Trees | `build_unreal_tree_import_bundle.py` | Trees, canopy, roots |
| Street Furniture | `build_unreal_street_furniture_import_bundle.py` | Benches, planters, bollards |
| Signs | `build_unreal_sign_import_bundle.py` | Business signs, street signs |
| Poles | `build_unreal_pole_import_bundle.py` | Light poles, utility poles |
| Alleys | `build_unreal_alley_import_bundle.py` | Alley geometry, fences |
| Garages | `build_unreal_alley_garage_import_bundle.py` | Rear garages |
| Ground | `build_unreal_ground_import_bundle.py` | Sidewalks, roads |
| Fences | `build_unreal_fence_gate_import_bundle.py` | Fences, gates |
| Parking | `build_unreal_parking_import_bundle.py` | Parking lots, driveways |
| Transit | `build_unreal_transit_stop_import_bundle.py` | TTC stops |
| Intersections | `build_unreal_intersection_import_bundle.py` | Crosswalks, signals |
| Waste | `build_unreal_waste_import_bundle.py` | Bins, dumpsters |
| Bike Racks | `build_unreal_bikerack_import_bundle.py` | Ring-and-post, wave |
| Utilities | `build_unreal_utility_import_bundle.py` | Hydrants, meters, boxes |
| Park Furniture | `build_unreal_park_furniture_import_bundle.py` | Benches, tables |
| Accessibility | `build_unreal_accessibility_import_bundle.py` | Ramps, tactile paving |
| Hardscape | `build_unreal_vertical_hardscape_import_bundle.py` | Retaining walls |
| Service | `build_unreal_service_backlot_import_bundle.py` | Service areas |
| Road Markings | `build_unreal_roadmark_decal_placements.py` | Lane lines, crossings |
| Graffiti | `build_unreal_graffiti_texture_import_manifest.py` | Decal textures |

Run all bundles:
```bash
for script in scripts/build_unreal_*_import_bundle.py; do
    python "$script" 2>&1 | tail -1
done
```

## Step 7: Collision & Physics

All 1,223 buildings have `_collision.fbx` files (convex hull at 10% decimation). These are referenced in the Datasmith XML as `<CollisionMesh>` elements.

**In UE5:**
- Collision meshes auto-import with Datasmith
- Verify: select any building > Details > Collision > Complex Collision Mesh should be set
- For walkthrough: ensure Player Collision is enabled on all collision meshes

## Step 8: Verify

Run the export validation:
```bash
python scripts/validate_all_exports.py
```

Expected: 7/7 checks pass (FBX, LODs, collision, CityGML, 3D Tiles, Datasmith, Unity).

## Coordinate System

| System | Units | Origin |
|--------|-------|--------|
| SRID 2952 | metres | NAD83 MTM Zone 10 |
| UE5 | centimetres | Scene centre (Augusta/Baldwin) |
| Conversion | x100 | SRID → UE: multiply by 100, swap Y/Z |

Scene centre in SRID 2952: X=312672.94, Y=4834994.86

## Performance Notes

- **Nanite**: Enable only on high-poly buildings (>5,000 verts). Most parametric buildings are under this threshold.
- **Virtual Shadow Maps**: Enable for Lumen compatibility.
- **World Partition**: Recommended for the full 1,200+ building scene.
- **Streaming**: Set streaming distance to 500m for urban walkthrough.
- **LOD distances**: LOD0 (full), LOD1 at 50m, LOD2 at 100m, LOD3 (bbox) at 200m.
