"""Render multiple views of the demo scene headlessly.

Produces: top-down, perspective, street-level, and detail views.
Uses Cycles for quality renders, EEVEE for quick previews.

Run: blender --background <scene.blend> --python scripts/render_demo.py
"""

import bpy
import math
import os
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "demos" / "renders"
OUT_DIR.mkdir(exist_ok=True)

# Scene setup
scene = bpy.context.scene
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.film_transparent = False

# Use EEVEE for fast renders first
scene.render.engine = 'BLENDER_EEVEE'

# Ensure sun exists
sun = None
for obj in bpy.data.objects:
    if obj.type == 'LIGHT' and obj.data.type == 'SUN':
        sun = obj
        break
if not sun:
    bpy.ops.object.light_add(type='SUN', location=(50, -50, 100))
    sun = bpy.context.active_object
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(25))


def set_camera(location, rotation_euler, name="RenderCam"):
    """Set or create camera at given position."""
    cam = bpy.data.objects.get(name)
    if cam is None:
        bpy.ops.object.camera_add(location=location)
        cam = bpy.context.active_object
        cam.name = name
    else:
        cam.location = location
    cam.rotation_euler = rotation_euler
    scene.camera = cam
    return cam


def render(filename, engine=None):
    """Render current view to file."""
    if engine:
        scene.render.engine = engine
    filepath = str(OUT_DIR / filename)
    scene.render.filepath = filepath
    bpy.ops.render.render(write_still=True)
    size = os.path.getsize(filepath + ".png") if os.path.exists(filepath + ".png") else 0
    print(f"  Rendered: {filename}.png ({size//1024}KB)")


# Find scene center from building objects
bldg_xs, bldg_ys = [], []
for obj in bpy.data.objects:
    if obj.name.startswith("Bldg_") and obj.type == "MESH":
        bldg_xs.append(obj.location.x)
        bldg_ys.append(obj.location.y)

if bldg_xs:
    cx = sum(bldg_xs) / len(bldg_xs)
    cy = sum(bldg_ys) / len(bldg_ys)
else:
    cx, cy = -74, -91

# Override: compute center from actual building objects in the scene
# The scene is rotated -17.5 degrees, so hardcoded values don't work.
# Let the auto-detection from bldg_xs/bldg_ys handle it.
if not bldg_xs:
    cx, cy = 0, 0  # fallback if no buildings found

# Add fill light to illuminate shadow sides
bpy.ops.object.light_add(type='AREA', location=(cx - 80, cy + 80, 60))
fill = bpy.context.active_object
fill.name = "FillLight"
fill.data.energy = 500
fill.data.size = 30
fill.rotation_euler = (math.radians(60), 0, math.radians(-135))

# Set world background to light blue sky
world = bpy.context.scene.world
if world is None:
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg:
    bg.inputs["Color"].default_value = (0.6, 0.7, 0.85, 1.0)
    bg.inputs["Strength"].default_value = 0.5

print(f"Scene center: ({cx:.0f}, {cy:.0f}), {len(bldg_xs)} buildings")
print(f"Output: {OUT_DIR}")
print()

# ── View 1: Bird's eye (wide overview) ──
print("View 1: Bird's eye overview")
set_camera(
    location=(cx, cy, 250),
    rotation_euler=(math.radians(10), 0, math.radians(17))
)
render("01_birds_eye")

# ── View 2: Top-down (plan view) ──
print("View 2: Top-down plan")
set_camera(
    location=(cx, cy, 300),
    rotation_euler=(0, 0, math.radians(17))
)
render("02_top_down")

# ── View 3: SE perspective (wide, all buildings) ──
print("View 3: SE perspective wide")
set_camera(
    location=(cx + 120, cy - 150, 100),
    rotation_euler=(math.radians(55), 0, math.radians(30))
)
render("03_se_perspective")

# ── View 4: NW perspective ──
print("View 4: NW perspective")
set_camera(
    location=(cx - 120, cy + 120, 80),
    rotation_euler=(math.radians(55), 0, math.radians(-150))
)
render("04_nw_perspective")

# ── View 5: Street level (west side row, looking NW along Bellevue) ──
print("View 5: Street level west row")
set_camera(
    location=(cx - 30, cy - 60, 4),
    rotation_euler=(math.radians(88), 0, math.radians(17))
)
render("05_street_west")

# ── View 6: Street level (east side, looking SE) ──
print("View 6: Street level east row")
set_camera(
    location=(cx + 20, cy + 30, 4),
    rotation_euler=(math.radians(88), 0, math.radians(-163))
)
render("06_street_east")

# ── View 7: Close-up pair of houses ──
print("View 7: Close-up houses")
set_camera(
    location=(cx - 15, cy - 30, 10),
    rotation_euler=(math.radians(70), 0, math.radians(17))
)
render("07_closeup")

# ── View 8: Park view (looking toward buildings from park area) ──
print("View 8: Park view")
set_camera(
    location=(cx + 50, cy - 100, 8),
    rotation_euler=(math.radians(82), 0, math.radians(-30))
)
render("08_park_view")

# ── View 9: Cycles render (best quality) ──
print("View 9: Cycles render")
set_camera(
    location=(cx + 100, cy - 120, 80),
    rotation_euler=(math.radians(55), 0, math.radians(25))
)
scene.render.engine = 'CYCLES'
scene.cycles.samples = 128
scene.cycles.use_denoising = True
render("09_cycles", engine='CYCLES')

print(f"\nDone. {len(list(OUT_DIR.glob('*.png')))} renders saved to {OUT_DIR}")
