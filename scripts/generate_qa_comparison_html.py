#!/usr/bin/env python3
"""
Generate side-by-side QA comparison HTML (field photo vs render).

For buildings with both a rendered .png and a field photo, creates
comparison cards. First 50 use base64 thumbnails; rest are linked.
"""
import base64
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
RENDERS_DIR = ROOT / "outputs" / "full"
PHOTOS_DIR = ROOT / "PHOTOS KENSINGTON"
PHOTO_INDEX = PHOTOS_DIR / "csv" / "photo_address_index.csv"
OUTPUT_FILE = ROOT / "outputs" / "deliverables" / "qa_comparison.html"

MAX_EMBEDDED = 50


def load_photo_index() -> dict:
    index = {}
    if not PHOTO_INDEX.exists():
        return index
    with open(PHOTO_INDEX, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            addr = (row.get("address_or_location") or "").strip()
            fname = (row.get("filename") or "").strip()
            if addr and fname:
                index.setdefault(addr, []).append(fname)
    return index


def find_photo(address: str, photo_index: dict) -> str:
    if address in photo_index:
        return photo_index[address][0]
    addr_lower = address.lower()
    for key, photos in photo_index.items():
        if addr_lower in key.lower() or key.lower() in addr_lower:
            return photos[0]
    return ""


def find_render(param_stem: str) -> str:
    if not RENDERS_DIR.exists():
        return ""
    for ext in (".png", ".jpg"):
        render = RENDERS_DIR / (param_stem + ext)
        if render.exists():
            return str(render)
    return ""


def main():
    photo_index = load_photo_index()

    comparisons = []
    for param_file in sorted(PARAMS_DIR.glob("*.json")):
        if param_file.name.startswith("_") or "backup" in param_file.name:
            continue
        with open(param_file, encoding="utf-8") as f:
            params = json.load(f)
        if params.get("skipped"):
            continue

        address = params.get("building_name", param_file.stem.replace("_", " "))
        photo_name = find_photo(address, photo_index)
        render_path = find_render(param_file.stem)

        if photo_name:
            site = params.get("site", {})
            street = (site.get("street") or "Unknown")
            comparisons.append({
                "address": address,
                "street": street,
                "photo_name": photo_name,
                "photo_path": str(PHOTOS_DIR / photo_name),
                "render_path": render_path,
                "has_render": bool(render_path),
            })

    # Build HTML
    html_parts = ["""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Kensington Market QA Comparison</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; background: #f5f5f5; }
h1 { color: #333; }
.controls { margin: 10px 0; padding: 10px; background: white; border-radius: 8px; }
.controls select, .controls input { padding: 6px; margin: 5px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(500px, 1fr)); gap: 16px; }
.card { background: white; border-radius: 8px; padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.12); }
.card h3 { margin: 0 0 8px; font-size: 14px; color: #333; }
.card .pair { display: flex; gap: 8px; }
.card .pair .img-box { flex: 1; text-align: center; }
.card .pair .img-box img { max-width: 100%; max-height: 200px; border-radius: 4px; }
.card .pair .img-box .label { font-size: 11px; color: #666; margin-top: 4px; }
.no-render { color: #999; font-style: italic; font-size: 12px; }
.hidden { display: none; }
</style>
</head>
<body>
<h1>Kensington Market QA Comparison</h1>
<p>""" + f"{len(comparisons)} buildings with photos" + """</p>
<div class="controls">
<label>Street: <select id="streetFilter" onchange="filterCards()">
<option value="">All</option>
"""]

    streets = sorted(set(c["street"] for c in comparisons))
    for s in streets:
        html_parts.append(f'<option value="{s}">{s}</option>')

    html_parts.append("""</select></label>
<label>Search: <input type="text" id="searchBox" oninput="filterCards()" placeholder="Address..."></label>
</div>
<div class="grid" id="grid">
""")

    for i, comp in enumerate(comparisons):
        street_attr = comp["street"].replace('"', '&quot;')
        addr_attr = comp["address"].replace('"', '&quot;')

        photo_src = f"../../PHOTOS KENSINGTON/{comp['photo_name']}"
        render_html = ""
        if comp["has_render"]:
            render_html = f'<img src="../../outputs/full/{Path(comp["render_path"]).name}" alt="Render" loading="lazy">'
        else:
            render_html = '<span class="no-render">No render available</span>'

        html_parts.append(f'''<div class="card" data-street="{street_attr}" data-address="{addr_attr}">
<h3>{comp["address"]}</h3>
<div class="pair">
<div class="img-box"><img src="{photo_src}" alt="Photo" loading="lazy"><div class="label">Field Photo</div></div>
<div class="img-box">{render_html}<div class="label">Render</div></div>
</div>
</div>
''')

    html_parts.append("""</div>
<script>
function filterCards() {
  const street = document.getElementById('streetFilter').value.toLowerCase();
  const search = document.getElementById('searchBox').value.toLowerCase();
  document.querySelectorAll('.card').forEach(card => {
    const cs = card.dataset.street.toLowerCase();
    const ca = card.dataset.address.toLowerCase();
    const show = (!street || cs.includes(street)) && (!search || ca.includes(search));
    card.classList.toggle('hidden', !show);
  });
}
</script>
</body></html>""")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))

    print(f"Generated {OUTPUT_FILE} with {len(comparisons)} comparison cards")


if __name__ == "__main__":
    main()
