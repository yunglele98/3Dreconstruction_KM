"""Phase 0: Visual Audit — compare parametric renders against field photos."""

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.metrics import structural_similarity as ssim


REPO_ROOT = Path(__file__).parent.parent.parent
RENDERS_DIR = REPO_ROOT / "outputs" / "buildings_renders_v1"
PHOTOS_SORTED_DIR = REPO_ROOT / "PHOTOS KENSINGTON sorted"
PHOTOS_RAW_DIR = REPO_ROOT / "PHOTOS KENSINGTON"
PARAMS_DIR = REPO_ROOT / "params"
OUTPUT_DIR = REPO_ROOT / "outputs" / "visual_audit"

SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from match_photos_to_params import find_photo, load_photo_index, normalize_address


def resolve_photo_index_csv():
    """Locate photo_address_index.csv with repo-specific fallbacks."""
    candidates = [
        REPO_ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv",
        REPO_ROOT / "PHOTOS KENSINGTON sorted" / "csv" / "photo_address_index.csv",
        REPO_ROOT
        / "PHOTOS KENSINGTON sorted"
        / ".claude"
        / "worktrees"
        / "jovial-keller"
        / "PHOTOS KENSINGTON"
        / "csv"
        / "photo_address_index.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matches = list(REPO_ROOT.rglob("photo_address_index.csv"))
    if matches:
        return matches[0]
    return None


def resolve_param_photo_filename(params):
    """Extract a preferred source photo already attached to params."""
    if not isinstance(params, dict):
        return None
    deep_facade = params.get("deep_facade_analysis")
    if isinstance(deep_facade, dict):
        source_photo = deep_facade.get("source_photo")
        if source_photo:
            return source_photo
    photo_observations = params.get("photo_observations")
    if isinstance(photo_observations, dict):
        observed_photo = photo_observations.get("photo")
        if observed_photo:
            return observed_photo
    return None


def load_and_resize(path, target_height=512):
    """Load image and resize to target height, preserving aspect ratio."""
    try:
        with Image.open(path) as pil_img:
            pil_img = pil_img.convert("RGB")
            width, height = pil_img.size
            if height <= 0:
                return None
            scale = target_height / height
            new_width = max(int(width * scale), 1)
            pil_img = pil_img.resize((new_width, target_height), Image.Resampling.LANCZOS)
            img = np.array(pil_img)
    except (OSError, ValueError, cv2.error, MemoryError):
        return None

    # OpenCV routines below expect BGR ordering.
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def build_photo_filename_index():
    """Build filename -> absolute path lookup from raw + sorted photo dirs."""
    index = {}
    for photo in PHOTOS_RAW_DIR.glob("*.[jJ][pP][gG]"):
        index[photo.name] = photo
    if PHOTOS_SORTED_DIR.exists():
        for subdir in PHOTOS_SORTED_DIR.iterdir():
            if not subdir.is_dir():
                continue
            for photo in subdir.glob("*.[jJ][pP][gG]"):
                index.setdefault(photo.name, photo)
    return index


def find_photo_for_address(address, params, photos_by_addr, photo_file_index):
    """Find the best field photo for this address using shared match strategies."""
    param_photo = resolve_param_photo_filename(params)
    if param_photo:
        path = photo_file_index.get(param_photo)
        if path and path.exists():
            return path, {
                "status": "matched",
                "method": "param_file",
                "photo_filename": param_photo,
                "confidence": 0.99,
            }

    site = params.get("site") if isinstance(params.get("site"), dict) else {}
    street_number = site.get("street_number")
    street = site.get("street")

    filename, method = find_photo(
        building_name=address,
        site_street_number=street_number,
        site_street=street,
        photos_by_addr=photos_by_addr,
    )

    if filename:
        path = photo_file_index.get(filename)
        if path and path.exists():
            confidence_map = {
                "exact": 1.0,
                "composite": 0.98,
                "normalized": 0.95,
                "number_variant": 0.92,
                "composite_prefix": 0.92,
                "composite_trailing": 0.9,
                "alias_expansion": 0.9,
                "substring": 0.85,
                "fuzzy": 0.8,
            }
            return path, {
                "status": "matched",
                "method": method,
                "photo_filename": filename,
                "confidence": confidence_map.get(method, 0.75),
            }

    # Legacy fallback to preserve behavior on odd naming edge-cases.
    addr_key = normalize_address(address)
    candidates = photos_by_addr.get(addr_key, [])
    if candidates:
        for candidate in candidates:
            path = photo_file_index.get(candidate)
            if path and path.exists():
                return path, {
                    "status": "matched",
                    "method": "index_fallback",
                    "photo_filename": candidate,
                    "confidence": 0.7,
                }

    return None, {
        "status": "no_photo",
        "method": "none",
        "photo_filename": None,
        "confidence": 0.0,
    }


def compare_images(render, photo):
    """Compute similarity metrics between render and photo."""
    # Resize both to same dimensions for comparison
    h = min(render.shape[0], photo.shape[0], 512)
    w = min(render.shape[1], photo.shape[1], 512)
    render_resized = cv2.resize(render, (w, h))
    photo_resized = cv2.resize(photo, (w, h))

    metrics = {}

    # 1. SSIM
    render_grey = cv2.cvtColor(render_resized, cv2.COLOR_BGR2GRAY)
    photo_grey = cv2.cvtColor(photo_resized, cv2.COLOR_BGR2GRAY)
    metrics["ssim"] = float(ssim(render_grey, photo_grey))

    # 2. Colour histogram comparison
    for ch, name in enumerate(["blue", "green", "red"]):
        hist_r = cv2.calcHist([render_resized], [ch], None, [64], [0, 256])
        hist_p = cv2.calcHist([photo_resized], [ch], None, [64], [0, 256])
        cv2.normalize(hist_r, hist_r)
        cv2.normalize(hist_p, hist_p)
        metrics[f"hist_{name}"] = float(cv2.compareHist(hist_r, hist_p, cv2.HISTCMP_CORREL))
    metrics["hist_avg"] = np.mean([metrics["hist_blue"], metrics["hist_green"], metrics["hist_red"]])

    # 3. LAB colour distance (central region)
    render_lab = cv2.cvtColor(render_resized, cv2.COLOR_BGR2LAB).astype(float)
    photo_lab = cv2.cvtColor(photo_resized, cv2.COLOR_BGR2LAB).astype(float)
    rh, rw = render_lab.shape[:2]
    region_r = render_lab[int(rh * 0.2):int(rh * 0.8), int(rw * 0.2):int(rw * 0.8)]
    region_p = photo_lab[int(rh * 0.2):int(rh * 0.8), int(rw * 0.2):int(rw * 0.8)]
    if region_r.size > 0 and region_p.size > 0:
        # Resize to match if needed
        min_h = min(region_r.shape[0], region_p.shape[0])
        min_w = min(region_r.shape[1], region_p.shape[1])
        region_r = region_r[:min_h, :min_w]
        region_p = region_p[:min_h, :min_w]
        metrics["lab_distance"] = float(np.mean(np.sqrt(np.sum((region_r - region_p) ** 2, axis=2))))
    else:
        metrics["lab_distance"] = 50.0

    # 4. Edge similarity
    edges_r = cv2.Canny(render_grey, 50, 150)
    edges_p = cv2.Canny(photo_grey, 50, 150)
    union = np.sum(edges_r | edges_p)
    if union > 0:
        metrics["edge_similarity"] = float(np.sum(edges_r & edges_p) / union)
    else:
        metrics["edge_similarity"] = 0.0

    return metrics


def classify_issues(metrics, params):
    """Classify discrepancy types based on metrics."""
    issues = []

    if metrics["lab_distance"] > 25:
        mat = (params.get("facade_material") or "").lower()
        if mat == "brick":
            issues.append({"type": "wrong_brick_colour", "severity": "medium",
                           "description": f"Brick colour mismatch (LAB: {metrics['lab_distance']:.0f})"})
        else:
            issues.append({"type": "wrong_paint_colour", "severity": "medium",
                           "description": f"Paint/stucco colour mismatch (LAB: {metrics['lab_distance']:.0f})"})

    if metrics["hist_avg"] < 0.4:
        issues.append({"type": "wrong_material", "severity": "high",
                       "description": "Facade material appears completely wrong"})

    if metrics["edge_similarity"] < 0.1:
        issues.append({"type": "missing_features", "severity": "high",
                       "description": "Significant structural features missing"})

    if metrics["ssim"] < 0.25:
        issues.append({"type": "major_structural_mismatch", "severity": "high",
                       "description": f"Very low structural match (SSIM: {metrics['ssim']:.2f})"})

    if not issues:
        issues.append({"type": "acceptable", "severity": "none",
                       "description": "Within acceptable tolerance"})

    return issues


def compute_gap_score(metrics, issues):
    """Composite gap score: 0 = perfect match, 100 = completely wrong."""
    scores = {
        "structural": (1 - max(metrics.get("ssim", 0), 0)) * 25,
        "colour": min(metrics.get("lab_distance", 0) / 50 * 25, 25),
        "edges": (1 - metrics.get("edge_similarity", 0)) * 20,
        "histogram": (1 - max(metrics.get("hist_avg", 0), 0)) * 15,
    }
    base = sum(scores.values())

    severity_bonus = sum(10 if i["severity"] == "high" else 5 if i["severity"] == "medium" else 0
                        for i in issues)

    return {
        "gap_score": round(min(base + severity_bonus, 100), 1),
        "components": {k: round(v, 1) for k, v in scores.items()},
    }


def generate_comparison_image(render_path, photo_path, address, gap_score, issues, output_dir):
    """Create side-by-side comparison PNG."""
    try:
        render = Image.open(render_path).resize((640, 360))
        photo = Image.open(photo_path).resize((640, 360))
    except Exception:
        return None

    canvas = Image.new("RGB", (1280, 460), (30, 30, 30))
    canvas.paste(render, (0, 0))
    canvas.paste(photo, (640, 0))

    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
        font_small = ImageFont.truetype("arial.ttf", 11)
    except Exception:
        font = ImageFont.load_default()
        font_small = font

    draw.text((10, 365), f"RENDER: {address}", fill="white", font=font)
    draw.text((650, 365), f"PHOTO: {address}", fill="white", font=font)

    # Gap score bar
    bar_w = int(gap_score * 12.5)
    if gap_score < 20:
        bar_col = (68, 255, 68)
    elif gap_score < 40:
        bar_col = (180, 255, 68)
    elif gap_score < 60:
        bar_col = (255, 200, 0)
    else:
        bar_col = (255, 68, 68)
    draw.rectangle((10, 390, 10 + bar_w, 405), fill=bar_col)
    draw.text((10 + bar_w + 5, 390), f"Gap: {gap_score:.0f}/100", fill="white", font=font_small)

    # Issues
    y = 415
    for issue in issues[:2]:
        col = {"high": "#FF4444", "medium": "#FFAA00", "none": "#44FF44"}.get(issue["severity"], "#FFFFFF")
        draw.text((10, y), f"[{issue['severity'].upper()}] {issue['type']}: {issue['description'][:90]}",
                  fill=col, font=font_small)
        y += 16

    safe_name = address.replace(" ", "_").replace(",", "")
    out_path = output_dir / f"{safe_name}.png"
    try:
        canvas.save(str(out_path))
    except OSError as exc:
        msg = str(exc).lower()
        if "no space left" in msg or "errno 28" in msg:
            return None
        raise
    return str(out_path)


def run_audit(limit=None):
    """Run the full visual audit pipeline."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    comparisons_dir = OUTPUT_DIR / "comparisons"
    comparisons_dir.mkdir(parents=True, exist_ok=True)

    renders = sorted(RENDERS_DIR.glob("*.png"))
    if limit:
        renders = renders[:limit]
    photo_index_csv = resolve_photo_index_csv()
    photos_by_addr = load_photo_index(photo_index_csv) if photo_index_csv else {}
    photo_file_index = build_photo_filename_index()

    print(f"Phase 0 Visual Audit")
    print(f"Renders: {len(renders)}")
    print(f"Photos dir: {PHOTOS_SORTED_DIR}")
    print(f"Photo index: {photo_index_csv or 'not found; using param-embedded photos where available'}")
    print(f"Photo index addresses: {len(photos_by_addr)}")
    print()

    results = []
    matching_results = []
    stats = {"matched": 0, "no_photo": 0, "errors": 0}
    method_counts = {}

    for i, render_path in enumerate(renders, 1):
        address = render_path.stem.replace("_", " ")

        # Load params
        param_path = PARAMS_DIR / f"{render_path.stem}.json"
        params = {}
        if param_path.exists():
            try:
                params = json.loads(param_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        if params.get("skipped"):
            continue

        # Find matching photo
        photo_path, match_meta = find_photo_for_address(
            address, params, photos_by_addr, photo_file_index
        )
        method = match_meta.get("method", "none")
        method_counts[method] = method_counts.get(method, 0) + 1

        if not photo_path:
            matching_results.append({
                "address": address,
                "status": "no_photo",
                "method": method,
                "photo_filename": None,
                "confidence": 0.0,
            })
            results.append({
                "address": address,
                "render": str(render_path),
                "photo": None,
                "match_status": "no_photo",
                "gap_score": None,
                "tier": "no_photo",
            })
            stats["no_photo"] += 1
            if i % 50 == 0:
                print(f"  [{i}/{len(renders)}] {address} — no photo")
            continue
        matching_results.append({
            "address": address,
            "status": "matched",
            "method": method,
            "photo_filename": match_meta.get("photo_filename"),
            "photo_path": str(photo_path),
            "confidence": match_meta.get("confidence", 0.0),
        })

        # Load images
        render_img = load_and_resize(render_path)
        photo_img = load_and_resize(photo_path)

        if render_img is None or photo_img is None:
            stats["errors"] += 1
            continue

        # Compare
        try:
            metrics = compare_images(render_img, photo_img)
            issues = classify_issues(metrics, params)
            score_data = compute_gap_score(metrics, issues)
            gap_score = score_data["gap_score"]
        except Exception as e:
            print(f"  [{i}/{len(renders)}] {address} — compare error: {e}")
            stats["errors"] += 1
            continue

        # Tier
        if gap_score >= 70:
            tier = "critical"
        elif gap_score >= 50:
            tier = "high"
        elif gap_score >= 30:
            tier = "medium"
        elif gap_score >= 15:
            tier = "low"
        else:
            tier = "acceptable"

        # Generate comparison image
        comp_path = generate_comparison_image(
            render_path, photo_path, address, gap_score, issues, comparisons_dir)

        # HCD info
        hcd = params.get("hcd_data", {}) if isinstance(params.get("hcd_data"), dict) else {}

        result = {
            "address": address,
            "render": str(render_path),
            "photo": str(photo_path),
            "comparison": comp_path,
            "match_status": "matched",
            "match_method": method,
            "match_confidence": match_meta.get("confidence", 0.0),
            "gap_score": gap_score,
            "tier": tier,
            "metrics": {k: round(v, 3) if isinstance(v, float) else v for k, v in metrics.items()},
            "issues": issues,
            "primary_issue": issues[0] if issues else None,
            "score_components": score_data["components"],
            "street": params.get("site", {}).get("street", ""),
            "era": hcd.get("construction_date", ""),
            "typology": hcd.get("typology", ""),
            "contributing": hcd.get("contributing", ""),
            "facade_material": params.get("facade_material", ""),
        }
        results.append(result)
        stats["matched"] += 1

        if i % 50 == 0:
            print(f"  [{i}/{len(renders)}] {address} — gap: {gap_score:.0f} ({tier})")

    # Sort by gap score descending
    scored = [r for r in results if r["gap_score"] is not None]
    scored.sort(key=lambda r: r["gap_score"], reverse=True)
    unscored = [r for r in results if r["gap_score"] is None]

    # Reassign tiers using PERCENTILE ranking (not fixed thresholds)
    # Since all render-vs-photo scores will be high, rank relatively
    if scored:
        all_scores = [r["gap_score"] for r in scored]
        p20 = float(np.percentile(all_scores, 20))
        p40 = float(np.percentile(all_scores, 40))
        p60 = float(np.percentile(all_scores, 60))
        p80 = float(np.percentile(all_scores, 80))

        for r in scored:
            g = r["gap_score"]
            if g >= p80:
                r["tier"] = "critical"
            elif g >= p60:
                r["tier"] = "high"
            elif g >= p40:
                r["tier"] = "medium"
            elif g >= p20:
                r["tier"] = "low"
            else:
                r["tier"] = "acceptable"

    # Tier counts
    tier_counts = {}
    for r in scored + unscored:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1

    # Issue type counts
    issue_counts = {}
    for r in scored:
        for issue in r.get("issues", []):
            t = issue["type"]
            issue_counts[t] = issue_counts.get(t, 0) + 1

    # Street-level aggregation
    street_scores = {}
    for r in scored:
        street = r.get("street", "UNKNOWN")
        street_scores.setdefault(street, []).append(r["gap_score"])
    street_avg = {s: round(np.mean(scores), 1) for s, scores in street_scores.items()}
    street_priority = sorted(street_avg.items(), key=lambda x: x[1], reverse=True)

    # Summary
    summary = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_renders": len(renders),
        "total_compared": stats["matched"],
        "total_no_photo": stats["no_photo"],
        "total_errors": stats["errors"],
        "tier_counts": tier_counts,
        "top_issues": dict(sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)),
        "avg_gap_score": round(np.mean([r["gap_score"] for r in scored]), 1) if scored else 0,
        "median_gap_score": round(float(np.median([r["gap_score"] for r in scored])), 1) if scored else 0,
        "street_priority": street_priority[:10],
    }

    # Write outputs
    report = {"summary": summary, "buildings": scored + unscored}
    (OUTPUT_DIR / "audit_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    (OUTPUT_DIR / "priority_queue.json").write_text(
        json.dumps(scored, indent=2, ensure_ascii=False), encoding="utf-8")

    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    matching_summary = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_renders": len(renders),
        "matched": stats["matched"],
        "no_photo": stats["no_photo"],
        "errors": stats["errors"],
        "match_rate_pct": round((stats["matched"] / max(len(renders), 1)) * 100, 1),
        "methods": dict(sorted(method_counts.items(), key=lambda kv: kv[1], reverse=True)),
        "avg_confidence": round(
            float(np.mean([m["confidence"] for m in matching_results if m["status"] == "matched"]))
            if any(m["status"] == "matched" for m in matching_results)
            else 0.0,
            3,
        ),
        "results": matching_results,
    }
    (OUTPUT_DIR / "photo_matching.json").write_text(
        json.dumps(matching_summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Print summary
    print(f"\n{'='*60}")
    print(f"PHASE 0 VISUAL AUDIT COMPLETE")
    print(f"{'='*60}")
    print(f"Compared: {stats['matched']} | No photo: {stats['no_photo']} | Errors: {stats['errors']}")
    print(f"Avg gap score: {summary['avg_gap_score']} | Median: {summary['median_gap_score']}")
    print(f"\nTier distribution:")
    for tier in ["critical", "high", "medium", "low", "acceptable", "no_photo"]:
        count = tier_counts.get(tier, 0)
        bar = "#" * (count // 5)
        print(f"  {tier:12s}: {count:4d} {bar}")
    print(f"\nTop issues:")
    for issue_type, count in list(summary["top_issues"].items())[:5]:
        print(f"  {issue_type:30s}: {count}")
    print(f"\nPriority streets for COLMAP:")
    for street, avg in street_priority[:5]:
        print(f"  {street:25s}: avg gap {avg:.1f}")
    print(f"\nOutputs: {OUTPUT_DIR}")


if __name__ == "__main__":
    limit = None
    for arg in sys.argv[1:]:
        if arg.startswith("--limit"):
            limit = int(sys.argv[sys.argv.index(arg) + 1])
    run_audit(limit=limit)
