"""Layer 4: AI visual analysis via Gemini — supports both API (python SDK) and CLI (gemini command).
Use --mode api for batch automation with API key, or --mode cli for auth-based Gemini CLI."""

import base64
import json
import os
import sys
import time
from pathlib import Path

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


PROMPT_TEMPLATE = """Compare these two images of the building at {address}, Kensington Market, Toronto.

IMAGE 1: A 3D parametric render of the building (procedural Blender model)
IMAGE 2: A real field photograph of the same building (March 2026)

Building parameters:
- Facade material: {facade_material}
- Floors: {floors}
- Roof type: {roof_type}
- Construction era: {era}
- Typology: {typology}
- Has storefront: {has_storefront}
- Condition: {condition}
- Facade colour: {facade_colour}

Rate each category 1-10 (10 = perfect match). Be specific about what differs.
For fixes, use the exact param field names shown.

IMPORTANT: These are DIFFERENT views (3D render vs real photo) so don't expect pixel-perfect match.
Focus on: correct material type, correct colour tone, correct feature presence/absence, correct proportions.

Respond ONLY with this JSON (no markdown, no explanation):
{{
  "overall_score": 0,
  "categories": {{
    "facade_material": {{
      "score": 0,
      "notes": "",
      "fix": null
    }},
    "facade_colour": {{
      "score": 0,
      "notes": "",
      "fix": null
    }},
    "windows": {{
      "score": 0,
      "notes": "",
      "fix": null
    }},
    "roof": {{
      "score": 0,
      "notes": "",
      "fix": null
    }},
    "ground_floor": {{
      "score": 0,
      "notes": "",
      "fix": null
    }},
    "decorative_elements": {{
      "score": 0,
      "notes": "",
      "fix": null
    }},
    "proportions": {{
      "score": 0,
      "notes": "",
      "fix": null
    }},
    "overall_impression": {{
      "score": 0,
      "notes": ""
    }}
  }},
  "biggest_issue": "",
  "colmap_recommendation": false,
  "confidence": 0.0
}}"""


