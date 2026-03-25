import csv, re, os

import sys
index_file = sys.argv[1] if len(sys.argv) > 1 else 'C:/PHOTOS KENSINGTON/csv/photo_address_index_merged.csv'
with open(index_file, encoding='utf-8') as f:
    reader = csv.reader(f)
    header = next(reader)
    all_rows = list(reader)

groups = {}
for r in all_rows:
    if r[2] != 'inferred-cascade':
        continue
    label = r[1]
    if label not in groups:
        groups[label] = []
    groups[label].append(r[0])

for label in groups:
    groups[label].sort()

sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))

parts = []
parts.append('''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Kensington Photo Review Tool</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #1a1a2e; color: #eee; }
.header { background: #16213e; padding: 16px 24px; position: sticky; top: 0; z-index: 100; border-bottom: 2px solid #0f3460; }
.header h1 { font-size: 20px; margin-bottom: 4px; }
.stats { font-size: 13px; color: #a0a0c0; }
.controls { display: flex; gap: 12px; margin-top: 8px; align-items: center; flex-wrap: wrap; }
.controls button { padding: 6px 14px; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.btn-export { background: #e94560; color: white; }
.btn-collapse { background: #0f3460; color: white; }
.filter-input { padding: 6px 12px; border: 1px solid #333; border-radius: 4px; background: #0d1b2a; color: #eee; width: 250px; font-size: 13px; }
.group { margin: 16px; border: 1px solid #333; border-radius: 8px; overflow: hidden; }
.group-header { background: #16213e; padding: 12px 16px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
.group-header:hover { background: #1a2a4e; }
.group-header h2 { font-size: 15px; font-weight: 500; }
.count { background: #0f3460; padding: 2px 10px; border-radius: 12px; font-size: 12px; }
.group-body { display: none; padding: 8px; }
.group.open .group-body { display: flex; flex-wrap: wrap; gap: 8px; }
.photo-card { width: 280px; border: 2px solid #333; border-radius: 6px; overflow: hidden; background: #0d1b2a; }
.photo-card.reviewed { border-color: #2ecc71; }
.photo-card.flagged { border-color: #e94560; }
.photo-card img { width: 100%; height: 200px; object-fit: cover; cursor: pointer; }
.info { padding: 8px; font-size: 11px; }
.filename { color: #a0a0c0; word-break: break-all; }
.label-row { display: flex; gap: 4px; margin-top: 6px; }
.label-row input { flex: 1; padding: 4px 6px; border: 1px solid #444; border-radius: 3px; background: #1a1a2e; color: #eee; font-size: 11px; }
.btn-row { display: flex; gap: 4px; margin-top: 4px; }
.btn-ok { padding: 3px 8px; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; background: #2ecc71; color: white; }
.btn-flag { padding: 3px 8px; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; background: #e94560; color: white; }
.btn-apply { padding: 3px 8px; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; background: #3498db; color: white; }
.lightbox { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.95); z-index: 200; justify-content: center; align-items: center; cursor: pointer; }
.lightbox.show { display: flex; }
.lightbox img { max-width: 95%; max-height: 95%; object-fit: contain; }
.progress { height: 3px; background: #333; margin-top: 8px; border-radius: 2px; overflow: hidden; }
.progress-bar { height: 100%; background: #2ecc71; transition: width 0.3s; }
</style>
</head>
<body>
<div class="header">
  <h1>Kensington Photo Review Tool (remaining 24)</h1>
  <div class="stats">
    TOTAL_PLACEHOLDER photos in GROUP_COUNT_PLACEHOLDER groups |
    Reviewed: <span id="rc">0</span> |
    Flagged: <span id="fc">0</span>
  </div>
  <div class="progress"><div class="progress-bar" id="pb" style="width:0%"></div></div>
  <div class="controls">
    <input class="filter-input" id="filter" placeholder="Filter groups by label..." oninput="filt()">
    <button class="btn-collapse" onclick="document.querySelectorAll('.group').forEach(g=>g.classList.remove('open'))">Collapse All</button>
    <button class="btn-collapse" onclick="document.querySelectorAll('.group').forEach(g=>g.classList.add('open'))">Expand All</button>
    <button class="btn-export" onclick="exp()">Export Corrections CSV</button>
  </div>
</div>
<div id="groups">
''')

