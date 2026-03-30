#!/usr/bin/env python3
"""Generate comprehensive QA report with HTML dashboard for building params.

Scans all param files in params/, computes quality scores across multiple
categories, performs per-street aggregation, and generates both machine-readable
JSON and an interactive HTML dashboard.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
OUTPUT_DIR = ROOT / "outputs"
PHOTO_INDEX = ROOT / "PHOTOS KENSINGTON" / "csv" / "photo_address_index.csv"


@dataclass
class QAIssue:
    """Represents a single QA issue found in a building."""
    category: str
    severity: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
        }


def _extract_street_from_name(building_name: str) -> str:
    """Extract street name from building name, removing number prefix.

    Example: "22 Lippincott St" -> "Lippincott St"
    """
    if not building_name:
        return ""
    parts = building_name.strip().split(maxsplit=1)
    return parts[1] if len(parts) > 1 else parts[0]


def _load_photo_index() -> dict[str, str]:
    """Load photo address index into a dict for fast lookup.

    Returns mapping from building address to photo filename.
    """
    photos: dict[str, str] = {}
    if not PHOTO_INDEX.exists():
        return photos

    try:
        with open(PHOTO_INDEX, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row and "address_or_location" in row:
                    addr = (row.get("address_or_location") or "").strip()
                    filename = (row.get("filename") or "").strip()
                    if addr and filename:
                        photos[addr] = filename
    except (OSError, csv.Error):
        pass

    return photos


def _has_render(building_name: str, outputs_dir: Path) -> bool:
    """Check if a building has a rendered output.

    Looks for <stem>.manifest.json in outputs/full/.
    """
    full_dir = outputs_dir / "full"
    if not full_dir.exists():
        return False

    stem = building_name.replace(" ", "_")
    manifest = full_dir / f"{stem}.manifest.json"
    return manifest.exists()


def _has_photo(building_name: str, photo_index: dict[str, str]) -> bool:
    """Check if a building has a field photo reference."""
    # Try exact match first
    if building_name in photo_index:
        return True

    # Try substring match on building name
    for addr in photo_index:
        if building_name.lower() in addr.lower() or addr.lower() in building_name.lower():
            return True

    return False


def _check_building(params: dict[str, Any], building_path: Path) -> tuple[list[QAIssue], float]:
    """Analyze a single building param file and return issues + score.

    Returns:
        Tuple of (issues list, quality score 0-100)
    """
    issues: list[QAIssue] = []
    name = params.get("building_name") or building_path.stem

    # Check windows_detail
    windows_detail = params.get("windows_detail") or []
    if not windows_detail:
        issues.append(QAIssue(
            category="missing_windows_detail",
            severity="error",
            message=f"{name}: no windows_detail entries"
        ))

    # Check doors_detail
    doors_detail = params.get("doors_detail")
    if doors_detail is None:
        issues.append(QAIssue(
            category="missing_doors_detail",
            severity="warning",
            message=f"{name}: no doors_detail"
        ))

    # Check roof_type
    if not params.get("roof_type"):
        issues.append(QAIssue(
            category="missing_roof_type",
            severity="error",
            message=f"{name}: no roof_type"
        ))

    # Check height mismatch (total_height_m vs city_data.height_avg_m)
    # Skip when city_data is clearly aggregated massing (not individual building):
    #   - city_data.height_avg_m > 25m for buildings with <=3 floors (block-level aggregate)
    #   - city_data.height_avg_m < 2m (footprint fragment / data error)
    total_height = params.get("total_height_m")
    city_data = params.get("city_data") or {}
    height_avg = city_data.get("height_avg_m")
    floors = params.get("floors") or 0
    if total_height and height_avg:
        try:
            th = float(total_height)
            ha = float(height_avg)
            floors_n = int(floors) if floors else 0
            # Skip clearly unreliable city_data (aggregated massing)
            # Conservative per-floor max: 4.5m/floor + 1m parapet
            plausible_max = floors_n * 4.5 + 1.0 if floors_n > 0 else 30.0
            city_data_suspect = (
                ha > plausible_max
                or ha < 2.0
                or ha == 0
            )
            if ha > 0 and not city_data_suspect and abs(th - ha) / ha > 0.5:
                issues.append(QAIssue(
                    category="height_mismatch",
                    severity="warning",
                    message=f"{name}: total_height_m={th:.2f}m vs city_data.height_avg_m={ha:.2f}m (>50% diff)"
                ))
        except (TypeError, ValueError):
            pass

    # Check brick_colour_hex for brick buildings
    facade_material = (params.get("facade_material") or "").lower()
    if "brick" in facade_material:
        facade_detail = params.get("facade_detail") or {}
        if not facade_detail.get("brick_colour_hex"):
            issues.append(QAIssue(
                category="missing_brick_colour",
                severity="warning",
                message=f"{name}: brick building but no facade_detail.brick_colour_hex"
            ))

    # Check decorative_elements
    decorative = params.get("decorative_elements")
    if decorative is None or not decorative:
        issues.append(QAIssue(
            category="missing_decorative_elements",
            severity="info",
            message=f"{name}: no decorative_elements"
        ))

    # Check deep_facade_analysis
    if not params.get("deep_facade_analysis"):
        issues.append(QAIssue(
            category="missing_deep_facade_analysis",
            severity="info",
            message=f"{name}: no deep_facade_analysis"
        ))

    # Check photo_observations
    if not params.get("photo_observations"):
        issues.append(QAIssue(
            category="missing_photo_observations",
            severity="info",
            message=f"{name}: no photo_observations"
        ))

    # Check storefront conflict
    storefront = params.get("storefront")
    has_storefront = params.get("has_storefront")
    if storefront and not has_storefront:
        issues.append(QAIssue(
            category="storefront_conflict",
            severity="warning",
            message=f"{name}: has storefront object but has_storefront=false"
        ))

    # Check floor_heights_m
    floors = params.get("floors")
    floor_heights = params.get("floor_heights_m") or []
    if floors is not None and floor_heights:
        try:
            if int(floors) != len(floor_heights):
                issues.append(QAIssue(
                    category="floor_heights_mismatch",
                    severity="warning",
                    message=f"{name}: floors={floors} but floor_heights_m has {len(floor_heights)} entries"
                ))
        except (TypeError, ValueError):
            pass
    elif not floor_heights and floors:
        issues.append(QAIssue(
            category="missing_floor_heights",
            severity="warning",
            message=f"{name}: no floor_heights_m despite having floors={floors}"
        ))

    # Compute quality score (0-100)
    # Start at 100, deduct by severity and category importance
    score = 100.0
    for issue in issues:
        if issue.severity == "error":
            score -= 15.0
        elif issue.severity == "warning":
            score -= 8.0
        else:  # info
            score -= 2.0

    score = max(0.0, score)

    return issues, score


def _scan_params(
    params_dir: Path,
    output_dir: Path,
    photo_index: dict[str, str],
) -> dict[str, Any]:
    """Scan all param files and return comprehensive report."""
    buildings: list[dict[str, Any]] = []
    issues_by_category: dict[str, int] = {}
    skipped_count = 0
    street_stats: dict[str, dict[str, Any]] = {}

    for path in sorted(params_dir.glob("*.json")):
        # Skip metadata files
        if path.name.startswith("_"):
            continue

        # Skip backup files
        if "backup" in path.name.lower():
            continue

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            buildings.append({
                "file": path.name,
                "building_name": path.stem,
                "address": path.stem,
                "street": "",
                "issues": [QAIssue(
                    category="invalid_json",
                    severity="error",
                    message="Invalid JSON file"
                ).as_dict()],
                "score": 0.0,
                "has_render": False,
                "has_photo": False,
            })
            continue

        # Skip marked-as-skipped files
        if data.get("skipped"):
            skipped_count += 1
            continue

        # Analyze building
        issues, score = _check_building(data, path)

        # Extract address and street
        site = data.get("site") or {}
        building_name = data.get("building_name") or path.stem
        address = site.get("street_number", "")
        if address and site.get("street"):
            address = f"{address} {site.get('street')}"
        else:
            address = building_name

        street = site.get("street") or _extract_street_from_name(building_name)

        # Check render and photo
        has_render = _has_render(building_name, output_dir)
        has_photo = _has_photo(address, photo_index)

        # Tally issues by category
        for issue in issues:
            cat = issue.category
            issues_by_category[cat] = issues_by_category.get(cat, 0) + 1

        # Update street stats
        if street not in street_stats:
            street_stats[street] = {
                "total": 0,
                "zero_issues": 0,
                "with_renders": 0,
                "with_photos": 0,
            }
        street_stats[street]["total"] += 1
        if not issues:
            street_stats[street]["zero_issues"] += 1
        if has_render:
            street_stats[street]["with_renders"] += 1
        if has_photo:
            street_stats[street]["with_photos"] += 1

        buildings.append({
            "file": path.name,
            "building_name": building_name,
            "address": address,
            "street": street,
            "issues": [issue.as_dict() for issue in issues],
            "score": round(score, 1),
            "has_render": has_render,
            "has_photo": has_photo,
        })

    # Compute aggregates
    buildings_with_issues = sum(1 for b in buildings if b["issues"])
    zero_issue_count = sum(1 for b in buildings if not b["issues"])
    avg_score = sum(b["score"] for b in buildings) / len(buildings) if buildings else 0.0
    zero_issue_pct = (zero_issue_count / len(buildings) * 100) if buildings else 0.0

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "params_dir": str(params_dir),
        "total_buildings_scanned": len(buildings),
        "skipped_files": skipped_count,
        "buildings_with_issues": buildings_with_issues,
        "buildings_with_zero_issues": zero_issue_count,
        "zero_issue_percentage": round(zero_issue_pct, 1),
        "average_quality_score": round(avg_score, 1),
        "issues_by_category": issues_by_category,
        "street_stats": street_stats,
        "buildings": buildings,
    }


def _generate_html_dashboard(report: dict[str, Any], output_path: Path) -> None:
    """Generate a self-contained HTML dashboard from the report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Summary stats
    total = report["total_buildings_scanned"]
    zero_issues = report["buildings_with_zero_issues"]
    zero_pct = report["zero_issue_percentage"]
    avg_score = report["average_quality_score"]

    # Top issues by category
    issues_by_cat = sorted(
        report["issues_by_category"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    # Street stats sorted by completion %
    streets_sorted = sorted(
        report["street_stats"].items(),
        key=lambda x: (x[1]["zero_issues"] / x[1]["total"] * 100) if x[1]["total"] > 0 else 0,
        reverse=True
    )

    # Buildings sorted by score (lowest first to show problem cases)
    buildings_sorted = sorted(report["buildings"], key=lambda x: x["score"])

    # Determine color class for score
    def score_color(score):
        if score >= 95:
            return "excellent"
        elif score >= 85:
            return "good"
        elif score >= 70:
            return "fair"
        elif score >= 50:
            return "poor"
        else:
            return "critical"

    # Build HTML
    html_parts = [
        """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QA Dashboard - Kensington Market Buildings</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }

        .header {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: white;
            padding: 3rem 2rem;
            text-align: center;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }

        .header h1 {
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
        }

        .header p {
            font-size: 1rem;
            opacity: 0.9;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }

        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1.5rem;
            margin-bottom: 3rem;
        }

        .stat-card {
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .stat-card h3 {
            font-size: 0.9rem;
            color: #666;
            text-transform: uppercase;
            margin-bottom: 0.5rem;
            font-weight: 600;
        }

        .stat-card .value {
            font-size: 2.5rem;
            font-weight: bold;
            color: #1a1a2e;
        }

        .stat-card .subtext {
            font-size: 0.85rem;
            color: #999;
            margin-top: 0.5rem;
        }

        .section {
            margin-bottom: 3rem;
        }

        .section h2 {
            font-size: 1.5rem;
            margin-bottom: 1.5rem;
            color: #1a1a2e;
            border-bottom: 3px solid #0066cc;
            padding-bottom: 0.5rem;
        }

        .chart-container {
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .bar-chart {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .bar-item {
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .bar-label {
            min-width: 150px;
            font-size: 0.9rem;
            font-weight: 500;
        }

        .bar-wrapper {
            flex: 1;
            background: #f0f0f0;
            border-radius: 4px;
            overflow: hidden;
            height: 30px;
        }

        .bar {
            height: 100%;
            background: linear-gradient(90deg, #0066cc, #0052a3);
            display: flex;
            align-items: center;
            justify-content: flex-end;
            padding-right: 10px;
            color: white;
            font-size: 0.85rem;
            font-weight: 600;
        }

        .bar-value {
            min-width: 40px;
            text-align: right;
            font-size: 0.9rem;
            color: #666;
        }

        .table-wrapper {
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .table-controls {
            padding: 1.5rem;
            border-bottom: 1px solid #eee;
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            align-items: center;
        }

        .table-controls label {
            font-weight: 600;
            font-size: 0.9rem;
        }

        .table-controls select,
        .table-controls input {
            padding: 0.5rem 0.75rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 0.9rem;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        thead {
            background: #f9f9f9;
            border-bottom: 2px solid #ddd;
        }

        th {
            padding: 1rem;
            text-align: left;
            font-weight: 600;
            font-size: 0.9rem;
            color: #1a1a2e;
            cursor: pointer;
            user-select: none;
            white-space: nowrap;
        }

        th:hover {
            background: #f0f0f0;
        }

        td {
            padding: 0.75rem 1rem;
            border-bottom: 1px solid #f0f0f0;
        }

        tr:hover {
            background: #fafafa;
        }

        .score-badge {
            display: inline-block;
            padding: 0.4rem 0.8rem;
            border-radius: 4px;
            font-weight: 600;
            font-size: 0.85rem;
            color: white;
        }

        .score-excellent { background: #28a745; }
        .score-good { background: #66bb6a; }
        .score-fair { background: #ffc107; color: #333; }
        .score-poor { background: #ff9800; }
        .score-critical { background: #dc3545; }

        .issue-list {
            max-height: 150px;
            overflow-y: auto;
            font-size: 0.8rem;
            background: #f9f9f9;
            border-radius: 4px;
            padding: 0.5rem;
        }

        .issue-item {
            padding: 0.25rem;
            margin: 0.25rem 0;
            border-left: 3px solid #999;
            padding-left: 0.5rem;
        }

        .issue-error { border-left-color: #dc3545; color: #c82333; }
        .issue-warning { border-left-color: #ff9800; color: #e68a00; }
        .issue-info { border-left-color: #0066cc; color: #0052a3; }

        .checkmark {
            display: inline-block;
            width: 20px;
            height: 20px;
            text-align: center;
            line-height: 20px;
        }

        .checkmark.yes { color: #28a745; font-weight: bold; }
        .checkmark.no { color: #ccc; }

        .render-link {
            color: #0066cc;
            text-decoration: none;
        }

        .render-link:hover {
            text-decoration: underline;
        }

        .hidden { display: none; }

        footer {
            background: #f0f0f0;
            padding: 1.5rem;
            text-align: center;
            font-size: 0.85rem;
            color: #666;
        }

        @media (max-width: 768px) {
            .summary-grid {
                grid-template-columns: 1fr;
            }

            .header h1 {
                font-size: 1.8rem;
            }

            .table-controls {
                flex-direction: column;
                align-items: flex-start;
            }

            .bar-label {
                min-width: 100px;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>QA Dashboard</h1>
        <p>Kensington Market Historic Buildings Parameter Quality Assessment</p>
        <p style="font-size: 0.9rem; margin-top: 0.5rem;">Generated: """ + report["generated_at"] + """</p>
    </div>

    <div class="container">
        <!-- Summary Cards -->
        <div class="summary-grid">
            <div class="stat-card">
                <h3>Total Buildings</h3>
                <div class="value">""" + str(total) + """</div>
                <div class="subtext">Scanned and analyzed</div>
            </div>
            <div class="stat-card">
                <h3>Zero Issues</h3>
                <div class="value">""" + str(zero_issues) + """</div>
                <div class="subtext">""" + f"{zero_pct:.1f}% of buildings" + """</div>
            </div>
            <div class="stat-card">
                <h3>Average Quality</h3>
                <div class="value">""" + f"{avg_score:.1f}" + """</div>
                <div class="subtext">Score out of 100</div>
            </div>
            <div class="stat-card">
                <h3>Skipped Files</h3>
                <div class="value">""" + str(report["skipped_files"]) + """</div>
                <div class="subtext">Non-building entries</div>
            </div>
        </div>

        <!-- Street Completion Chart -->
        <div class="section">
            <h2>Street Completion Rates</h2>
            <div class="chart-container">
                <div class="bar-chart">
"""
    ]

    for street, stats in streets_sorted:
        total_st = stats["total"]
        zero_st = stats["zero_issues"]
        pct = (zero_st / total_st * 100) if total_st > 0 else 0
        html_parts.append(f"""
                    <div class="bar-item">
                        <div class="bar-label">{street or "(no street)"}</div>
                        <div class="bar-wrapper">
                            <div class="bar" style="width: {pct:.1f}%">
                                {zero_st}/{total_st}
                            </div>
                        </div>
                        <div class="bar-value">{pct:.0f}%</div>
                    </div>
""")

    html_parts.append("""
                </div>
            </div>
        </div>

        <!-- Top Issues Chart -->
        <div class="section">
            <h2>Top Issues by Category</h2>
            <div class="chart-container">
                <div class="bar-chart">
""")

    max_issues = max([count for _, count in issues_by_cat], default=1)
    for cat, count in issues_by_cat[:15]:
        pct = (count / max_issues * 100) if max_issues > 0 else 0
        cat_display = cat.replace("_", " ").title()
        html_parts.append(f"""
                    <div class="bar-item">
                        <div class="bar-label">{cat_display}</div>
                        <div class="bar-wrapper">
                            <div class="bar" style="width: {pct:.1f}%">
                                {count}
                            </div>
                        </div>
                        <div class="bar-value">{count}</div>
                    </div>
""")

    html_parts.append("""
                </div>
            </div>
        </div>

        <!-- Buildings Table -->
        <div class="section">
            <h2>All Buildings</h2>
            <div class="table-wrapper">
                <div class="table-controls">
                    <label for="street-filter">Filter by Street:</label>
                    <select id="street-filter">
                        <option value="">All Streets</option>
""")

    for street in sorted(set(b["street"] for b in buildings_sorted)):
        html_parts.append(f'                        <option value="{street}">{street or "(no street)"}</option>\n')

    html_parts.append("""
                    </select>
                    <label for="score-filter">Min Score:</label>
                    <input type="number" id="score-filter" min="0" max="100" value="0" style="width: 60px;">
                </div>
                <table>
                    <thead>
                        <tr>
                            <th onclick="sortTable(0)">Address</th>
                            <th onclick="sortTable(1)">Street</th>
                            <th onclick="sortTable(2)">Score</th>
                            <th>Issues</th>
                            <th>Render</th>
                            <th>Photo</th>
                        </tr>
                    </thead>
                    <tbody id="buildings-table">
""")

    for building in buildings_sorted:
        score = building["score"]
        color_class = score_color(score)
        issues_html = ""
        if building["issues"]:
            issues_html = '<div class="issue-list">'
            for issue in building["issues"][:5]:
                severity = issue["severity"]
                cat = issue["category"].replace("_", " ")
                issues_html += f'<div class="issue-item issue-{severity}">{cat}</div>'
            if len(building["issues"]) > 5:
                issues_html += f'<div class="issue-item">... +{len(building["issues"]) - 5} more</div>'
            issues_html += '</div>'
        else:
            issues_html = '<div style="color: #28a745; font-weight: 600;">All good</div>'

        render_icon = '<span class="checkmark yes">✓</span>' if building["has_render"] else '<span class="checkmark no">–</span>'
        photo_icon = '<span class="checkmark yes">✓</span>' if building["has_photo"] else '<span class="checkmark no">–</span>'

        html_parts.append(f"""
                        <tr class="building-row" data-street="{building['street']}" data-score="{score}">
                            <td>{building['address']}</td>
                            <td>{building['street']}</td>
                            <td><span class="score-badge score-{color_class}">{score:.1f}</span></td>
                            <td>{issues_html}</td>
                            <td style="text-align: center;">{render_icon}</td>
                            <td style="text-align: center;">{photo_icon}</td>
                        </tr>
""")

    html_parts.append("""
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <footer>
        <p>Kensington Market QA Report &mdash;
        <strong>""" + f"{zero_issues}" + """</strong> buildings with zero issues •
        <strong>""" + f"{report['buildings_with_issues']}" + """</strong> buildings with issues •
        Average quality: <strong>""" + f"{avg_score:.1f}/100" + """</strong></p>
    </footer>

    <script>
        let sortColumn = null;
        let sortAscending = true;

        function filterTable() {
            const streetFilter = document.getElementById('street-filter').value;
            const scoreFilter = parseFloat(document.getElementById('score-filter').value) || 0;
            const rows = document.querySelectorAll('.building-row');

            rows.forEach(row => {
                const street = row.dataset.street;
                const score = parseFloat(row.dataset.score);

                const matchStreet = !streetFilter || street === streetFilter;
                const matchScore = score >= scoreFilter;

                row.style.display = (matchStreet && matchScore) ? '' : 'none';
            });
        }

        function sortTable(colIndex) {
            const tbody = document.getElementById('buildings-table');
            const rows = Array.from(tbody.querySelectorAll('tr'));

            if (sortColumn === colIndex) {
                sortAscending = !sortAscending;
            } else {
                sortColumn = colIndex;
                sortAscending = true;
            }

            rows.sort((a, b) => {
                let aVal = a.cells[colIndex].textContent.trim();
                let bVal = b.cells[colIndex].textContent.trim();

                // Try numeric comparison for columns 1 and 2
                if (colIndex === 2) {
                    aVal = parseFloat(aVal) || 0;
                    bVal = parseFloat(bVal) || 0;
                } else {
                    aVal = aVal.toLowerCase();
                    bVal = bVal.toLowerCase();
                }

                if (aVal < bVal) return sortAscending ? -1 : 1;
                if (aVal > bVal) return sortAscending ? 1 : -1;
                return 0;
            });

            rows.forEach(row => tbody.appendChild(row));
        }

        document.getElementById('street-filter').addEventListener('change', filterTable);
        document.getElementById('score-filter').addEventListener('input', filterTable);
    </script>
</body>
</html>
""")

    output_path.write_text("".join(html_parts), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate comprehensive QA report with HTML dashboard for building params."
    )
    parser.add_argument(
        "--params-dir",
        default=str(PARAMS_DIR),
        help="Directory containing params/*.json (default: params/)"
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help="Output directory for reports (default: outputs/)"
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()
    params_dir = Path(args.params_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    output_json = output_dir / "qa_report.json"
    output_html = output_dir / "qa_dashboard.html"

    print(f"[qa] Scanning params directory: {params_dir}")

    # Load photo index
    photo_index = _load_photo_index()
    print(f"[qa] Loaded {len(photo_index)} photo index entries")

    # Scan params
    report = _scan_params(params_dir, output_dir, photo_index)

    # Write JSON report
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[qa] JSON report: {output_json}")

    # Generate HTML dashboard
    _generate_html_dashboard(report, output_html)
    print(f"[qa] HTML dashboard: {output_html}")

    # Print summary
    print(f"\n[qa] === SUMMARY ===")
    print(f"[qa] Total buildings: {report['total_buildings_scanned']}")
    print(f"[qa] Buildings with zero issues: {report['buildings_with_zero_issues']} ({report['zero_issue_percentage']:.1f}%)")
    print(f"[qa] Buildings with issues: {report['buildings_with_issues']}")
    print(f"[qa] Average quality score: {report['average_quality_score']:.1f}/100")
    print(f"[qa] Skipped files: {report['skipped_files']}")
    print(f"\n[qa] Top issue categories:")
    for cat, count in sorted(report["issues_by_category"].items(), key=lambda x: x[1], reverse=True)[:5]:
        print(f"[qa]   {cat}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
