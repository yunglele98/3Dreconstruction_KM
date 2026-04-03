# TASK-20260403-003: Batch render all buildings (V1 renders)

- **priority**: high
- **stage**: 4-GENERATE
- **estimated_effort**: large (GPU-bound, ~4-8 hours)
- **depends_on**: TASK-20260403-001

## Description

No renders exist in `outputs/buildings_renders_v1/`. Need initial batch render of all 1,050 buildings for Phase 0 visual audit comparison against field photos. Requires Blender 5.1 CLI and GPU.

## Commands

```bash
blender --background --python generate_building.py -- --params params/ --output-dir outputs/buildings_renders_v1/ --batch-individual --render --skip-existing
```

## Acceptance

- 1,000+ `.png` renders in `outputs/buildings_renders_v1/`
- `batch.manifest.json` written with completion stats
- Failed buildings < 5%
