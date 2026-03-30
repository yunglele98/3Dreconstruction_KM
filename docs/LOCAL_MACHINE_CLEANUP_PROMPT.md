# Claude Code — Full System Organization

Reorganizes the entire machine around `D:\liam1_transfer` as the primary workspace.

## Safety Rules

- NEVER delete >1GB without asking first
- NEVER delete .blend, .json (params), or .py files without confirmation
- Always verify destination exists before moving

## Target Structure

```
D:\liam1_transfer\
├── blender_buildings\          ← Kensington Market 3D (canonical, already here)
├── projects\
│   ├── urbanisme\              ← University urbanisme coursework
│   └── cartographie\           ← Cartography / GIS coursework
├── tools\
│   ├── COLMAP\
│   ├── OpenMVS\
│   ├── RealESRGAN\
│   ├── MaterialMaker\
│   └── Blender_addons\
├── data\
│   ├── MASTERLIST\             ← DATA bundle (currently C:\Users\liam1\DOWNLOADS\MASTERLIST\DATA)
│   ├── gis_exports\
│   └── reference_photos\
├── archives\
└── backups\
```

## Phase 1: Discovery

```powershell
$drives = (Get-PSDrive -PSProvider FileSystem).Root
foreach ($d in $drives) {
    Get-ChildItem -Path $d -Directory -Filter "blender_buildings" -Recurse -Depth 5 -EA 0 |
        Select FullName, LastWriteTime, @{N='SizeMB';E={[math]::Round((Get-ChildItem $_.FullName -Recurse -File -EA 0 | Measure Length -Sum).Sum/1MB)}}
}
Get-ChildItem C:\ -Directory -Filter "MASTERLIST" -Recurse -Depth 5 -EA 0 | Select FullName
foreach ($d in $drives) {
    Get-ChildItem $d -Directory -Recurse -Depth 4 -EA 0 | Where-Object { $_.Name -match "urbanis|cartograph|SIG|QGIS|enquete|paysag" } | Select FullName
}
Get-ChildItem "C:\Users\liam1\Downloads","C:\Users\liam1\Desktop" -Recurse -File -EA 0 |
    Where-Object { $_.Length -gt 500MB } | Select FullName, @{N='SizeMB';E={[math]::Round($_.Length/1MB)}}
Get-PSDrive -PSProvider FileSystem | Select Name, @{N='UsedGB';E={[math]::Round($_.Used/1GB,1)}}, @{N='FreeGB';E={[math]::Round($_.Free/1GB,1)}}
```

## Phase 2: Create structure

```powershell
$base = "D:\liam1_transfer"
@("projects\urbanisme","projects\cartographie","tools\COLMAP","tools\OpenMVS","tools\RealESRGAN","tools\MaterialMaker","tools\Blender_addons","data\MASTERLIST","data\gis_exports","data\reference_photos","archives","backups") | ForEach-Object {
    New-Item -ItemType Directory -Force -Path "$base\$_"
}
```

## Phase 3: Consolidate

Move MASTERLIST/DATA, tools, coursework, dedup blender_buildings copies. Rescue unique files before deleting old copies.

## Phase 4: Update paths_config.py

```python
DATA_BUNDLE = Path(r"D:\liam1_transfer\data\MASTERLIST\DATA")
```

Update TOOLS dict paths and PowerShell scripts.

## Phase 5: Clean C: drive

Remove old copies and installers (with confirmation). Report space recovered.

## Phase 6: Verify

```powershell
cd D:\liam1_transfer\blender_buildings
python -c "from scripts.paths_config import *; print('DATA_BUNDLE:', DATA_BUNDLE); print('Exists:', DATA_BUNDLE.exists())"
python -m pytest tests/ -q
```

## Phase 7: Run project reorg

```
claude "Follow PROJECT_REORG_PROMPT.md"
```
