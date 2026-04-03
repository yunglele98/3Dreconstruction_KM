# GPU Task Queue — Run on local machine with RTX 2080S + Blender 5.1

Priority order. Check `.gpu_lock` before starting any GPU job.

---

## 1. BATCH RENDER V1 (blocks everything downstream)

```bash
# Full batch (~4-8 hours, 1,050 buildings)
blender --background --python generate_building.py -- \
  --params params/ --output-dir outputs/buildings_renders_v1/ \
  --batch-individual --render --skip-existing

# Quick test first (5 buildings)
blender --background --python generate_building.py -- \
  --params params/ --output-dir outputs/buildings_renders_v1/ \
  --batch-individual --render --limit 5
```

**Expected output:** 1,050 `.blend` + `.png` + `.manifest.json` files

---

## 2. PHASE 0 VISUAL AUDIT (needs renders from #1)

```bash
python scripts/visual_audit/run_full_audit.py
# Quick test:
python scripts/visual_audit/run_full_audit.py --limit 20
```

**Expected output:** Priority queue JSON ranking buildings for photogrammetry upgrade

---

## 3. LOD GENERATION (needs .blend files from #1)

```bash
blender --background --python scripts/generate_lods.py -- \
  --source-dir outputs/full/ --skip-existing
```

---

## 4. COLLISION MESH GENERATION

```bash
blender --background --python scripts/generate_collision_mesh.py -- \
  --source-dir outputs/full/
```

---

## 5. FBX EXPORT FOR UNREAL

```bash
blender --background --python scripts/batch_export_unreal.py -- \
  --source-dir outputs/full/
```

---

## 6. TEXTURE OPERATIONS (needs GPU for upscaling)

```bash
# PBR extraction
python scripts/texture/extract_pbr.py --model intrinsic-anything \
  --input "PHOTOS KENSINGTON/" --output textures/pbr/

# Texture upscaling (RealESRGAN)
python scripts/texture/upscale_textures.py --model realesrgan \
  --input textures/ --scale 4
```

---

## 7. CYCLES RENDERS (high-quality, optional)

```bash
blender --background --python generate_building.py -- \
  --params params/ --batch-individual --render --cycles --skip-existing
```

---

## Status after enrichment session (2026-04-03)

| Metric | Value |
|---|---|
| Params enriched | 1,050/1,050 (100%) |
| Deep facade promoted | 1,035/1,050 (99%) |
| Setbacks inferred | 252 buildings |
| Depth notes consolidated | 791 buildings |
| Step counts added | 787 buildings |
| Foundation heights | 776 buildings |
| Photo matched | 1,035/1,050 (99%) |
| Generator compatible | 1,050/1,050 (100%) |
| **Renders** | **0 — START HERE** |
