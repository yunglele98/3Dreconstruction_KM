.PHONY: test lint audit render-sample web-build pipeline-status healthcheck coverage clean

test:
	python -m pytest tests/ -q

lint:
	python -m py_compile generate_building.py
	@echo "Syntax check passed"

audit:
	python scripts/qa_params_gate.py --ci
	python scripts/audit_params_quality.py
	python scripts/audit_structural_consistency.py

render-sample:
	@echo "Render requires Blender CLI — run on local machine"

web-build:
	cd web && npm install && npm run build

pipeline-status:
	python scripts/run_full_pipeline.py --dry-run

healthcheck:
	python scripts/monitor/healthcheck.py

coverage:
	python scripts/generate_coverage_matrix.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
