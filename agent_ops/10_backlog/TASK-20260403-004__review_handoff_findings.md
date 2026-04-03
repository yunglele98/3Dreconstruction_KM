# TASK-20260403-004: Triage and apply actionable handoff findings

- **priority**: medium
- **stage**: 9-VERIFY
- **estimated_effort**: medium
- **depends_on**: none

## Description

43 handoff reports remain in `agent_ops/30_handoffs/` from March 26-27. Key actionable findings:

### High priority (apply fixes):
1. **TASK-20260326-AUDIT** — Gemini audit found 145 issues: 35 suspicious dimensions, 110 core missing fields
2. **TASK-20260327-007** — HCD feature consistency: 139 discrepancies across 1,241 buildings
3. **TASK-20260327-017** — Protected field violations: 284 issues across 384 buildings (batches 1-8)
4. **TASK-20260327-MATERIAL-AUDIT** — 168 material mismatches reconciled

### Medium priority (review/validate):
5. **TASK-20260326-006** — Missing site coordinates for several buildings
6. **TASK-20260327-010** — Brick colour vs era validation
7. **TASK-20260327-019** — Window count cross-reference
8. **TASK-20260327-020** — Colour palette consistency

### Low priority (informational):
9. **TASK-20260327-005** — Texture baseline audit (urban elements)
10. **TASK-20260327-003** — Codex garage placement fixes (ready for review)

## Acceptance

- Each finding reviewed: applied, deferred, or archived with rationale
- Handoffs moved to `90_archive/` after processing
