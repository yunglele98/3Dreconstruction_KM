# Geometry Failures Remediation Report

## Status Summary
All 6 target addresses now pass degenerate_faces validation in their GLB sidecars.

## Gate Matrix
| Address | Watertight | Degenerate Faces | Materials.json |
|---|---|---|---|
| 100 Nassau St | WARN | PASS | PASS |
| 102 Nassau St | WARN | PASS | PASS |
| 103 Bellevue Ave | WARN | PASS | PASS |
| 10 Hickory St | WARN | PASS | PASS |
| 327 Bathurst St Sanderson Library | WARN | PASS | PASS |
| 75 Kensington Ave | WARN | PASS | PASS |

## Changes
1. Patched scripts/validate_export_pipeline.py to support materials.json list format.
2. Patched scripts/optimize_meshes.py for pymeshlab 2023+ compatibility.
3. Repaired GLB sidecars using 	rimesh area-based filtering.
