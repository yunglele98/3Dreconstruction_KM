"""Layer 2: Structural analysis — per-floor, roof silhouette, window grid, colour sampling."""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim


def load_and_resize(path, h=512):
    img = cv2.imread(str(path))
    if img is None:
        return None
    scale = h / img.shape[0]
    return cv2.resize(img, (int(img.shape[1] * scale), h))


def compute_lab_distance(a, b):
    min_h = min(a.shape[0], b.shape[0])
    min_w = min(a.shape[1], b.shape[1])
    a2 = cv2.cvtColor(cv2.resize(a, (min_w, min_h)), cv2.COLOR_BGR2LAB).astype(float)
    b2 = cv2.cvtColor(cv2.resize(b, (min_w, min_h)), cv2.COLOR_BGR2LAB).astype(float)
    return float(np.mean(np.sqrt(np.sum((a2 - b2) ** 2, axis=2))))


def compute_ssim(a, b):
    min_h = min(a.shape[0], b.shape[0])
    min_w = min(a.shape[1], b.shape[1])
    ag = cv2.cvtColor(cv2.resize(a, (min_w, min_h)), cv2.COLOR_BGR2GRAY)
    bg = cv2.cvtColor(cv2.resize(b, (min_w, min_h)), cv2.COLOR_BGR2GRAY)
    win = min(7, min_h - 1 if min_h % 2 == 0 else min_h, min_w - 1 if min_w % 2 == 0 else min_w)
    if win < 3:
        return 0.0
    if win % 2 == 0:
        win -= 1
    return float(ssim(ag, bg, win_size=win))


def per_floor_analysis(render, photo, params):
    """Compare render vs photo floor by floor."""
    total_h = params.get("total_height_m", 7.0)
    floor_heights = params.get("floor_heights_m", [3.5, 3.0])
    if not floor_heights or not isinstance(floor_heights, list):
        floor_heights = [total_h / max(params.get("floors", 2), 1)] * max(params.get("floors", 2), 1)

    img_h = render.shape[0]
    # Building occupies roughly middle 70% of image vertically
    bldg_top = int(img_h * 0.1)
    bldg_bot = int(img_h * 0.85)
    bldg_pixel_h = bldg_bot - bldg_top

    results = []
    cumulative = 0
    for i, fh in enumerate(floor_heights):
        frac_start = cumulative / total_h
        frac_end = (cumulative + fh) / total_h
        # Bottom-up building → top-down image
        y_start = bldg_top + int((1 - frac_end) * bldg_pixel_h)
        y_end = bldg_top + int((1 - frac_start) * bldg_pixel_h)
        y_start = max(0, min(y_start, img_h - 1))
        y_end = max(y_start + 5, min(y_end, img_h))

        r_floor = render[y_start:y_end, :]
        p_floor = photo[y_start:y_end, :]

        if r_floor.shape[0] < 5 or p_floor.shape[0] < 5:
            cumulative += fh
            continue

        floor_names = ["Ground floor", "Second floor", "Third floor", "Fourth floor"]
        results.append({
            "floor": i,
            "floor_name": floor_names[i] if i < len(floor_names) else f"Floor {i+1}",
            "height_m": fh,
            "ssim": compute_ssim(r_floor, p_floor),
            "lab_distance": compute_lab_distance(r_floor, p_floor),
        })
        cumulative += fh

    return results


