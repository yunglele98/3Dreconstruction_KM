# Claude Code — Reorganize blender_buildings Project Structure

Working directory: `D:\liam1_transfer\blender_buildings`

---

## Phase 1: Archive tmp_ and one-off scripts

```powershell
New-Item -ItemType Directory -Force -Path archive\tmp_scripts, archive\fire_station_scripts

Get-ChildItem scripts\tmp_*.py | Move-Item -Destination archive\tmp_scripts\
@("finalize_station.py","extract_station.py","find_tower.py","reconstruct_fire_station_perfect.py","render_st_stephens_overview.py","render_st_stephens_qa.py","interpolate_mural_lane.py","merge_kensington_ave_facades.py") | ForEach-Object {
    if (Test-Path "scripts\$_") { Move-Item "scripts\$_" "archive\fire_station_scripts\" }
}
```

## Phase 2: Organize docs/ into subdirectories

```powershell
New-Item -ItemType Directory -Force -Path docs\prompts, docs\reports, docs\audits
```

### Move prompts
```powershell
@("AGENT_PROMPT.md","CLAUDE_LAUNCHER_PROMPT.md","CODEX_LAUNCHER_PROMPT.md","GEMINI_LAUNCHER_PROMPT.md","OLLAMA_LAUNCHER_PROMPT.md","CLAUDE_CODE_LOCAL_LAUNCH_2026-03-28.md","GEMINI_BATCH_2_PROMPT_2026-03-28.md","GEMINI_BATCH_3_PROMPT_2026-03-28.md","CODEX_BATCH_2_PROMPT_2026-03-28.md","CODEX_BATCH_3_PROMPT_2026-03-28.md","SECOND_AGENT_PROMPT.md","DEMO_REFINEMENT_PROMPT.md","BATCH_REGEN_PROMPT.md","BATCH_FILL_GAP_PROMPT.md","RESUME_PROMPT.md","CLAUDE_AGENT_PROMPT_FIND_RELEVANT_APPS.md","DEDUP_BLENDER_BUILDINGS_PROMPT.md","TASK_LAUNCH_PROMPTS_2026-03-28.md","agent_prompts_description_cleanup.md","LOCAL_MACHINE_CLEANUP_PROMPT.md","PROJECT_REORG_PROMPT.md") | ForEach-Object {
    if (Test-Path "docs\$_") { Move-Item "docs\$_" "docs\prompts\" }
}
# Also move root-level prompts
@("CODEX_BATCH_3_PROMPT_2026-03-28.md","PROJECT_REORG_PROMPT.md","LOCAL_MACHINE_CLEANUP_PROMPT.md") | ForEach-Object {
    if (Test-Path "$_") { Move-Item "$_" "docs\prompts\" }
}
```

### Move reports
```powershell
@("CHANGELOG_2026-03-28.md","NEXT_TASK_QUEUE_2026-03-28.md","NEXT_TASK_QUEUE_2026-03-29.md","COWORK_TASK_LIST_2026-03-28.md","generator_hardening_report_2026-03-28.md","APP_TOOLING_ANALYSIS_2026-03-27.md","REPAIR_REPORT.md","SCHEMA_SUMMARY.txt","TASK_COMPLETION_SUMMARY.txt","VALIDATION_REPORT.md","BUILDING_TOOLS.md","HARDENING_ANALYSIS_INDEX.md","CONSOLIDATED_GATE_REPORT_2026-03-28.md","GATE_DASHBOARD_2026-03-28.md","deep_facade_quality_report.md","glomap_triage.md","photogrammetry_analysis.md") | ForEach-Object {
    if (Test-Path "docs\$_") { Move-Item "docs\$_" "docs\reports\" }
}
```

### Move audits
```powershell
@("hcd_photo_coverage_2026-03-28.md","photo_param_crossref_2026-03-28.md") | ForEach-Object {
    if (Test-Path "docs\$_") { Move-Item "docs\$_" "docs\audits\" }
}
Get-ChildItem docs\windows_detail_audit*.md, docs\colour_consistency_audit*.md, docs\storefront_audit*.md -ErrorAction SilentlyContinue | Move-Item -Destination docs\audits\
```

## Phase 3: Organize outputs/

```powershell
New-Item -ItemType Directory -Force -Path outputs\deliverables
@("Kensington_Market_Project_Status.pptx","Kensington_Task_Dispatch_Plan_2026-03-28.docx","Kensington_Market_Building_Summary.xlsx") | ForEach-Object {
    if (Test-Path "outputs\$_") { Move-Item "outputs\$_" "outputs\deliverables\" }
}
```

## Phase 4: Verify

```powershell
Write-Host "=== Final Structure ==="
Write-Host "Root: $((Get-ChildItem -Force | Where-Object { $_.Name -ne '__pycache__' }).Count) items"
Write-Host "scripts/: $((Get-ChildItem scripts\*.py).Count) scripts"
Write-Host "docs/prompts/: $((Get-ChildItem docs\prompts\).Count) files"
Write-Host "docs/reports/: $((Get-ChildItem docs\reports\).Count) files"
Write-Host "docs/audits/: $((Get-ChildItem docs\audits\).Count) files"
Write-Host "docs/catalogue/: $((Get-ChildItem docs\catalogue\ -EA 0).Count) files"
Write-Host "archive/ subdirs: $((Get-ChildItem archive -Directory).Count)"
Write-Host "tests/: $((Get-ChildItem tests\*.py).Count) test files"

python -m pytest tests/ -q
```

## Phase 5: Update CLAUDE.md

Update the Working Data Directories section to reflect:
- `docs/prompts/` — agent launch prompts and batch task prompts
- `docs/reports/` — changelogs, analysis, status reports
- `docs/audits/` — quality audit reports
- `outputs/deliverables/` — .pptx, .xlsx, .docx
