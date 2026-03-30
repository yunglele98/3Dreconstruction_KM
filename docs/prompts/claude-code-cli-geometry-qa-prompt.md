Work in C:\Users\liam1\blender_buildings.

Read first:
- AGENTS.md
- CLAUDE.md
- docs/CLAUDE_LAUNCHER_PROMPT.md

Goal:
Run a geometry/export quality pass focused on representative buildings and produce actionable diffs.

Tasks:
1. Select 5 representative addresses:
   - rowhouse
   - storefront
   - bay-and-gable
   - institutional/landmark
   - atypical multi-volume
2. Generate or refresh outputs for those addresses.
3. Run export QA:
   - python scripts/validate_export_pipeline.py --address "<each>"
4. If issues found, patch smallest possible source script(s), then re-test.
5. Run:
   - python scripts/audit_generator_contracts.py
6. Write:
   - docs/reports/claude_code_geometry_qa_<date>_<timestamp>.md
   - docs/reports/claude_code_patch_notes_<date>_<timestamp>.md

Final output:
- tested addresses
- pass/fail per address
- script patches
- remaining blockers + owner recommendation
