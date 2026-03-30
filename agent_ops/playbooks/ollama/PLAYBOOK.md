# Ollama Local Playbook

## Primary Role

- Fast local loops: lint, unit tests, smoke scripts.
- Batch render checks and artifact verification.
- Queue draining for repetitive operational tasks.

## Delegation Rules

1. Prefer bounded tasks with clear pass/fail output.
2. Push failures back with exact failing command and log snippet.
3. Avoid broad refactors unless explicitly assigned.

## Deliverables

- Command logs.
- QA artifacts.
- Failure triage notes.
