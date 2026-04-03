#!/usr/bin/env python3
"""Generate browsable HTML grid for visual-audit results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
_MERGED = REPO_ROOT / "outputs" / "visual_audit" / "audit_report_merged.json"
_BASE = REPO_ROOT / "outputs" / "visual_audit" / "audit_report.json"
DEFAULT_REPORT = _MERGED if _MERGED.exists() else _BASE
DEFAULT_OUTPUT = REPO_ROOT / "outputs" / "visual_audit" / "grid.html"

TIER_COLOURS = {
    "critical": "#e04646",
    "high": "#ee8e42",
    "medium": "#d8c446",
    "low": "#5abf66",
    "acceptable": "#6f7885",
    "no_photo": "#4f5661",
}


def _as_list(value):
    if isinstance(value, list):
        return value
    return []


def _issue_type(building: dict) -> str:
    primary = building.get("primary_issue")
    if isinstance(primary, dict):
        return str(primary.get("type") or "")
    return ""


def _safe_rel(path: str | None, html_output: Path) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    try:
        return str(p.relative_to(html_output.parent)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def build_dataset(report: dict, html_output: Path) -> list[dict]:
    buildings = _as_list(report.get("buildings"))
    dataset = []
    for b in buildings:
        dataset.append(
            {
                "address": b.get("address") or "Unknown",
                "gap_score": b.get("gap_score"),
                "tier": b.get("tier") or "no_photo",
                "street": b.get("street") or "",
                "era": b.get("era") or "",
                "issue_type": _issue_type(b),
                "primary_issue": (b.get("primary_issue") or {}).get("description", "")
                if isinstance(b.get("primary_issue"), dict)
                else "",
                "render": _safe_rel(b.get("render"), html_output),
                "photo": _safe_rel(b.get("photo"), html_output),
                "comparison": _safe_rel(b.get("comparison"), html_output),
                "match_status": b.get("match_status", ""),
            }
        )
    dataset.sort(key=lambda x: x.get("gap_score") or -1, reverse=True)
    return dataset


def render_html(cards: list[dict]) -> str:
    tiers = sorted({c["tier"] for c in cards if c.get("tier")})
    streets = sorted({c["street"] for c in cards if c.get("street")})
    eras = sorted({c["era"] for c in cards if c.get("era")})
    issues = sorted({c["issue_type"] for c in cards if c.get("issue_type")})
    payload = json.dumps(cards, ensure_ascii=False)

    tier_style = "\n".join(
        f'.card[data-tier="{tier}"]' + "{ border-color: " + colour + "; }"
        for tier, colour in TIER_COLOURS.items()
    )

    options = lambda values: "\n".join(  # noqa: E731
        f'<option value="{v}">{v}</option>' for v in values
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Kensington Visual Audit Grid</title>
  <style>
    :root {{
      --bg: #11141a;
      --panel: #1c222c;
      --panel-2: #151a22;
      --txt: #eef2f8;
      --muted: #99a3b3;
      --accent: #59a7ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Inter", sans-serif;
      background: radial-gradient(1600px 800px at 20% -10%, #27364d 0%, var(--bg) 45%);
      color: var(--txt);
    }}
    .wrap {{ max-width: 1500px; margin: 0 auto; padding: 22px; }}
    h1 {{ margin: 0 0 14px; font-size: clamp(20px, 3vw, 30px); }}
    .controls {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      background: rgba(16, 21, 30, 0.85);
      border: 1px solid #2a3340;
      border-radius: 14px;
      padding: 12px;
      position: sticky;
      top: 10px;
      backdrop-filter: blur(6px);
      z-index: 10;
    }}
    input, select {{
      width: 100%;
      border-radius: 10px;
      border: 1px solid #344154;
      background: var(--panel);
      color: var(--txt);
      padding: 9px 10px;
      font-size: 14px;
    }}
    .meta {{ margin: 10px 2px 14px; color: var(--muted); font-size: 14px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 12px;
    }}
    .card {{
      background: linear-gradient(180deg, rgba(37,46,60,.85), rgba(22,28,37,.9));
      border: 2px solid #3a4453;
      border-radius: 12px;
      overflow: hidden;
    }}
    {tier_style}
    .thumb {{
      width: 100%;
      aspect-ratio: 16 / 9;
      object-fit: cover;
      cursor: zoom-in;
      background: #0c1117;
      border-bottom: 1px solid #2c3644;
    }}
    .body {{ padding: 10px; }}
    .addr {{ font-weight: 700; margin-bottom: 6px; }}
    .small {{ font-size: 12px; color: var(--muted); }}
    .pill {{
      display: inline-block;
      margin-right: 6px;
      margin-top: 6px;
      padding: 3px 8px;
      border-radius: 999px;
      border: 1px solid #3b4758;
      background: var(--panel-2);
      font-size: 11px;
      color: #d9e4f5;
    }}
    dialog {{
      border: 1px solid #3a4657;
      background: #0e141d;
      border-radius: 12px;
      padding: 10px;
      width: min(95vw, 1400px);
    }}
    dialog img {{ width: 100%; height: auto; border-radius: 8px; }}
    dialog::backdrop {{ background: rgba(2, 7, 12, 0.72); }}
    .hidden {{ display: none !important; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Kensington Visual Audit</h1>
    <div class="controls">
      <input id="search" type="search" placeholder="Search address..." />
      <select id="tier"><option value="">All tiers</option>{options(tiers)}</select>
      <select id="street"><option value="">All streets</option>{options(streets)}</select>
      <select id="era"><option value="">All eras</option>{options(eras)}</select>
      <select id="issue"><option value="">All issue types</option>{options(issues)}</select>
    </div>
    <div class="meta"><span id="count"></span></div>
    <div class="grid" id="grid"></div>
  </div>
  <dialog id="modal">
    <img id="modalImg" alt="comparison" />
  </dialog>
  <script id="dataset" type="application/json">{payload}</script>
  <script>
    const data = JSON.parse(document.getElementById("dataset").textContent || "[]");
    const grid = document.getElementById("grid");
    const count = document.getElementById("count");
    const modal = document.getElementById("modal");
    const modalImg = document.getElementById("modalImg");
    const controls = {{
      search: document.getElementById("search"),
      tier: document.getElementById("tier"),
      street: document.getElementById("street"),
      era: document.getElementById("era"),
      issue: document.getElementById("issue"),
    }};

    function matches(item) {{
      const q = controls.search.value.trim().toLowerCase();
      if (q && !item.address.toLowerCase().includes(q)) return false;
      if (controls.tier.value && item.tier !== controls.tier.value) return false;
      if (controls.street.value && item.street !== controls.street.value) return false;
      if (controls.era.value && item.era !== controls.era.value) return false;
      if (controls.issue.value && item.issue_type !== controls.issue.value) return false;
      return true;
    }}

    function bestImage(item) {{
      return item.comparison || item.photo || item.render || "";
    }}

    function render() {{
      const filtered = data.filter(matches);
      count.textContent = `${{filtered.length}} / ${{data.length}} buildings`;
      grid.innerHTML = "";
      for (const item of filtered) {{
        const card = document.createElement("article");
        card.className = "card";
        card.dataset.tier = item.tier || "no_photo";
        const score = item.gap_score ?? "N/A";
        const img = bestImage(item);
        card.innerHTML = `
          <img class="thumb ${{img ? "" : "hidden"}}" src="${{img}}" alt="${{item.address}}" loading="lazy" />
          <div class="body">
            <div class="addr">${{item.address}}</div>
            <div class="small">Gap score: ${{score}} | Primary: ${{item.issue_type || "n/a"}}</div>
            <div class="small">${{item.primary_issue || ""}}</div>
            <span class="pill">${{item.tier}}</span>
            <span class="pill">${{item.street || "street n/a"}}</span>
            <span class="pill">${{item.era || "era n/a"}}</span>
          </div>
        `;
        const thumb = card.querySelector(".thumb");
        if (thumb && img) {{
          thumb.addEventListener("click", () => {{
            modalImg.src = img;
            modal.showModal();
          }});
        }}
        grid.appendChild(card);
      }}
    }}

    for (const control of Object.values(controls)) {{
      control.addEventListener("input", render);
      control.addEventListener("change", render);
    }}
    modal.addEventListener("click", () => modal.close());
    render();
  </script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Generate HTML grid for visual-audit report.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    cards = build_dataset(report, args.output)
    html = render_html(cards)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    print(f"Wrote {args.output} ({len(cards)} cards)")


if __name__ == "__main__":
    main()
