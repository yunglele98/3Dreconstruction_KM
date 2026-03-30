import os, re, math, xml.etree.ElementTree as ET

photo_dir = r'C:\Users\liam1\blender_buildings\PHOTOS KENSINGTON sorted\Chinatown Mural Lane'
photos = sorted([f for f in os.listdir(photo_dir) if f.startswith('IMG_') and f.endswith('.jpg')])

def parse_ts(fname):
    m = re.match(r'IMG_(\d{8})_(\d{2})(\d{2})(\d{2})(\d{3})', fname)
    date = m.group(1)
    h, mi, s, ms = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
    t = h * 3600 + mi * 60 + s + ms / 1000.0
    return date, t

# 12 GPS reference points from user's Google My Maps
refs_raw = [
    ('IMG_20260316_004213611_HDR', 43.6561599, -79.4000059),
    ('IMG_20260316_004220875_HDR', 43.6561599, -79.4000059),
    ('IMG_20260316_004548676_HDR', 43.6558761, -79.3999060),
    ('IMG_20260318_152321300_HDR', 43.6564064, -79.4000792),
    ('IMG_20260318_152330797_HDR', 43.6563118, -79.4000416),
    ('IMG_20260318_152340182_HDR', 43.6562953, -79.4000349),
    ('IMG_20260318_152437037_HDR', 43.6561517, -79.4001006),
    ('IMG_20260318_153219916_HDR', 43.6556823, -79.4020028),
    ('IMG_20260318_153226150_HDR', 43.6556823, -79.4020028),
    ('IMG_20260318_154416471_HDR', 43.6560969, -79.3999834),
    ('IMG_20260318_154447308_HDR', 43.6561780, -79.4000498),
    ('IMG_20260318_154608992_HDR', 43.6558275, -79.3998968),
]
ref_dict = {r[0]: (r[1], r[2]) for r in refs_raw}


def build_refs(session_photos):
    r = []
    for stem, t in session_photos:
        if stem in ref_dict:
            lat, lon = ref_dict[stem]
            r.append((t, lat, lon))
    r.sort()
    return r


def interpolate(t, refs):
    if not refs:
        return None, None
    if len(refs) == 1:
        return refs[0][1], refs[0][2]
    if t <= refs[0][0]:
        if refs[0][0] == refs[1][0]:
            return refs[0][1], refs[0][2]
        frac = (t - refs[0][0]) / (refs[1][0] - refs[0][0])
        frac = max(frac, -0.5)
        return refs[0][1] + frac * (refs[1][1] - refs[0][1]), refs[0][2] + frac * (refs[1][2] - refs[0][2])
    if t >= refs[-1][0]:
        if refs[-1][0] == refs[-2][0]:
            return refs[-1][1], refs[-1][2]
        frac = (t - refs[-2][0]) / (refs[-1][0] - refs[-2][0])
        frac = min(frac, 1.5)
        return refs[-2][1] + frac * (refs[-1][1] - refs[-2][1]), refs[-2][2] + frac * (refs[-1][2] - refs[-2][2])
    for i in range(len(refs) - 1):
        if refs[i][0] <= t <= refs[i + 1][0]:
            dt = refs[i + 1][0] - refs[i][0]
            if dt == 0:
                return refs[i][1], refs[i][2]
            frac = (t - refs[i][0]) / dt
            return refs[i][1] + frac * (refs[i + 1][1] - refs[i][1]), refs[i][2] + frac * (refs[i + 1][2] - refs[i][2])
    return refs[-1][1], refs[-1][2]


# Group photos into sessions
all_items = []
for p in photos:
    d, t = parse_ts(p)
    stem = p.replace('.jpg', '')
    all_items.append((stem, d, t, p))

# Find the 10-min gap in March 18 photos
mar18 = sorted([(s, d, t, p) for s, d, t, p in all_items if d == '20260318'], key=lambda x: x[2])
split_t = None
for i in range(1, len(mar18)):
    if mar18[i][2] - mar18[i - 1][2] > 300:
        split_t = (mar18[i - 1][2] + mar18[i][2]) / 2
        break

sessions = {}
for stem, d, t, p in all_items:
    if d == '20260316':
        sessions.setdefault('night', []).append((stem, t))
    elif split_t and t < split_t:
        sessions.setdefault('walk1', []).append((stem, t))
    else:
        sessions.setdefault('walk2', []).append((stem, t))

# Build refs per session
night_refs = build_refs(sessions.get('night', []))
walk1_refs = build_refs(sessions.get('walk1', []))
walk2_refs = build_refs(sessions.get('walk2', []))

