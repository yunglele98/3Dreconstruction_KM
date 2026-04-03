"""
generate_dashboard.py
Generates an interactive HTML dashboard from visual audit results.

Input:  outputs/visual_audit/audit_report.json
Output: outputs/visual_audit/dashboard.html
"""

import json
import pathlib

_MERGED = pathlib.Path(
    r"C:\Users\liam1\blender_buildings\outputs\visual_audit\audit_report_merged.json"
)
_BASE = pathlib.Path(
    r"C:\Users\liam1\blender_buildings\outputs\visual_audit\audit_report.json"
)
INPUT_PATH = _MERGED if _MERGED.exists() else _BASE
OUTPUT_PATH = pathlib.Path(
    r"C:\Users\liam1\blender_buildings\outputs\visual_audit\dashboard.html"
)

TIER_ORDER = ["Critical", "High", "Medium", "Low", "Acceptable", "No Photo"]
TIER_COLORS = {
    "Critical":   "#e63946",
    "High":       "#f4a261",
    "Medium":     "#e9c46a",
    "Low":        "#2a9d8f",
    "Acceptable": "#6c757d",
    "No Photo":   "#343a40",
}


def load_buildings(path: pathlib.Path) -> list:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    buildings = data.get("buildings", data) if isinstance(data, dict) else data
    return buildings


def compute_stats(buildings: list) -> dict:
    total = len(buildings)
    tier_counts = {t: 0 for t in TIER_ORDER}
    gap_scores = []

    for b in buildings:
        raw_tier = b.get("tier", "No Photo")
        # Normalize lowercase tiers to title case
        tier = raw_tier.replace("_", " ").title() if isinstance(raw_tier, str) else "No Photo"
        if tier not in tier_counts:
            tier_counts["No Photo"] += 1
        else:
            tier_counts[tier] += 1

        score = b.get("gap_score")
        if score is not None:
            try:
                gap_scores.append(float(score))
            except (TypeError, ValueError):
                pass

    avg_gap = round(sum(gap_scores) / len(gap_scores), 2) if gap_scores else 0.0

    tier_stats = []
    for tier in TIER_ORDER:
        count = tier_counts[tier]
        pct = round(count / total * 100, 1) if total else 0.0
        tier_stats.append({
            "tier":  tier,
            "count": count,
            "pct":   pct,
            "color": TIER_COLORS[tier],
        })

    # street summary
    street_map = {}
    for b in buildings:
        street = b.get("street", "Unknown")
        score = b.get("gap_score")
        if score is not None:
            try:
                street_map.setdefault(street, []).append(float(score))
            except (TypeError, ValueError):
                pass

    street_summary = sorted(
        [
            {"street": s, "avg": round(sum(v) / len(v), 2), "count": len(v)}
            for s, v in street_map.items()
        ],
        key=lambda x: x["avg"],
        reverse=True,
    )

    # issue distribution
    issue_map = {}
    for b in buildings:
        issue = b.get("primary_issue", "Unknown")
        if isinstance(issue, dict):
            issue = issue.get("type", "Unknown")
        if not isinstance(issue, str):
            issue = str(issue) if issue else "Unknown"
        issue_map[issue] = issue_map.get(issue, 0) + 1

    issue_dist = sorted(
        [{"issue": k, "count": v} for k, v in issue_map.items()],
        key=lambda x: x["count"],
        reverse=True,
    )

    return {
        "total":          total,
        "avg_gap":        avg_gap,
        "tier_stats":     tier_stats,
        "street_summary": street_summary,
        "issue_dist":     issue_dist,
    }


