"""Render a turntable animation of the demo scene.

Creates a 360-degree orbit around the scene center, rendering each frame.
Output: PNG sequence or MP4 video.

Run: blender --background <scene.blend> --python scripts/render_turntable.py
"""

import bpy
import math
import os
from pathlib import Path

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
OUT_DIR = SCRIPT_DIR / "outputs" / "demos" / "turntable"
OUT_DIR.mkdir(exist_ok=True)

# Settings
FRAMES = 120  # 120 frames = 4 seconds at 30fps
RADIUS = 120  # distance from center
HEIGHT = 60   # camera height
RESOLUTION_X = 1920
RESOLUTION_Y = 1080
USE_CYCLES = False  # True for quality, False for speed


def find_scene_center():
    """Find center of all building objects."""
    xs, ys = [], []
    for obj in bpy.data.objects:
        if obj.name.startswith("Bldg_") and obj.type == "MESH":
            xs.append(obj.location.x)
            ys.append(obj.location.y)
    if xs:
        return sum(xs) / len(xs), sum(ys) / len(ys)
    return 0, 0


def setup_camera():
    """Create or get the turntable camera."""
    cam = bpy.data.objects.get("TurntableCam")
    if cam is None:
        bpy.ops.object.camera_add()
        cam = bpy.context.active_object
        cam.name = "TurntableCam"
    bpy.context.scene.camera = cam
    return cam


def setup_lighting():
    """Ensure good lighting for turntable."""
    # Sun
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

    # Fill light
    fill = bpy.data.objects.get("TurntableFill")
    if not fill:
        bpy.ops.object.light_add(type='AREA', location=(-60, 60, 50))
        fill = bpy.context.active_object
        fill.name = "TurntableFill"
        fill.data.energy = 300
        fill.data.size = 20

    # World background
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.6, 0.7, 0.85, 1.0)
        bg.inputs["Strength"].default_value = 0.5


def render_turntable():
    """Render the turntable animation."""
    cx, cy = find_scene_center()
    print(f"Scene center: ({cx:.0f}, {cy:.0f})")

    cam = setup_camera()
    setup_lighting()

    scene = bpy.context.scene
    scene.render.resolution_x = RESOLUTION_X
    scene.render.resolution_y = RESOLUTION_Y
    scene.render.film_transparent = False

    if USE_CYCLES:
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = 64
        scene.cycles.use_denoising = True
    else:
        scene.render.engine = 'BLENDER_EEVEE'

    scene.frame_start = 1
    scene.frame_end = FRAMES

    print(f"Rendering {FRAMES} frames ({FRAMES / 30:.1f}s at 30fps)")
    print(f"Output: {OUT_DIR}")
    print(f"Engine: {'Cycles' if USE_CYCLES else 'EEVEE'}")

    for frame in range(1, FRAMES + 1):
        scene.frame_set(frame)

        # Calculate camera position on orbit
        angle = (frame - 1) / FRAMES * 2 * math.pi
        cam_x = cx + math.cos(angle) * RADIUS
        cam_y = cy + math.sin(angle) * RADIUS
        cam_z = HEIGHT

        cam.location = (cam_x, cam_y, cam_z)

        # Point camera at scene center (slightly above ground)
        look_at = (cx, cy, 5)
        direction = (look_at[0] - cam_x, look_at[1] - cam_y, look_at[2] - cam_z)
        rot_z = math.atan2(direction[1], direction[0]) + math.pi / 2
        dist_xy = math.sqrt(direction[0]**2 + direction[1]**2)
        rot_x = math.atan2(dist_xy, -direction[2])
        cam.rotation_euler = (rot_x, 0, rot_z)

        # Render frame
        scene.render.filepath = str(OUT_DIR / f"frame_{frame:04d}")
        bpy.ops.render.render(write_still=True)

        if frame % 10 == 0 or frame == 1:
            print(f"  Frame {frame}/{FRAMES}")

    print(f"\nDone. {FRAMES} frames saved to {OUT_DIR}")
    print(f"\nTo create MP4 (requires ffmpeg):")
    print(f'  ffmpeg -framerate 30 -i "{OUT_DIR}/frame_%04d.png" -c:v libx264 -pix_fmt yuv420p "{OUT_DIR}/turntable.mp4"')


render_turntable()
