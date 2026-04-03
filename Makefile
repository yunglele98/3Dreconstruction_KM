.PHONY: test test-fast lint audit render-sample web-build web-dev pipeline-status pipeline-dry-run healthcheck coverage scenarios web-data analyze autofix-dry-run autofix-apply report clean help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-20s %s\n", $$1, $$2}'

test:  ## Run all tests
	python -m pytest tests/ -q

test-fast:  ## Run tests, stop on first failure
	python -m pytest tests/ -q -x --tb=short

lint:  ## Syntax-check all pipeline scripts
	@echo "Checking generate_building.py..."
	@python -m py_compile generate_building.py
	@echo "Checking generator_modules/..."
	@for f in generator_modules/*.py; do python -m py_compile "$$f"; done
	@echo "Checking scripts/sense/..."
	@for f in scripts/sense/*.py; do python -m py_compile "$$f"; done
	@echo "Checking scripts/reconstruct/..."
	@for f in scripts/reconstruct/*.py; do python -m py_compile "$$f"; done
	@echo "Checking scripts/enrich/..."
	@for f in scripts/enrich/*.py; do python -m py_compile "$$f"; done
	@echo "Checking scripts/planning/..."
	@for f in scripts/planning/*.py; do python -m py_compile "$$f"; done
	@echo "Checking scripts/export/..."
	@for f in scripts/export/*.py; do python -m py_compile "$$f"; done
	@echo "Checking scripts/verify/..."
	@for f in scripts/verify/*.py; do python -m py_compile "$$f"; done
	@echo "Checking scripts/monitor/..."
	@for f in scripts/monitor/*.py; do python -m py_compile "$$f"; done
	@echo "All syntax checks passed."

audit:  ## Run QA param audits
	python scripts/qa_params_gate.py --ci
	python scripts/audit_params_quality.py
	python scripts/audit_structural_consistency.py
	python scripts/audit_generator_contracts.py

render-sample:  ## Render a single test building (requires Blender)
	@echo "Render requires Blender CLI. Example:"
	@echo "  blender --background --python generate_building.py -- --params params/22_Lippincott_St.json --render"

web-build:  ## Build the web planning platform
	cd web && npm install && npm run build

web-dev:  ## Start web dev server
	cd web && npm install && npm run dev

pipeline-status:  ## Show pipeline dry-run status
	python scripts/run_full_pipeline.py --dry-run --skip-missing

pipeline-dry-run:  ## Dry-run full pipeline
	python scripts/run_full_pipeline.py --dry-run

healthcheck:  ## Run pipeline health check
	python scripts/monitor/healthcheck.py

coverage:  ## Generate coverage matrix
	python scripts/generate_coverage_matrix.py

scenarios:  ## Generate all scenario data
	python scripts/planning/generate_scenarios.py

web-data:  ## Build web data bundle (params-slim.json, geojson, scenarios)
	python scripts/export/build_web_data.py

analyze:  ## Run all param-only analysis scripts
	python scripts/analyze/geometric_accuracy.py --params params/ --output outputs/geometric_analysis/
	python scripts/analyze/facade_completeness.py --params params/ --output outputs/facade_completeness/
	python scripts/analyze/photo_param_drift.py --params params/ --output outputs/photo_drift/
	python scripts/analyze/heritage_fidelity.py --params params/ --output outputs/heritage_analysis/
	python scripts/analyze/splat_readiness.py --params params/ --output outputs/splat_readiness/
	python scripts/analyze/style_consistency.py --params params/ --output outputs/style_analysis/

autofix-dry-run:  ## Preview all autofix changes (no writes)
	python scripts/autofix_from_photos.py --params params/ --dry-run
	python scripts/autofix_decorative_from_hcd.py --params params/ --dry-run
	python scripts/autofix_color_from_photos.py --params params/ --dry-run

autofix-apply:  ## Apply all autofixes (writes to params)
	python scripts/autofix_from_photos.py --params params/ --apply --report outputs/autofix_report.json
	python scripts/autofix_decorative_from_hcd.py --params params/ --apply --report outputs/autofix_decorative_report.json
	python scripts/autofix_color_from_photos.py --params params/ --apply --report outputs/autofix_color_report.json

report:  ## Generate master pipeline report from all analyses
	python scripts/analyze/reconstruction_pipeline_report.py --output outputs/pipeline_report.json

clean:  ## Remove Python cache files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
