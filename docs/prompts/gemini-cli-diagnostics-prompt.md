Operate in C:\Users\liam1\blender_buildings as a verification + diagnosis specialist.

Read first:
- AGENTS.md
- docs/GEMINI_LAUNCHER_PROMPT.md
- latest docs/reports/*.md

Goal:
Find integration issues quickly and produce precise, reproducible fixes.

Tasks:
1. Baseline:
   - git status --short
   - python scripts/run_blender_buildings_workflows.py dashboard --once-json
2. Run diagnostic pack:
   - python scripts/validate_all_params.py
   - python scripts/audit_decorative_completeness.py
   - python scripts/audit_structural_consistency.py
   - python scripts/audit_storefront_conflicts.py
3. If DB failures occur, classify cause (service/auth/db/schema/permissions).
4. Run:
   - python scripts/validate_export_pipeline.py --address "103 Bellevue Ave"
5. Build ranked issue list:
   - P0 breakage
   - P1 data risk
   - P2 cleanup
6. Propose minimal patch set and apply only high-confidence fixes.
7. Re-run only impacted validations.
8. Write:
   - docs/reports/gemini_diagnostics_<date>_<timestamp>.md
   - outputs/session_runs/gemini_findings_<timestamp>.json

Final output:
- exact failures found
- exact fixes applied
- residual risks
- commands for next agent
