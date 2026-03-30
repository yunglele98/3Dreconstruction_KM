import json
from pathlib import Path
path=Path('params/401_College_St_custom_v23.json')
data=json.loads(path.read_text(encoding='utf-8'))
meta=data['_meta']
meta.setdefault('custom_passes',[]).append({'pass':'pass_23_windows_doors','timestamp':'2026-03-26','author':'codex','summary':'Adds horizontal mullions and door frame proxies for the primary front windows/doors.'})
meta['custom_workflow_note']='Pass 23 keeps geometry locked while adding mullion lines and door frame blades.'
fd=data['facade_detail']
fd['opening_rhythm']='Pass-23 adds horizontal mullions and door frame depth proxies on the primary frontage openings.'
fd['composition']='Pass 23 door/window riff for Kensington Community Early Learning Centre at 401 College St. Adds mullion-led window bands and door frame blades while keeping massing fixed.'
fd['heritage_summary']='Pass 23 enriches facade musicality with mullion and door frame proxies.'
vols=data['volumes']
for idx in (0,3,7):
    vol=vols[idx]
    for row in vol['window_rows']:
        row['add_horizontal_mullion']=True
        row['frame_colour']='#183558'
    for door in vol.get('doors_detail',[]):
        door['frame_depth_m']=0.05
        door['frame_colour_hex']='#183558'
path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