total_photos = sum(len(v) for v in groups.values())
parts[0] = parts[0].replace('TOTAL_PLACEHOLDER', str(total_photos))
parts[0] = parts[0].replace('GROUP_COUNT_PLACEHOLDER', str(len(groups)))

for label, files in sorted_groups:
    safe = label.replace('&','&amp;').replace('"','&quot;').replace("'","&#39;").replace('<','&lt;').replace('>','&gt;')
    gid = re.sub(r'[^a-zA-Z0-9]', '_', label)[:40]
    parts.append(f'<div class="group open" id="g_{gid}" data-label="{safe}">\n')
    parts.append(f'  <div class="group-header" onclick="this.parentElement.classList.toggle(\'open\')">\n')
    parts.append(f'    <h2>{safe}</h2><span class="count">{len(files)}</span>\n')
    parts.append(f'  </div><div class="group-body">\n')
    for fn in files:
        sfn = fn.replace('"','&quot;')
        m = re.search(r'(\d{8})_(\d{2})(\d{2})(\d{2})', fn)
        ts = f"{m.group(2)}:{m.group(3)}:{m.group(4)}" if m else ""
        parts.append(f'    <div class="photo-card" data-fn="{sfn}">')
        parts.append(f'      <img src="../{sfn}" loading="lazy" onclick="lb(this.src)" onerror="this.alt=\'Not found\';this.style.background=\'#333\'">')
        parts.append(f'      <div class="info"><div class="filename">{sfn}<br><small>{ts}</small></div>')
        parts.append(f'        <div class="label-row"><input type="text" value="{safe}" class="nl"></div>')
        parts.append(f'        <div class="btn-row"><button class="btn-ok" onclick="ok(this)">OK</button>')
        parts.append(f'        <button class="btn-flag" onclick="fl(this)">Flag</button>')
        parts.append(f'        <button class="btn-apply" onclick="ap(this)">Apply to group</button></div>')
        parts.append(f'      </div></div>\n')
    parts.append('  </div></div>\n')

parts.append('''</div>
<div class="lightbox" id="lbx" onclick="this.classList.remove('show')"><img id="lbi"></div>
<script>
const T=document.querySelectorAll('.photo-card').length;
function upd(){
  const r=document.querySelectorAll('.photo-card.reviewed').length;
  const f=document.querySelectorAll('.photo-card.flagged').length;
  document.getElementById('rc').textContent=r;
  document.getElementById('fc').textContent=f;
  document.getElementById('pb').style.width=((r+f)/T*100)+'%';
}
function ok(b){const c=b.closest('.photo-card');c.classList.remove('flagged');c.classList.add('reviewed');upd();}
function fl(b){const c=b.closest('.photo-card');c.classList.remove('reviewed');c.classList.add('flagged');upd();}
function ap(b){
  const card=b.closest('.photo-card');
  const val=card.querySelector('.nl').value;
  const group=card.closest('.group-body');
  group.querySelectorAll('.nl').forEach(inp=>{inp.value=val;});
}
function lb(s){document.getElementById('lbi').src=s;document.getElementById('lbx').classList.add('show');}
function filt(){
  const q=document.getElementById('filter').value.toLowerCase();
  document.querySelectorAll('.group').forEach(g=>{
    g.style.display=g.dataset.label.toLowerCase().includes(q)?'':'none';
  });
}
function exp(){
  let csv='filename,new_address,status\\n';
  document.querySelectorAll('.photo-card').forEach(c=>{
    let st='unchanged';
    if(c.classList.contains('reviewed'))st='reviewed';
    if(c.classList.contains('flagged'))st='flagged';
    if(st!=='unchanged'){
      const fn=c.dataset.fn;
      const lb=c.querySelector('.nl').value.replace(/"/g,'""');
      csv+='"'+fn+'","'+lb+'","'+st+'"\\n';
    }
  });
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
  a.download='photo_review_corrections.csv';
  a.click();
}
</script>
</body></html>''')

with open('C:/PHOTOS KENSINGTON/csv/review_tool.html', 'w', encoding='utf-8') as f:
    f.write(''.join(parts))

print(f"Created review_tool.html")
print(f"  {len(sorted_groups)} groups, {total_photos} photos")