def build_html(buildings: list, stats: dict) -> str:
    buildings_json = json.dumps(buildings, ensure_ascii=False)
    stats_json     = json.dumps(stats,     ensure_ascii=False)
    tier_colors_json = json.dumps(TIER_COLORS, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kensington Market \u2014 Visual Audit Dashboard</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg:     #1a1a2e;
    --card:   #16213e;
    --card2:  #0f3460;
    --text:   #eeeeee;
    --muted:  #aaaaaa;
    --border: #2a2a4a;
    --radius: 8px;
  }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    padding: 24px;
  }}

  h1 {{ font-size: 1.6rem; margin-bottom: 4px; }}
  h2 {{ font-size: 1.1rem; margin-bottom: 16px; color: var(--muted); font-weight: 400; }}

  /* ---- Header ---- */
  .header {{ margin-bottom: 28px; }}
  .avg-gap {{
    display: inline-block;
    margin-top: 10px;
    font-size: 2.4rem;
    font-weight: 700;
    color: #e0e0ff;
    letter-spacing: -1px;
  }}
  .avg-gap-label {{
    font-size: 0.85rem;
    color: var(--muted);
    margin-left: 6px;
    vertical-align: middle;
  }}

  /* ---- Stat cards ---- */
  .stat-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 32px;
  }}
  .stat-card {{
    background: var(--card);
    border-radius: var(--radius);
    padding: 16px 14px 14px;
    border-top: 4px solid var(--tier-color, #555);
    cursor: pointer;
  }}
  .stat-card .tier-name {{
    font-size: 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .5px;
  }}
  .stat-card .count {{
    font-size: 2rem;
    font-weight: 700;
    line-height: 1;
    margin: 4px 0;
  }}
  .stat-card .pct {{ font-size: 0.8rem; color: var(--muted); }}

  /* ---- Controls ---- */
  .controls {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 20px;
    align-items: center;
  }}
  .controls select,
  .controls input {{
    background: var(--card);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 7px 12px;
    font-size: 0.85rem;
    outline: none;
    min-width: 140px;
  }}
  .controls select:focus,
  .controls input:focus {{ border-color: #4a4a8a; }}
  .sort-group {{ display: flex; align-items: center; gap: 6px; margin-left: auto; }}
  .sort-group label {{ font-size: 0.8rem; color: var(--muted); }}

  /* ---- Building grid ---- */
  .building-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 14px;
    margin-bottom: 40px;
  }}
  .building-card {{
    background: var(--card);
    border-radius: var(--radius);
    padding: 14px;
    border-left: 5px solid var(--tier-color, #555);
    cursor: pointer;
    transition: transform .15s, box-shadow .15s;
    text-decoration: none;
    color: inherit;
    display: block;
  }}
  .building-card:hover {{
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(0,0,0,.4);
  }}
  .building-card.hidden {{ display: none; }}

  .card-address {{
    font-size: 0.9rem;
    font-weight: 600;
    margin-bottom: 8px;
    word-break: break-word;
  }}

  .gap-bar-wrap {{ margin-bottom: 8px; }}
  .gap-bar-track {{
    background: #2a2a4a;
    border-radius: 4px;
    height: 8px;
    overflow: hidden;
  }}
  .gap-bar-fill {{
    height: 100%;
    border-radius: 4px;
    background: var(--tier-color, #555);
  }}
  .gap-score-label {{ font-size: 0.75rem; color: var(--muted); margin-top: 3px; }}

  .badge-row {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
  .badge {{
    font-size: 0.68rem;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 20px;
    text-transform: uppercase;
    letter-spacing: .3px;
    white-space: nowrap;
  }}
  .badge-tier  {{ background: var(--tier-color, #555); color: #fff; }}
  .badge-issue {{ background: #2a2a4a; color: var(--muted); border: 1px solid #3a3a6a; }}

  /* ---- No results ---- */
  .no-results {{
    display: none;
    color: var(--muted);
    padding: 32px 0;
    text-align: center;
    font-size: 1rem;
  }}

  /* ---- Sections ---- */
  .section {{ margin-bottom: 40px; }}
  .section-title {{
    font-size: 1rem;
    font-weight: 600;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 16px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--border);
  }}

  /* ---- Bar charts (CSS only) ---- */
  .bar-chart {{ display: flex; flex-direction: column; gap: 8px; }}
  .bar-row {{ display: flex; align-items: center; gap: 10px; }}
  .bar-label {{
    width: 200px;
    font-size: 0.8rem;
    color: var(--text);
    text-align: right;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex-shrink: 0;
  }}
  .bar-track {{
    flex: 1;
    background: #2a2a4a;
    border-radius: 4px;
    height: 18px;
    overflow: hidden;
  }}
  .bar-fill {{
    height: 100%;
    border-radius: 4px;
    background: #4a6fa5;
    display: flex;
    align-items: center;
    padding-left: 6px;
    min-width: 2px;
  }}
  .bar-fill.issue-fill {{ background: #7b5ea7; }}
  .bar-value {{ font-size: 0.72rem; color: #fff; white-space: nowrap; }}
  .bar-count {{ width: 50px; font-size: 0.75rem; color: var(--muted); flex-shrink: 0; }}

  /* ---- Result count ---- */
  .result-count {{ font-size: 0.8rem; color: var(--muted); margin-bottom: 10px; }}

  /* ---- Responsive ---- */
  @media (max-width: 900px) {{
    .building-grid {{ grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }}
  }}
  @media (max-width: 600px) {{
    .building-grid {{ grid-template-columns: 1fr 1fr; }}
    .bar-label {{ width: 110px; }}
  }}
  @media (max-width: 420px) {{
    .building-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>Kensington Market \u2014 Visual Audit</h1>
  <h2>3D Reconstruction Quality Review</h2>
  <div>
    <span class="avg-gap" id="avg-gap-display">\u2014</span>
    <span class="avg-gap-label">avg gap score</span>
  </div>
</div>

<div class="stat-grid" id="stat-grid"></div>

<div class="controls">
  <select id="filter-tier"><option value="">All Tiers</option></select>
  <select id="filter-street"><option value="">All Streets</option></select>
  <select id="filter-issue"><option value="">All Issue Types</option></select>
  <input type="search" id="filter-search" placeholder="Search address\u2026">
  <div class="sort-group">
    <label for="sort-select">Sort:</label>
    <select id="sort-select">
      <option value="gap_desc">Gap Score \u2193</option>
      <option value="gap_asc">Gap Score \u2191</option>
      <option value="address_asc">Address A\u2013Z</option>
      <option value="address_desc">Address Z\u2013A</option>
      <option value="street_asc">Street A\u2013Z</option>
    </select>
  </div>
</div>

<div class="result-count" id="result-count"></div>
<div class="building-grid" id="building-grid"></div>
<div class="no-results" id="no-results">No buildings match the current filters.</div>

<div class="section">
  <div class="section-title">Street Summary \u2014 Avg Gap Score</div>
  <div class="bar-chart" id="street-chart"></div>
</div>

<div class="section">
  <div class="section-title">Issue Distribution</div>
  <div class="bar-chart" id="issue-chart"></div>
</div>

<script>
const BUILDINGS   = {buildings_json};
const STATS       = {stats_json};
const TIER_COLORS = {tier_colors_json};
const TIER_ORDER  = ["Critical","High","Medium","Low","Acceptable","No Photo"];

function tier_color(tier) {{
  return TIER_COLORS[tier] || "#555";
}}

function gap_bar_width(score) {{
  if (score == null) return 0;
  return Math.min(100, Math.max(0, parseFloat(score) * 10));
}}

function safe_filename(addr) {{
  return addr.replace(/[^a-zA-Z0-9_\\-. ]/g, "_");
}}

// ---- Stat cards ----
function render_stat_cards() {{
  const grid = document.getElementById("stat-grid");
  STATS.tier_stats.forEach(t => {{
    const div = document.createElement("div");
    div.className = "stat-card";
    div.style.setProperty("--tier-color", t.color);
    div.title = "Click to filter by " + t.tier;
    div.innerHTML =
      '<div class="tier-name">' + t.tier + '</div>' +
      '<div class="count">' + t.count + '</div>' +
      '<div class="pct">' + t.pct + '% of total</div>';
    div.addEventListener("click", () => {{
      const sel = document.getElementById("filter-tier");
      sel.value = sel.value === t.tier ? "" : t.tier;
      apply_filters();
    }});
    grid.appendChild(div);
  }});
  document.getElementById("avg-gap-display").textContent = STATS.avg_gap.toFixed(2);
}}

// ---- Dropdowns ----
function populate_filters() {{
  const tier_sel = document.getElementById("filter-tier");
  TIER_ORDER.forEach(t => {{
    const o = document.createElement("option");
    o.value = t; o.textContent = t;
    tier_sel.appendChild(o);
  }});

  const streets = [...new Set(BUILDINGS.map(b => b.street || "Unknown"))].sort();
  const st_sel = document.getElementById("filter-street");
  streets.forEach(s => {{
    const o = document.createElement("option");
    o.value = s; o.textContent = s;
    st_sel.appendChild(o);
  }});

  const issues = [...new Set(BUILDINGS.map(b => b.primary_issue || "Unknown"))].sort();
  const is_sel = document.getElementById("filter-issue");
  issues.forEach(i => {{
    const o = document.createElement("option");
    o.value = i; o.textContent = i;
    is_sel.appendChild(o);
  }});
}}

// ---- Building cards ----
function render_building_cards() {{
  const grid = document.getElementById("building-grid");
  grid.innerHTML = "";
  BUILDINGS.forEach((b, idx) => {{
    const tier  = b.tier || "No Photo";
    const color = tier_color(tier);
    const score = b.gap_score != null ? parseFloat(b.gap_score).toFixed(2) : "N/A";
    const width = gap_bar_width(b.gap_score);
    const addr  = b.address || b.name || ("Building " + (idx + 1));
    const issue = b.primary_issue || "";

    const a = document.createElement("a");
    a.className = "building-card";
    a.style.setProperty("--tier-color", color);
    a.href   = "comparisons/" + safe_filename(addr) + ".png";
    a.target = "_blank";
    a.rel    = "noopener";
    a.dataset.tier    = tier;
    a.dataset.street  = b.street || "Unknown";
    a.dataset.issue   = issue;
    a.dataset.address = addr.toLowerCase();
    a.dataset.score   = b.gap_score != null ? b.gap_score : -1;

    a.innerHTML =
      '<div class="card-address">' + addr + '</div>' +
      '<div class="gap-bar-wrap">' +
        '<div class="gap-bar-track">' +
          '<div class="gap-bar-fill" style="width:' + width + '%"></div>' +
        '</div>' +
        '<div class="gap-score-label">Gap score: ' + score + '</div>' +
      '</div>' +
      '<div class="badge-row">' +
        '<span class="badge badge-tier" style="background:' + color + '">' + tier + '</span>' +
        (issue ? '<span class="badge badge-issue">' + issue + '</span>' : '') +
      '</div>';

    grid.appendChild(a);
  }});
}}

// ---- Filter + sort ----
function apply_filters() {{
  const tier_val   = document.getElementById("filter-tier").value;
  const street_val = document.getElementById("filter-street").value;
  const issue_val  = document.getElementById("filter-issue").value;
  const search_val = document.getElementById("filter-search").value.toLowerCase().trim();
  const sort_val   = document.getElementById("sort-select").value;

  const grid  = document.getElementById("building-grid");
  const cards = Array.from(grid.querySelectorAll(".building-card"));
  let visible = [];

  cards.forEach(c => {{
    const show =
      (!tier_val   || c.dataset.tier   === tier_val)   &&
      (!street_val || c.dataset.street === street_val) &&
      (!issue_val  || c.dataset.issue  === issue_val)  &&
      (!search_val || c.dataset.address.includes(search_val));
    c.classList.toggle("hidden", !show);
    if (show) visible.push(c);
  }});

  visible.sort((a, b) => {{
    if (sort_val === "gap_desc")     return parseFloat(b.dataset.score) - parseFloat(a.dataset.score);
    if (sort_val === "gap_asc")      return parseFloat(a.dataset.score) - parseFloat(b.dataset.score);
    if (sort_val === "address_asc")  return a.dataset.address.localeCompare(b.dataset.address);
    if (sort_val === "address_desc") return b.dataset.address.localeCompare(a.dataset.address);
    if (sort_val === "street_asc")   return a.dataset.street.localeCompare(b.dataset.street);
    return 0;
  }});
  visible.forEach(c => grid.appendChild(c));

  document.getElementById("result-count").textContent =
    visible.length + " of " + cards.length + " buildings shown";
  document.getElementById("no-results").style.display =
    visible.length === 0 ? "block" : "none";
}}

// ---- Street chart ----
function render_street_chart() {{
  const container = document.getElementById("street-chart");
  const max_val = Math.max(...STATS.street_summary.map(s => s.avg), 0.01);
  STATS.street_summary.forEach(s => {{
    const pct = Math.min(100, (s.avg / max_val) * 100).toFixed(1);
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML =
      '<div class="bar-label" title="' + s.street + '">' + s.street + '</div>' +
      '<div class="bar-track">' +
        '<div class="bar-fill" style="width:' + pct + '%">' +
          '<span class="bar-value">' + s.avg.toFixed(2) + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="bar-count">' + s.count + ' bldg' + (s.count !== 1 ? 's' : '') + '</div>';
    container.appendChild(row);
  }});
}}

// ---- Issue chart ----
function render_issue_chart() {{
  const container = document.getElementById("issue-chart");
  const max_val = Math.max(...STATS.issue_dist.map(i => i.count), 1);
  STATS.issue_dist.forEach(i => {{
    const pct = Math.min(100, (i.count / max_val) * 100).toFixed(1);
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML =
      '<div class="bar-label" title="' + i.issue + '">' + i.issue + '</div>' +
      '<div class="bar-track">' +
        '<div class="bar-fill issue-fill" style="width:' + pct + '%">' +
          '<span class="bar-value">' + i.count + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="bar-count"></div>';
    container.appendChild(row);
  }});
}}

// ---- Init ----
(function init() {{
  render_stat_cards();
  populate_filters();
  render_building_cards();
  apply_filters();
  render_street_chart();
  render_issue_chart();

  ["filter-tier","filter-street","filter-issue","sort-select"].forEach(id => {{
    document.getElementById(id).addEventListener("change", apply_filters);
  }});
  document.getElementById("filter-search").addEventListener("input", apply_filters);
}})();
</script>
</body>
</html>
"""
    return html


def main() -> None:
    buildings = load_buildings(INPUT_PATH)
    stats     = compute_stats(buildings)
    html      = build_html(buildings, stats)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")

    print(f"Dashboard written to: {OUTPUT_PATH}")
    print(f"  Buildings : {stats['total']}")
    print(f"  Avg gap   : {stats['avg_gap']}")
    for t in stats["tier_stats"]:
        print(f"  {t['tier']:<12}: {t['count']:>4}  ({t['pct']}%)")


if __name__ == "__main__":
    main()