def roof_silhouette(render, photo):
    """Compare roof outline shapes."""
    def top_contour(img):
        grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(grey, 200, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        return max(contours, key=cv2.contourArea)

    rc = top_contour(render)
    pc = top_contour(photo)
    if rc is None or pc is None:
        return {"hausdorff_distance": None, "match_score": None}

    try:
        dist = cv2.matchShapes(rc, pc, cv2.CONTOURS_MATCH_I1, 0)
    except Exception:
        dist = 1.0

    return {
        "hausdorff_distance": round(float(dist), 4),
        "match_score": round(max(0, 1.0 - dist), 3),
    }


def detect_windows(image):
    """Detect window-like dark rectangular regions."""
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = grey.shape

    # Adaptive threshold to find dark rectangles
    blurred = cv2.GaussianBlur(grey, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    contours, _ = cv2.findContours(thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    windows = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        aspect = ch / max(cw, 1)
        # Window: taller than wide, reasonable size, not touching edges
        if (area > w * h * 0.002 and area < w * h * 0.08 and
                0.7 < aspect < 5.0 and
                cw > 8 and ch > 12 and
                x > w * 0.05 and x + cw < w * 0.95):
            windows.append({
                "x": round(x / w, 3), "y": round(y / h, 3),
                "w": round(cw / w, 3), "h": round(ch / h, 3),
                "area_pct": round(area / (w * h) * 100, 2),
            })

    # Cluster into floors by Y position
    if not windows:
        return {"total": 0, "floors": 0, "per_floor": []}

    windows.sort(key=lambda win: win["y"])
    floors = []
    current_floor = [windows[0]]
    for win in windows[1:]:
        if abs(win["y"] - current_floor[-1]["y"]) < 0.08:
            current_floor.append(win)
        else:
            floors.append(current_floor)
            current_floor = [win]
    floors.append(current_floor)

    return {
        "total": len(windows),
        "floors": len(floors),
        "per_floor": [len(f) for f in floors],
    }


def window_grid_comparison(render, photo):
    """Compare detected window grids between render and photo."""
    r_win = detect_windows(render)
    p_win = detect_windows(photo)

    return {
        "render_windows": r_win,
        "photo_windows": p_win,
        "total_count_diff": r_win["total"] - p_win["total"],
        "floor_count_diff": r_win["floors"] - p_win["floors"],
        "per_floor_match": r_win["per_floor"] == p_win["per_floor"] if r_win["per_floor"] and p_win["per_floor"] else None,
    }


def bgr_to_hex(bgr):
    b, g, r = int(bgr[0]), int(bgr[1]), int(bgr[2])
    return f"#{r:02x}{g:02x}{b:02x}"


def colour_sampling(render, photo):
    """Sample and compare colours at specific facade points."""
    def sample(img, points):
        h, w = img.shape[:2]
        results = {}
        for name, (fx, fy) in points.items():
            x, y = int(fx * w), int(fy * h)
            patch = img[max(0, y - 3):y + 4, max(0, x - 3):x + 4]
            if patch.size == 0:
                continue
            avg = patch.mean(axis=(0, 1))
            lab = cv2.cvtColor(np.uint8([[avg]]), cv2.COLOR_BGR2LAB)[0][0]
            results[name] = {"hex": bgr_to_hex(avg), "lab": lab.tolist()}
        return results

    points = {
        "facade_upper": (0.5, 0.3),
        "facade_center": (0.5, 0.5),
        "facade_lower": (0.5, 0.7),
        "roof_area": (0.5, 0.1),
        "ground_floor": (0.5, 0.85),
        "left_wall": (0.15, 0.5),
        "right_wall": (0.85, 0.5),
        "trim_area": (0.5, 0.22),
    }

    r_samples = sample(render, points)
    p_samples = sample(photo, points)

    comparison = {}
    for name in points:
        if name in r_samples and name in p_samples:
            r_lab = np.array(r_samples[name]["lab"], dtype=float)
            p_lab = np.array(p_samples[name]["lab"], dtype=float)
            dist = float(np.sqrt(np.sum((r_lab - p_lab) ** 2)))
            comparison[name] = {
                "render_hex": r_samples[name]["hex"],
                "photo_hex": p_samples[name]["hex"],
                "lab_distance": round(dist, 1),
            }

    return comparison


def symmetry_score(image):
    """Measure left-right symmetry."""
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = grey.shape
    half = w // 2
    left = grey[:, :half]
    right = cv2.flip(grey[:, w - half:], 1)
    min_w = min(left.shape[1], right.shape[1])
    left = left[:, :min_w]
    right = right[:, :min_w]
    if left.size == 0 or right.size == 0:
        return 0.0
    return compute_ssim(cv2.cvtColor(left, cv2.COLOR_GRAY2BGR), cv2.cvtColor(right, cv2.COLOR_GRAY2BGR))


def regional_metrics(render, photo):
    """Compare specific regions of render vs photo."""
    h = min(render.shape[0], photo.shape[0])
    w = min(render.shape[1], photo.shape[1])
    r = cv2.resize(render, (w, h))
    p = cv2.resize(photo, (w, h))

    regions = {
        "roof": (0, int(h * 0.25)),
        "upper_facade": (int(h * 0.25), int(h * 0.5)),
        "lower_facade": (int(h * 0.5), int(h * 0.75)),
        "ground": (int(h * 0.75), h),
    }

    results = {}
    for name, (y1, y2) in regions.items():
        r_reg = r[y1:y2, :]
        p_reg = p[y1:y2, :]
        if r_reg.shape[0] < 5:
            continue
        results[name] = {
            "ssim": compute_ssim(r_reg, p_reg),
            "lab_distance": round(compute_lab_distance(r_reg, p_reg), 1),
        }

    return results


def analyze_building(render_path, photo_path, params):
    """Run full Layer 2 structural analysis on one building."""
    render = load_and_resize(render_path)
    photo = load_and_resize(photo_path)
    if render is None or photo is None:
        return None

    return {
        "per_floor": per_floor_analysis(render, photo, params),
        "roof_silhouette": roof_silhouette(render, photo),
        "window_grid": window_grid_comparison(render, photo),
        "colour_samples": colour_sampling(render, photo),
        "symmetry": {
            "render": round(symmetry_score(render), 3),
            "photo": round(symmetry_score(photo), 3),
        },
        "regional": regional_metrics(render, photo),
    }


def run_layer2(renders_dir, photos_sorted_dir, params_dir, output_path, limit=None):
    """Run Layer 2 on all paired buildings, using Layer 1 audit_report for photo matches."""
    renders_dir = Path(renders_dir)
    params_dir = Path(params_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load photo matches from Layer 1 audit report
    audit_report_path = output_path.parent / "audit_report.json"
    photo_map = {}
    if audit_report_path.exists():
        report = json.loads(audit_report_path.read_text(encoding="utf-8"))
        for b in report.get("buildings", []):
            if b.get("match_status") == "matched" and b.get("photo"):
                photo_map[b["address"]] = b["photo"]
        print(f"  Loaded {len(photo_map)} photo matches from audit_report.json")

    renders = sorted(renders_dir.glob("*.png"))
    if limit:
        renders = renders[:limit]

    results = {}
    for i, rp in enumerate(renders, 1):
        address = rp.stem.replace("_", " ")

        # Get photo from Layer 1 matches
        photo_path_str = photo_map.get(address)
        if not photo_path_str:
            continue
        pp = Path(photo_path_str)
        if not pp.exists():
            continue

        param_path = params_dir / f"{rp.stem}.json"
        params = {}
        if param_path.exists():
            try:
                params = json.loads(param_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        if params.get("skipped"):
            continue

        result = analyze_building(rp, pp, params)
        if result:
            results[address] = result

        if i % 100 == 0:
            print(f"  Layer 2: [{i}/{len(renders)}] {address}")

    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Layer 2 complete: {len(results)} buildings -> {output_path}")
    return results


if __name__ == "__main__":
    limit = None
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    run_layer2(
        renders_dir="outputs/buildings_renders_v1",
        photos_sorted_dir="PHOTOS KENSINGTON sorted",
        params_dir="params",
        output_path="outputs/visual_audit/layer2_results.json",
        limit=limit,
    )