def analyze_pair(render_path, photo_path, params, address, model):
    """Send one render+photo pair to Gemini for analysis."""
    render_bytes = Path(render_path).read_bytes()
    photo_bytes = Path(photo_path).read_bytes()

    hcd = params.get("hcd_data", {}) if isinstance(params.get("hcd_data"), dict) else {}

    prompt = PROMPT_TEMPLATE.format(
        address=address,
        facade_material=params.get("facade_material", "unknown"),
        floors=params.get("floors", "?"),
        roof_type=params.get("roof_type", "unknown"),
        era=hcd.get("construction_date", "unknown"),
        typology=hcd.get("typology", "unknown"),
        has_storefront=params.get("has_storefront", False),
        condition=params.get("condition", "unknown"),
        facade_colour=params.get("facade_colour", "unknown"),
    )

    response = model.generate_content([
        prompt,
        {"mime_type": "image/png", "data": base64.b64encode(render_bytes).decode()},
        {"mime_type": "image/jpeg", "data": base64.b64encode(photo_bytes).decode()},
    ])

    # Parse JSON from response
    text = response.text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Try extracting JSON from text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(text[start:end])
        else:
            return {
                "address": address,
                "error": "parse_failed",
                "raw_response": text[:500],
            }

    result["address"] = address
    result["render"] = str(render_path)
    result["photo"] = str(photo_path)
    result["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    return result


def run_layer4(pairs, output_dir, api_key=None, limit=None, batch_size=10, delay=2.0):
    """Batch process all pairs through Gemini API."""
    if not HAS_GENAI:
        print("ERROR: google-generativeai not installed. pip install google-generativeai")
        return []

    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set. Export it or pass --api-key")
        return []

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if limit:
        pairs = pairs[:limit]

    results = []
    skipped = 0
    errors = 0

    for i, pair in enumerate(pairs, 1):
        address = pair["address"]
        safe = address.replace(" ", "_").replace(",", "")
        out_path = output_dir / f"{safe}.json"

        # Skip if already analyzed
        if out_path.exists():
            try:
                results.append(json.loads(out_path.read_text(encoding="utf-8")))
                skipped += 1
                continue
            except Exception:
                pass

        if not pair.get("photo"):
            continue

        print(f"  [{i}/{len(pairs)}] {address}...")

        retries = 0
        max_retries = 5
        while retries <= max_retries:
            try:
                result = analyze_pair(
                    pair["render"], pair["photo"],
                    pair.get("params", {}), address, model,
                )
                out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
                results.append(result)

                score = result.get("overall_score", "?")
                biggest = result.get("biggest_issue", "")[:60]
                print(f"    Score: {score}/10 -- {biggest}")
                break

            except Exception as e:
                err_str = str(e)
                if "429" in err_str and retries < max_retries:
                    # Extract retry delay from error if available
                    wait = min(60 * (2 ** retries), 300)
                    import re
                    m = re.search(r"retry in ([\d.]+)s", err_str)
                    if m:
                        wait = max(float(m.group(1)) + 2, wait)
                    retries += 1
                    print(f"    Rate limited, waiting {wait:.0f}s (retry {retries}/{max_retries})...")
                    time.sleep(wait)
                    continue
                print(f"    ERROR: {err_str[:200]}")
                errors += 1
                results.append({"address": address, "error": err_str[:500]})
                break

        # Rate limit between successful requests
        if i % batch_size == 0:
            time.sleep(delay)

    print(f"\nLayer 4 complete: {len(results)} analyzed, {skipped} cached, {errors} errors")

    # Write batch summary
    scored = [r for r in results if "overall_score" in r]
    summary = {
        "total": len(results),
        "scored": len(scored),
        "skipped": skipped,
        "errors": errors,
        "avg_score": round(sum(r["overall_score"] for r in scored) / max(len(scored), 1), 1),
        "score_distribution": {
            "excellent_8_10": len([r for r in scored if r["overall_score"] >= 8]),
            "good_6_7": len([r for r in scored if 6 <= r["overall_score"] < 8]),
            "moderate_4_5": len([r for r in scored if 4 <= r["overall_score"] < 6]),
            "poor_2_3": len([r for r in scored if 2 <= r["overall_score"] < 4]),
            "critical_1": len([r for r in scored if r["overall_score"] < 2]),
        },
        "colmap_recommended": len([r for r in scored if r.get("colmap_recommendation")]),
    }
    (output_dir.parent / "layer4_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Summary: avg score {summary['avg_score']}/10, "
          f"{summary['colmap_recommended']} COLMAP recommendations")

    return results


def load_pairs(audit_report_path, params_dir):
    """Load pairs from Layer 1 audit report."""
    report = json.loads(Path(audit_report_path).read_text(encoding="utf-8"))
    buildings = report.get("buildings", [])
    params_dir = Path(params_dir)

    pairs = []
    for b in buildings:
        if b.get("match_status") != "matched":
            continue
        address = b["address"]
        param_path = params_dir / f"{address.replace(' ', '_')}.json"
        params = {}
        if param_path.exists():
            try:
                params = json.loads(param_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        pairs.append({
            "address": address,
            "render": b["render"],
            "photo": b["photo"],
            "params": params,
            "gap_score": b.get("gap_score", 0),
        })

    # Sort by gap score descending — analyze worst buildings first
    pairs.sort(key=lambda p: p.get("gap_score", 0), reverse=True)
    return pairs


if __name__ == "__main__":
    limit = None
    api_key = None
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])
        if arg == "--api-key" and i + 1 < len(sys.argv):
            api_key = sys.argv[i + 1]

    pairs = load_pairs(
        "outputs/visual_audit/audit_report.json",
        "params",
    )
    print(f"Loaded {len(pairs)} pairs from audit report")

    run_layer4(
        pairs=pairs,
        output_dir="outputs/visual_audit/gemini_analysis",
        api_key=api_key,
        limit=limit,
    )
