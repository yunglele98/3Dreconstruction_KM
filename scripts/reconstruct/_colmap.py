"""Shared COLMAP utilities for reconstruct pipeline scripts."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GPU_LOCK = REPO_ROOT / ".gpu_lock"


def find_colmap() -> str | None:
    """Locate COLMAP executable on the system."""
    candidates = [
        shutil.which("colmap"),
        "C:/Users/liam1/Apps/COLMAP/bin/colmap",
        "C:/Program Files/COLMAP/COLMAP.bat",
        "/usr/bin/colmap",
        "/usr/local/bin/colmap",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


def acquire_gpu_lock(script_name: str = "colmap") -> bool:
    """Acquire the single-GPU lock. Returns True if acquired."""
    if GPU_LOCK.exists():
        try:
            info = json.loads(GPU_LOCK.read_text(encoding="utf-8"))
            holder = info.get("holder", "unknown")
            print(f"[WARN] GPU locked by {holder}")
            return False
        except (json.JSONDecodeError, OSError):
            pass
    GPU_LOCK.write_text(
        json.dumps({"holder": script_name, "pid": __import__("os").getpid()},
                    indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return True


def release_gpu_lock() -> None:
    """Release the GPU lock."""
    if GPU_LOCK.exists():
        GPU_LOCK.unlink()


def run_colmap_step(
    colmap_bin: str,
    args: list[str],
    *,
    step_name: str = "",
    timeout: int = 3600,
) -> tuple[bool, str]:
    """Run a single COLMAP step with error handling.

    Returns (success, message).
    """
    cmd = [colmap_bin] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr[:500] if result.stderr else "no stderr"
            return False, f"{step_name} failed (exit {result.returncode}): {stderr}"
        return True, f"{step_name} complete"
    except subprocess.TimeoutExpired:
        return False, f"{step_name} timed out after {timeout}s"
    except FileNotFoundError:
        return False, f"COLMAP binary not found: {colmap_bin}"


def run_sparse_reconstruction(
    image_dir: Path,
    workspace: Path,
    colmap_bin: str,
    *,
    gpu_index: int = 0,
    max_features: int = 8192,
    max_image_size: int = 2048,
) -> tuple[bool, str | None, list[str]]:
    """Run COLMAP sparse reconstruction (feature extract → match → map).

    Returns (success, best_model_path, log_messages).
    """
    db_path = workspace / "database.db"
    sparse_dir = workspace / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)
    log = []

    use_gpu = "1" if gpu_index >= 0 else "0"
    gpu_idx = str(max(gpu_index, 0))

    # Step 1: Feature extraction
    ok, msg = run_colmap_step(colmap_bin, [
        "feature_extractor",
        "--database_path", str(db_path),
        "--image_path", str(image_dir),
        "--ImageReader.single_camera", "0",
        "--SiftExtraction.use_gpu", use_gpu,
        "--SiftExtraction.gpu_index", gpu_idx,
        "--SiftExtraction.max_num_features", str(max_features),
        "--SiftExtraction.max_image_size", str(max_image_size),
    ], step_name="Feature extraction", timeout=3600)
    log.append(msg)
    if not ok:
        return False, None, log

    # Step 2: Exhaustive matching
    ok, msg = run_colmap_step(colmap_bin, [
        "exhaustive_matcher",
        "--database_path", str(db_path),
        "--SiftMatching.use_gpu", use_gpu,
        "--SiftMatching.gpu_index", gpu_idx,
    ], step_name="Exhaustive matching", timeout=3600)
    log.append(msg)
    if not ok:
        return False, None, log

    # Step 3: Mapping
    ok, msg = run_colmap_step(colmap_bin, [
        "mapper",
        "--database_path", str(db_path),
        "--image_path", str(image_dir),
        "--output_path", str(sparse_dir),
    ], step_name="Mapping", timeout=3600)
    log.append(msg)
    if not ok:
        return False, None, log

    # Find the best model (most images registered)
    models = sorted(sparse_dir.iterdir()) if sparse_dir.exists() else []
    if not models:
        return False, None, log + ["No sparse model produced"]

    best = str(models[0])
    log.append(f"Sparse model: {best}")
    return True, best, log


def run_dense_reconstruction(
    sparse_model: str,
    image_dir: Path,
    workspace: Path,
    colmap_bin: str,
    *,
    gpu_index: int = 0,
) -> tuple[bool, str | None, list[str]]:
    """Run COLMAP dense reconstruction (undistort → patch_match → fusion).

    Returns (success, ply_path, log_messages).
    """
    dense_dir = workspace / "dense"
    dense_dir.mkdir(parents=True, exist_ok=True)
    log = []

    # Undistort
    ok, msg = run_colmap_step(colmap_bin, [
        "image_undistorter",
        "--image_path", str(image_dir),
        "--input_path", sparse_model,
        "--output_path", str(dense_dir),
        "--output_type", "COLMAP",
    ], step_name="Image undistortion", timeout=600)
    log.append(msg)
    if not ok:
        return False, None, log

    # Patch-match stereo
    ok, msg = run_colmap_step(colmap_bin, [
        "patch_match_stereo",
        "--workspace_path", str(dense_dir),
        "--workspace_format", "COLMAP",
        "--PatchMatchStereo.gpu_index", str(max(gpu_index, 0)),
    ], step_name="Patch-match stereo", timeout=3600)
    log.append(msg)
    if not ok:
        return False, None, log

    # Stereo fusion
    ply_path = workspace / "fused.ply"
    ok, msg = run_colmap_step(colmap_bin, [
        "stereo_fusion",
        "--workspace_path", str(dense_dir),
        "--workspace_format", "COLMAP",
        "--output_path", str(ply_path),
    ], step_name="Stereo fusion", timeout=600)
    log.append(msg)
    if not ok:
        return False, None, log

    if not ply_path.exists():
        return False, None, log + ["No fused.ply produced"]

    return True, str(ply_path), log


def export_model_ply(
    model_path: str,
    output_path: Path,
    colmap_bin: str,
) -> Path | None:
    """Export a COLMAP sparse model to PLY format."""
    ok, msg = run_colmap_step(colmap_bin, [
        "model_converter",
        "--input_path", model_path,
        "--output_path", str(output_path),
        "--output_type", "PLY",
    ], step_name="PLY export", timeout=120)
    return output_path if ok and output_path.exists() else None


def validate_sparse_model(model_dir: Path) -> dict:
    """Validate a sparse COLMAP model by checking output files."""
    result = {"valid": False, "cameras": 0, "images": 0, "points": 0}

    cameras_bin = model_dir / "cameras.bin"
    images_bin = model_dir / "images.bin"
    points_bin = model_dir / "points3D.bin"
    cameras_txt = model_dir / "cameras.txt"
    images_txt = model_dir / "images.txt"
    points_txt = model_dir / "points3D.txt"

    has_bin = cameras_bin.exists() and images_bin.exists() and points_bin.exists()
    has_txt = cameras_txt.exists() and images_txt.exists() and points_txt.exists()

    if not has_bin and not has_txt:
        return result

    result["valid"] = True
    result["format"] = "binary" if has_bin else "text"

    # Count from text files if available
    if images_txt.exists():
        lines = images_txt.read_text(encoding="utf-8").splitlines()
        data_lines = [l for l in lines if l.strip() and not l.startswith("#")]
        result["images"] = len(data_lines) // 2  # 2 lines per image

    if points_txt.exists():
        lines = points_txt.read_text(encoding="utf-8").splitlines()
        data_lines = [l for l in lines if l.strip() and not l.startswith("#")]
        result["points"] = len(data_lines)

    return result