# Walk1 has a big gap between mid-lane (15:24:37) and far-west (15:32:19).
# Add synthetic waypoints: south end of lane ~15:28, then heading west.
walk1_refs.append((55680.0, 43.6558, -79.3999))   # 15:28:00 south end of lane
walk1_refs.append((55740.0, 43.6557, -79.4005))   # 15:29:00 starting west
walk1_refs.sort()

# Interpolate all photos
results = []
session_refs = {'night': night_refs, 'walk1': walk1_refs, 'walk2': walk2_refs}
for sname, sphotos in sessions.items():
    refs = session_refs[sname]
    for stem, t in sorted(sphotos, key=lambda x: x[1]):
        is_ref = stem in ref_dict
        lat, lon = interpolate(t, refs)
        if lat is not None:
            results.append((stem, lat, lon, sname, is_ref))

# Generate KML
kml = ET.Element('kml', xmlns='http://www.opengis.net/kml/2.2')
doc = ET.SubElement(kml, 'Document')
ET.SubElement(doc, 'name').text = 'Chinatown Mural Lane - All Photos'

# Styles: red=reference, yellow=night, green=walk1, magenta=walk2
for color, sid, scale in [
    ('ff0000ff', 'ref', '1.2'),
    ('ff00aaff', 'night', '0.8'),
    ('ff00ff00', 'walk1', '0.8'),
    ('ffff00ff', 'walk2', '0.8'),
]:
    style = ET.SubElement(doc, 'Style', id=sid)
    icon_style = ET.SubElement(style, 'IconStyle')
    ET.SubElement(icon_style, 'color').text = color
    ET.SubElement(icon_style, 'scale').text = scale
    icon = ET.SubElement(icon_style, 'Icon')
    ET.SubElement(icon, 'href').text = 'http://maps.google.com/mapfiles/kml/paddle/wht-blank.png'

labels = {
    'night': '1. Night Mar16 (13 pics)',
    'walk1': '2. Day Walk1 Mar18 (67 pics)',
    'walk2': '3. Day Walk2 Mar18 (18 pics)',
}

for sname in ['night', 'walk1', 'walk2']:
    folder = ET.SubElement(doc, 'Folder')
    ET.SubElement(folder, 'name').text = labels[sname]

    session_results = [(s, la, lo, sn, ir) for s, la, lo, sn, ir in results if sn == sname]
    for i, (stem, lat, lon, sn, is_ref) in enumerate(session_results):
        pm = ET.SubElement(folder, 'Placemark')
        seq = f'{i + 1:02d}'
        parts = stem.split('_')
        time_str = parts[2][:2] + ':' + parts[2][2:4] + ':' + parts[2][4:6]
        prefix = 'REF ' if is_ref else ''
        ET.SubElement(pm, 'name').text = f'{prefix}{seq} {time_str}'
        ET.SubElement(pm, 'description').text = (
            f'{stem}.jpg\n'
            f'Session: {sname}\n'
            f'GPS: {"REFERENCE" if is_ref else "interpolated"}\n'
            f'{lat:.7f}, {lon:.7f}'
        )
        ET.SubElement(pm, 'styleUrl').text = f'#{"ref" if is_ref else sname}'
        pt = ET.SubElement(pm, 'Point')
        ET.SubElement(pt, 'coordinates').text = f'{lon:.7f},{lat:.7f},0'

    # Path line
    line_pm = ET.SubElement(folder, 'Placemark')
    ET.SubElement(line_pm, 'name').text = f'{sname} path'
    ls_style = ET.SubElement(line_pm, 'Style')
    ls_line = ET.SubElement(ls_style, 'LineStyle')
    path_colors = {'night': 'ff0000ff', 'walk1': 'ff00ff00', 'walk2': 'ffff00ff'}
    ET.SubElement(ls_line, 'color').text = path_colors[sname]
    ET.SubElement(ls_line, 'width').text = '3'
    linestring = ET.SubElement(line_pm, 'LineString')
    ET.SubElement(linestring, 'tessellate').text = '1'
    coords_str = ' '.join(f'{lon:.7f},{lat:.7f},0' for _, lat, lon, sn, _ in session_results)
    ET.SubElement(linestring, 'coordinates').text = coords_str

out_path = r'C:\Users\liam1\blender_buildings\PHOTOS KENSINGTON sorted\Chinatown Mural Lane\mural_lane_photos.kml'
tree = ET.ElementTree(kml)
ET.indent(tree, space='  ')
tree.write(out_path, encoding='utf-8', xml_declaration=True)

print(f'KML written: {out_path}')
print(f'Total placemarks: {len(results)}')
for sname in ['night', 'walk1', 'walk2']:
    cnt = sum(1 for r in results if r[3] == sname)
    ref_cnt = sum(1 for r in results if r[3] == sname and r[4])
    print(f'  {sname}: {cnt} points ({ref_cnt} GPS refs, {cnt - ref_cnt} interpolated)')