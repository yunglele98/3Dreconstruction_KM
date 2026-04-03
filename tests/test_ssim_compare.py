import json
import subprocess
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="numpy not installed")
Image = pytest.importorskip("PIL.Image", reason="Pillow not installed")

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "verify"))
ssim_single = pytest.importorskip("ssim_single", reason="scripts/verify/ssim_single.py not on path")
compute_ssim = ssim_single.compute_ssim


def _write_image(path: Path, arr: np.ndarray) -> None:
    Image.fromarray(arr.astype(np.uint8), mode="L").save(path)


def test_compute_ssim_identical():
    arr = np.full((32, 32), 128, dtype=np.uint8)
    assert compute_ssim(arr.astype(float), arr.astype(float)) == 1.0


def test_compute_ssim_different():
    a = np.full((32, 32), 128, dtype=np.uint8)
    b = np.full((32, 32), 0, dtype=np.uint8)
    assert compute_ssim(a.astype(float), b.astype(float)) < 0.2


def test_ssim_compare_script(tmp_path: Path):
    ref = tmp_path / "ref"
    new = tmp_path / "new"
    ref.mkdir()
    new.mkdir()

    base = np.full((32, 32), 128, dtype=np.uint8)
    altered = base.copy()
    altered[0:8, 0:8] = 0

    _write_image(ref / "a.png", base)
    _write_image(new / "a.png", base)
    _write_image(ref / "b.png", base)
    _write_image(new / "b.png", altered)

    out = tmp_path / "out.json"
    cmd = [
        sys.executable,
        "scripts/ssim_compare.py",
        "--reference-dir",
        str(ref),
        "--new-dir",
        str(new),
        "--threshold",
        "0.95",
        "--output",
        str(out),
    ]
    subprocess.check_call(cmd)

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["total_compared"] == 2
    assert report["significant_changes"] == 1
    assert report["results"][0]["filename"] == "b.png"
