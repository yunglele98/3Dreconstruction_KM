"""
Fix 20 buildings flagged with height_mismatch in QA report.
These have total_height_m significantly exceeding city_data.height_avg_m.

Strategy:
- If city_data.height_avg_m exists and is < 5m, the building is likely 1-storey
- Recalculate total_height_m and floor_heights_m from city LiDAR data
- Preserve floor count only if consistent with the corrected height
- Never touch lot dimensions, site data, or HCD data
"""
import json, os
from pathlib import Path

PARAMS_DIR = Path(r'C:\Users\liam1\blender_buildings\params')

# The 20 flagged buildings and their city_data heights
FLAGGED = {
    "189_Baldwin_St": 3.44,
    "254_Augusta_Ave": 4.10,
    "27_Bellevue_Ave": 3.74,
    "299_Augusta_Ave": 4.53,
    "301_Augusta_Ave": 4.53,
    "305_Augusta_Ave": 3.21,
    "307_Augusta_Ave": 3.21,
    "323_College_St": 3.53,
    "333_College_St": 3.53,
    "335_College_St": 3.53,
    "337_College_St": 4.22,
    "374_Spadina_Ave": 3.88,
    "3_Nassau_St": 3.38,
    "400_Spadina_Ave": 4.43,
    "402_Spadina_Ave": 4.43,
    "404_Spadina_Ave": 4.43,
    "406_Spadina_Ave": 4.43,
    "408_Spadina_Ave": 4.43,
    "39_Kensington_Ave": 3.91,  # Actually 43 Kensington Ave
    "53_Kensington_Ave": 3.15,
}

MIN_FLOOR_HEIGHT = 2.4  # metres - absolute minimum
DEFAULT_1F_HEIGHT = 3.2  # single storey commercial/residential

fixed = 0
for stem, lidar_avg in FLAGGED.items():
    path = PARAMS_DIR / f"{stem}.json"
    if not path.exists():
        # Try alternate naming
        alt = stem.replace("_", " ")
        candidates = list(PARAMS_DIR.glob(f"*{stem.split('_')[0]}*{stem.split('_')[-2]}*"))
        if candidates:
            path = candidates[0]
        else:
            print(f"  SKIP: {stem} - file not found")
            continue
    
    data = json.load(open(path, encoding='utf-8'))
    old_height = data.get('total_height_m', 0)
    old_floors = data.get('floors', 1)
    
    # Use city_data height if available, or the FLAGGED value
    city_height = lidar_avg
    cd = data.get('city_data', {})
    if cd.get('height_avg_m'):
        try:
            city_height = float(cd['height_avg_m'])
        except (TypeError, ValueError):
            pass
    
    # Determine correct floor count from LiDAR height
    if city_height < 4.5:
        new_floors = 1
    elif city_height < 7.5:
        new_floors = 2
    elif city_height < 10.5:
        new_floors = 3
    else:
        new_floors = max(1, round(city_height / 3.2))
    
    # Build new floor heights from city data
    # Use realistic height distribution: ground floor slightly taller
    if new_floors == 1:
        new_floor_heights = [round(city_height, 2)]
        new_total = city_height
    elif new_floors == 2:
        ground = round(city_height * 0.55, 2)
        upper = round(city_height - ground, 2)
        new_floor_heights = [ground, upper]
        new_total = city_height
    else:
        ground = round(city_height * 0.4, 2)
        remaining = city_height - ground
        upper = round(remaining / (new_floors - 1), 2)
        new_floor_heights = [ground] + [upper] * (new_floors - 1)
        new_total = round(sum(new_floor_heights), 2)
    
    # Ensure floor heights are sensible (not below 2.4m)
    if any(h < MIN_FLOOR_HEIGHT for h in new_floor_heights):
        # Fall back to equal distribution
        per_floor = round(city_height / new_floors, 2)
        if per_floor < MIN_FLOOR_HEIGHT and new_floors > 1:
            new_floors = max(1, int(city_height / MIN_FLOOR_HEIGHT))
            per_floor = round(city_height / new_floors, 2)
        new_floor_heights = [per_floor] * new_floors
        new_total = round(sum(new_floor_heights), 2)
    
    # Apply changes
    data['total_height_m'] = round(new_total, 2)
    data['floors'] = new_floors
    data['floor_heights_m'] = new_floor_heights
    
    # Adjust windows_per_floor if needed
    wpf = data.get('windows_per_floor', [])
    if len(wpf) > new_floors:
        data['windows_per_floor'] = wpf[:new_floors]
    elif len(wpf) < new_floors:
        default_w = wpf[0] if wpf else 3
        data['windows_per_floor'] = wpf + [default_w] * (new_floors - len(wpf))
    
    # Update meta
    meta = data.setdefault('_meta', {})
    fixes = meta.get('height_fixes', [])
    fixes.append(f"qa_height_mismatch: {old_height}m/{old_floors}F -> {new_total}m/{new_floors}F (LiDAR avg: {city_height}m)")
    meta['height_fixes'] = fixes
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"  FIXED: {stem}: {old_height}m/{old_floors}F -> {new_total}m/{new_floors}F (LiDAR: {city_height}m)")
    fixed += 1

print(f"\n{fixed} buildings corrected")
