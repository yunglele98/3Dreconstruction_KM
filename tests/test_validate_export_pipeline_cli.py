from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "validate_export_pipeline.py"


def test_validate_export_pipeline_help_runs():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--exports-dir" in result.stdout
    assert "--output" in result.stdout


def test_validate_export_pipeline_writes_custom_output(tmp_path: Path):
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    output = tmp_path / "report.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--exports-dir",
            str(exports_dir),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert output.exists()

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"]["total_validated"] == 0
