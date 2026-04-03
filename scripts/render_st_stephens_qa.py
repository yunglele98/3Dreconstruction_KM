import bpy
from mathutils import Vector
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs"
COLLECTION_NAME = "building_103_Bellevue_Ave"


def look_at(cam, target):
    direction = Vector(target) - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


def scene_bounds(objs):
    xs, ys, zs = [], [], []
    for obj in objs:
        if obj.type != 'MESH':
            continue
        for c in obj.bound_box:
            w = obj.matrix_world @ Vector(c)
            xs.append(w.x)
            ys.append(w.y)
            zs.append(w.z)
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


col = bpy.data.collections.get(COLLECTION_NAME)
if not col:
    raise RuntimeError(f"Collection not found: {COLLECTION_NAME}")

mesh_objs = [o for o in col.objects if o.type == 'MESH' and "adjacent" not in o.name.lower()]
if not mesh_objs:
    raise RuntimeError("No mesh objects in collection")

min_x, max_x, min_y, max_y, min_z, max_z = scene_bounds(mesh_objs)
center_x = (min_x + max_x) * 0.5
center_y = (min_y + max_y) * 0.5
span_x = max_x - min_x
span_y = max_y - min_y
span = max(span_x, span_y)
cam_z = min_z + (max_z - min_z) * 0.38
center = Vector((center_x, center_y, cam_z))

scene = bpy.context.scene
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080

# Remove existing cameras to avoid ambiguity
for obj in list(bpy.data.objects):
    if obj.type == 'CAMERA':
        bpy.data.objects.remove(obj, do_unlink=True)

# Infer front vector from porch relative to nave (fallback +Y)
nave = bpy.data.objects.get("custom_nave_103_Bellevue_Ave")
porch = bpy.data.objects.get("custom_front_porch_103_Bellevue_Ave")
chapel = bpy.data.objects.get("custom_chapel_strip_103_Bellevue_Ave")
if nave and porch:
    front_vec = (porch.location - nave.location)
    front_vec.z = 0.0
    if front_vec.length > 0.001:
        front_vec.normalize()
    else:
        front_vec = Vector((0.0, 1.0, 0.0))
else:
    front_vec = Vector((0.0, 1.0, 0.0))

if nave and chapel:
    side_vec = (chapel.location - nave.location)
    side_vec.z = 0.0
    if side_vec.length > 0.001:
        side_vec.normalize()
    else:
        side_vec = Vector((-front_vec.y, front_vec.x, 0.0))
else:
    side_vec = Vector((-front_vec.y, front_vec.x, 0.0))

# Front view (camera placed opposite front target direction)
front_dist = max(span * 1.45, 36)
front_cam_loc = center + front_vec * front_dist
bpy.ops.object.camera_add(location=(front_cam_loc.x, front_cam_loc.y, cam_z))
cam_front = bpy.context.active_object
cam_front.name = "QA_Front_Cam"
front_target = center - front_vec * (span * 0.10)
look_at(cam_front, (front_target.x, front_target.y, cam_z + 0.2))
cam_front.data.lens = 42
scene.camera = cam_front
scene.render.filepath = str((OUT_DIR / "103_Bellevue_Ave_custom_v3_QA_true_front.png").resolve())
bpy.ops.render.render(write_still=True)

# Side view (chapel side)
side_dist = max(span * 1.35, 34)
side_cam_loc = center + side_vec * side_dist
bpy.ops.object.camera_add(location=(side_cam_loc.x, side_cam_loc.y, cam_z))
cam_side = bpy.context.active_object
cam_side.name = "QA_Side_Cam"
side_target = center - side_vec * (span * 0.10)
look_at(cam_side, (side_target.x, side_target.y, cam_z + 0.2))
cam_side.data.lens = 42
scene.camera = cam_side
scene.render.filepath = str((OUT_DIR / "103_Bellevue_Ave_custom_v3_QA_true_side.png").resolve())
bpy.ops.render.render(write_still=True)

# Additional facade-matched close QA views
if nave and porch:
    front_anchor = porch.location.copy()
else:
    front_anchor = center

fg_dist = max(span * 0.95, 24)
fg_cam_loc = front_anchor + front_vec * fg_dist
bpy.ops.object.camera_add(location=(fg_cam_loc.x, fg_cam_loc.y, cam_z + 1.2))
cam_fg = bpy.context.active_object
cam_fg.name = "QA_Front_Gable_Cam"
look_at(cam_fg, (front_anchor.x, front_anchor.y - 0.4, cam_z + 1.4))
cam_fg.data.lens = 55
scene.camera = cam_fg
scene.render.filepath = str((OUT_DIR / "103_Bellevue_Ave_custom_v3_QA_front_gable.png").resolve())
bpy.ops.render.render(write_still=True)

if chapel:
    side_anchor = chapel.location.copy()
else:
    side_anchor = center

cs_dist = max(span * 0.9, 22)
cs_cam_loc = side_anchor + side_vec * cs_dist
bpy.ops.object.camera_add(location=(cs_cam_loc.x, cs_cam_loc.y, cam_z + 1.0))
cam_cs = bpy.context.active_object
cam_cs.name = "QA_Chapel_Side_Cam"
look_at(cam_cs, (side_anchor.x, side_anchor.y, cam_z + 1.1))
cam_cs.data.lens = 52
scene.camera = cam_cs
scene.render.filepath = str((OUT_DIR / "103_Bellevue_Ave_custom_v3_QA_chapel_side.png").resolve())
bpy.ops.render.render(write_still=True)

# Fixed reference views tied to known custom objects
door = bpy.data.objects.get("custom_front_door_103_Bellevue_Ave")
tower = bpy.data.objects.get("custom_tower_103_Bellevue_Ave")
chapel_strip = bpy.data.objects.get("custom_chapel_strip_103_Bellevue_Ave")

if door and nave and tower:
    # Front elevation style: centered on nave/door, tower visible to side
    fx = nave.location.x - 1.5
    fy = door.location.y + 29.0
    fz = door.location.z + 5.2
    bpy.ops.object.camera_add(location=(fx, fy, fz))
    cam_front_fixed = bpy.context.active_object
    cam_front_fixed.name = "QA_Front_Fixed_Cam"
    look_at(cam_front_fixed, (door.location.x, door.location.y, door.location.z + 3.6))
    cam_front_fixed.data.lens = 47
    scene.camera = cam_front_fixed
    scene.render.filepath = str((OUT_DIR / "103_Bellevue_Ave_custom_v3_QA_front_fixed.png").resolve())
    bpy.ops.render.render(write_still=True)

if chapel_strip and nave:
    # Side elevation style: broad chapel rhythm along facade
    sx = chapel_strip.location.x + 28.0
    sy = chapel_strip.location.y + 1.0
    sz = nave.location.z + 4.8
    bpy.ops.object.camera_add(location=(sx, sy, sz))
    cam_side_fixed = bpy.context.active_object
    cam_side_fixed.name = "QA_Side_Fixed_Cam"
    look_at(cam_side_fixed, (chapel_strip.location.x - 0.6, chapel_strip.location.y, nave.location.z + 3.5))
    cam_side_fixed.data.lens = 44
    scene.camera = cam_side_fixed
    scene.render.filepath = str((OUT_DIR / "103_Bellevue_Ave_custom_v3_QA_side_fixed.png").resolve())
    bpy.ops.render.render(write_still=True)

print("Rendered QA views:")
print(scene.render.filepath)