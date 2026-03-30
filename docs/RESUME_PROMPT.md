# Resume Prompt — After Restart

Paste into Claude Code after restarting your PC:

```
cd G:\liam1_transfer\blender_buildings
```

Then:

```
Resume from docs/RESUME_PROMPT.md — finish the batch re-render and generate street demos.
```

---

## What was done (2026-03-27 session)

### Multi-agent system
- Built full multi-agent workflow: router with dependency checking, task lifecycle (complete/close), Ollama + Gemini task runners, launcher prompts for all 4 agent types
- Expanded Gemini (8 skills, capacity 4, full playbook), re-enabled Claude
- PowerShell launcher: `.\scripts\start_agent_ops.ps1 -StartControlLoop -StartOllamaRunner -StartGeminiRunner -OllamaAutoComplete`
- 19 tasks completed, 47 handoffs written

### Param enrichment (all 1,241 active buildings)
- All 12 tracked fields at 100% (except HCD typology 77.4% — external data)
- Normalized: roof_type, facade_material (case-consistent lowercase)
- Fixed: 18 window/floor mismatches, 100 colour conflicts, 67 roof type descriptions
- Skipped: 12 non-building photos, 39 backup/variant files
- Geocoded: 87 buildings from PostGIS + embedded coords (now 100% coordinate coverage)
- Diversified window types for 920 buildings, enriched 67 door types, 19 roof pitches
- Updated `params/_site_coordinates.json` with 1,241 new entries
- Tests: 30/30 passing

### Renders
- Batch re-render started: 533/1,253 completed before session ended
- Individual .blend files in `outputs/full/`

## What needs finishing

### 1. Complete batch re-render (~720 remaining)
```bash
blender --background --python generate_building.py -- --params params/ --batch-individual --skip-existing --output-dir outputs/full/
```
This will only render the ~720 buildings that weren't re-rendered yet.

### 2. Generate street demos (sequentially)
```bash
blender --background --python generate_building.py -- --params params/ --match "Bellevue" --output-dir outputs/demos/
blender --background --python generate_building.py -- --params params/ --match "Augusta" --output-dir outputs/demos/
blender --background --python generate_building.py -- --params params/ --match "Baldwin" --output-dir outputs/demos/
blender --background --python generate_building.py -- --params params/ --match "Kensington_Ave" --output-dir outputs/demos/
blender --background --python generate_building.py -- --params params/ --match "Nassau" --output-dir outputs/demos/
blender --background --python generate_building.py -- --params params/ --match "Spadina" --output-dir outputs/demos/
blender --background --python generate_building.py -- --params params/ --match "College" --output-dir outputs/demos/
blender --background --python generate_building.py -- --params params/ --match "Dundas" --output-dir outputs/demos/
blender --background --python generate_building.py -- --params params/ --match "Bathurst" --output-dir outputs/demos/
blender --background --python generate_building.py -- --params params/ --match "Oxford" --output-dir outputs/demos/
blender --background --python generate_building.py -- --params params/ --match "Wales" --output-dir outputs/demos/
```
Run these ONE AT A TIME — parallel `--match` without `--batch-individual` overwrites the same output file.

### 3. Restart agent ops (optional)
```bash
# Start Ollama
start "" "C:\Users\liam1\AppData\Local\Programs\Ollama\ollama.exe"
# Wait 5 seconds then:
"C:\Users\liam1\AppData\Local\Programs\Ollama\ollama.exe" serve &

# Start full agent stack
.\scripts\start_agent_ops.ps1 -StartControlLoop -StartOllamaRunner -StartGeminiRunner -OllamaAutoComplete
```

### 4. Photo analysis batches (8 batches in batches/)
The Gemini/Codex photo agents were launched on all 8 batches but may not have finished writing. Check:
```bash
ls batches/batch_*_results.json
```
If missing, re-launch one at a time:
```bash
gemini -m gemini-2.5-flash -p "Follow docs/AGENT_PROMPT.md to process batches/batch_001.json. Read each building's photo from 'PHOTOS KENSINGTON/' and merge visual observations into the corresponding params/*.json file. Write results to batches/batch_001_results.json when done."
```
