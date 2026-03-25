#!/usr/bin/env python3
"""
Add Bellevue Square Park to a Blender scene.
Run inside Blender: blender --python scripts/create_park.py

Park features from field photos (March 2026):
- Rectangular ~70x50m grass area
- ~15 mature deciduous trees (bare)
- Children's playground (NE corner)
- Stepped concrete seating (W side)
- Boulders, benches, lamp posts, pathways
- Fire hydrants at corners
"""

import bpy
import bmesh
import math
import random
from mathutils import Vector

# Park center in local coords (between Bellevue 30-40 buildings)
# From site_coordinates: Bellevue 30 is at (-92, -119), 40 is at (-100, -90)
# Park is east of the west-side houses, between the two sides of Bellevue Ave
PARK_CENTER_X = -75.0
PARK_CENTER_Y = -80.0
PARK_W = 70.0  # east-west
PARK_D = 50.0  # north-south


def hex_to_rgb(hex_str):
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def get_or_create_material(name, color_hex, roughness=0.8):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    r, g, b = hex_to_rgb(color_hex)
    bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def create_ground():
    """Grass ground plane."""
    bpy.ops.mesh.primitive_plane_add(size=1, location=(PARK_CENTER_X, PARK_CENTER_Y, 0))
    ground = bpy.context.active_object
    ground.name = "Park_Ground"
    ground.scale = (PARK_W / 2, PARK_D / 2, 1)
    mat = get_or_create_material("Park_Grass", "#5A7A3A", 0.9)
    ground.data.materials.append(mat)
    return ground


def create_pathway(start, end, width=1.8):
    """Concrete pathway between two points."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.sqrt(dx*dx + dy*dy)
    angle = math.atan2(dy, dx)
    cx = (start[0] + end[0]) / 2
    cy = (start[1] + end[1]) / 2

    bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, 0.02))
    path = bpy.context.active_object
    path.name = f"Path_{start[0]:.0f}_{start[1]:.0f}"
    path.scale = (length / 2, width / 2, 0.02)
    path.rotation_euler[2] = angle
    mat = get_or_create_material("Park_Concrete", "#A0A0A0", 0.7)
    path.data.materials.append(mat)
    return path


def create_tree(x, y, trunk_h=4.0, canopy_r=2.5):
    """Bare deciduous tree (March — no leaves)."""
    # Trunk
    bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=trunk_h,
                                         location=(x, y, trunk_h / 2))
    trunk = bpy.context.active_object
    trunk.name = f"Tree_Trunk_{x:.0f}_{y:.0f}"
    mat = get_or_create_material("Tree_Bark", "#4A3528", 0.9)
    trunk.data.materials.append(mat)

    # Main branches (3-4 from top of trunk)
    branches = []
    for i in range(random.randint(3, 5)):
        angle = random.uniform(0, 2 * math.pi)
        tilt = random.uniform(0.4, 0.8)
        branch_len = random.uniform(1.5, 3.0)
        bx = x + math.cos(angle) * branch_len * 0.5
        by = y + math.sin(angle) * branch_len * 0.5
        bz = trunk_h + branch_len * 0.3

        bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=branch_len,
                                             location=(bx, by, bz))
        branch = bpy.context.active_object
        branch.name = f"Branch_{x:.0f}_{y:.0f}_{i}"
        branch.rotation_euler = (tilt * math.cos(angle + 1.5),
                                  tilt * math.sin(angle + 1.5), angle)
        branch.data.materials.append(mat)
        branches.append(branch)

    return [trunk] + branches


def create_boulder(x, y, scale=0.6):
    """Large decorative boulder."""
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=scale,
                                           location=(x, y, scale * 0.4))
    boulder = bpy.context.active_object
    boulder.name = f"Boulder_{x:.0f}_{y:.0f}"
    boulder.scale = (random.uniform(0.8, 1.2), random.uniform(0.8, 1.2), random.uniform(0.5, 0.8))
    boulder.rotation_euler = (random.uniform(0, 0.3), random.uniform(0, 0.3), random.uniform(0, 6.28))
    mat = get_or_create_material("Boulder_Grey", "#787878", 0.85)
    boulder.data.materials.append(mat)
    return boulder


def create_bench(x, y, rotation=0):
    """Park bench."""
    # Seat
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 0.45))
    seat = bpy.context.active_object
    seat.name = f"Bench_Seat_{x:.0f}_{y:.0f}"
    seat.scale = (0.8, 0.25, 0.025)
    seat.rotation_euler[2] = rotation
    mat_wood = get_or_create_material("Bench_Wood", "#8B6914", 0.8)
    seat.data.materials.append(mat_wood)

    # Back
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x - 0.15 * math.sin(rotation),
                                                        y + 0.15 * math.cos(rotation), 0.7))
    back = bpy.context.active_object
    back.name = f"Bench_Back_{x:.0f}_{y:.0f}"
    back.scale = (0.8, 0.02, 0.15)
    back.rotation_euler[2] = rotation
    back.data.materials.append(mat_wood)

    # Legs (2)
    mat_metal = get_or_create_material("Bench_Metal", "#3A3A3A", 0.5)
    for side in [-0.6, 0.6]:
        lx = x + side * math.cos(rotation)
        ly = y + side * math.sin(rotation)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(lx, ly, 0.22))
        leg = bpy.context.active_object
        leg.name = f"Bench_Leg_{x:.0f}_{side:.0f}"
        leg.scale = (0.02, 0.2, 0.22)
        leg.rotation_euler[2] = rotation
        leg.data.materials.append(mat_metal)

    return seat


def create_lamp_post(x, y, height=4.5):
    """Modern LED lamp post."""
    # Pole
    bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=height,
                                         location=(x, y, height / 2))
    pole = bpy.context.active_object
    pole.name = f"Lamp_Pole_{x:.0f}_{y:.0f}"
    mat = get_or_create_material("Lamp_Metal", "#505050", 0.4)
    pole.data.materials.append(mat)

    # Light head
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, height))
    head = bpy.context.active_object
    head.name = f"Lamp_Head_{x:.0f}_{y:.0f}"
    head.scale = (0.3, 0.15, 0.05)
    mat_light = get_or_create_material("Lamp_Light", "#E0E0D0", 0.3)
    head.data.materials.append(mat_light)

    return pole


def create_playground(cx, cy):
    """Simple playground structure."""
    objects = []

    # Main frame (orange)
    mat_orange = get_or_create_material("Playground_Orange", "#E06020", 0.6)
    mat_blue = get_or_create_material("Playground_Blue", "#2060C0", 0.6)

    # Vertical posts
    for dx, dy in [(-2, -1.5), (2, -1.5), (-2, 1.5), (2, 1.5)]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=3.0,
                                             location=(cx + dx, cy + dy, 1.5))
        post = bpy.context.active_object
        post.name = f"PG_Post_{dx}_{dy}"
        post.data.materials.append(mat_orange)
        objects.append(post)

    # Top bars
    for dy in [-1.5, 1.5]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=4.0,
                                             location=(cx, cy + dy, 3.0))
        bar = bpy.context.active_object
        bar.name = f"PG_TopBar_{dy}"
        bar.rotation_euler[1] = math.pi / 2
        bar.data.materials.append(mat_orange)
        objects.append(bar)

    # Slide (blue)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(cx + 3, cy, 1.0))
    slide = bpy.context.active_object
    slide.name = "PG_Slide"
    slide.scale = (1.5, 0.4, 0.03)
    slide.rotation_euler[1] = -0.5
    slide.data.materials.append(mat_blue)
    objects.append(slide)

    # Platform
    bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, 2.8))
    platform = bpy.context.active_object
    platform.name = "PG_Platform"
    platform.scale = (2.0, 1.5, 0.05)
    mat_grey = get_or_create_material("PG_Platform", "#888888", 0.6)
    platform.data.materials.append(mat_grey)
    objects.append(platform)

    # Fence around playground
    mat_fence = get_or_create_material("PG_Fence", "#2A2A2A", 0.5)
    fence_r = 5.0
    for angle in range(0, 360, 15):
        rad = math.radians(angle)
        fx = cx + fence_r * math.cos(rad)
        fy = cy + fence_r * math.sin(rad)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=0.9,
                                             location=(fx, fy, 0.45))
        post = bpy.context.active_object
        post.name = f"Fence_{angle}"
        post.data.materials.append(mat_fence)
        objects.append(post)

    return objects


def create_stepped_seating(cx, cy, width=8.0, depth=3.0, steps=4):
    """Concrete stepped amphitheatre seating."""
    objects = []
    mat = get_or_create_material("Seating_Concrete", "#B0B0A8", 0.7)

    for i in range(steps):
        step_z = i * 0.35
        step_y = cy + i * (depth / steps)
        bpy.ops.mesh.primitive_cube_add(size=1,
                                         location=(cx, step_y, step_z + 0.175))
        step = bpy.context.active_object
        step.name = f"Step_{i}"
        step.scale = (width / 2, (depth / steps) / 2, 0.175)
        step.data.materials.append(mat)
        objects.append(step)

    return objects


def create_fire_hydrant(x, y):
    """Yellow fire hydrant."""
    bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=0.6,
                                         location=(x, y, 0.3))
    body = bpy.context.active_object
    body.name = f"Hydrant_{x:.0f}_{y:.0f}"
    mat = get_or_create_material("Hydrant_Yellow", "#E0C020", 0.5)
    body.data.materials.append(mat)

    # Cap
    bpy.ops.mesh.primitive_cylinder_add(radius=0.14, depth=0.08,
                                         location=(x, y, 0.64))
    cap = bpy.context.active_object
    cap.name = f"Hydrant_Cap_{x:.0f}_{y:.0f}"
    cap.data.materials.append(mat)

    return body


def main():
    # Create park collection
    park_col = bpy.data.collections.new("Bellevue_Square_Park")
    bpy.context.scene.collection.children.link(park_col)

    all_objects = []

    # Ground
    ground = create_ground()
    all_objects.append(ground)

    # Pathways (crossing pattern from photos)
    cx, cy = PARK_CENTER_X, PARK_CENTER_Y
    hw, hd = PARK_W / 2, PARK_D / 2

    paths = [
        # Main cross paths
        ((cx - hw, cy), (cx + hw, cy)),          # East-west through center
        ((cx, cy - hd), (cx, cy + hd)),          # North-south through center
        # Diagonal paths
        ((cx - hw, cy - hd), (cx + 5, cy + 5)),  # SW to center
        ((cx + hw, cy - hd), (cx - 5, cy + 5)),  # SE to center
        # Perimeter paths
        ((cx - hw, cy - hd + 2), (cx + hw, cy - hd + 2)),  # South edge
        ((cx - hw, cy + hd - 2), (cx + hw, cy + hd - 2)),  # North edge
    ]
    for start, end in paths:
        p = create_pathway(start, end)
        all_objects.append(p)

    # Trees (~15 mature trees scattered)
    random.seed(42)  # Reproducible
    tree_positions = [
        (cx - 25, cy - 15), (cx - 20, cy + 10), (cx - 15, cy - 5),
        (cx - 10, cy + 15), (cx - 5, cy - 18), (cx - 5, cy + 5),
        (cx + 5, cy - 10), (cx + 10, cy + 12), (cx + 15, cy - 8),
        (cx + 20, cy + 5), (cx + 25, cy - 12), (cx + 25, cy + 15),
        (cx - 28, cy), (cx + 28, cy - 5), (cx, cy + 20),
    ]
    for tx, ty in tree_positions:
        height = random.uniform(5.0, 8.0)
        tree_objs = create_tree(tx, ty, trunk_h=height)
        all_objects.extend(tree_objs)

    # Boulders (scattered on grass — visible in photos)
    boulder_positions = [
        (cx - 8, cy + 8), (cx + 5, cy + 10), (cx - 15, cy - 8),
        (cx + 12, cy - 5), (cx, cy + 15), (cx + 18, cy + 8),
    ]
    for bx, by in boulder_positions:
        b = create_boulder(bx, by, random.uniform(0.4, 0.7))
        all_objects.append(b)

    # Benches (along paths)
    bench_positions = [
        (cx - 15, cy + 3, 0), (cx + 15, cy - 3, math.pi),
        (cx - 5, cy + 20, math.pi / 2), (cx + 5, cy - 20, -math.pi / 2),
        (cx - 25, cy + 12, 0), (cx + 20, cy + 15, math.pi / 4),
    ]
    for bx, by, rot in bench_positions:
        create_bench(bx, by, rot)

    # Lamp posts (along paths, visible in night photo)
    lamp_positions = [
        (cx - 20, cy), (cx + 20, cy), (cx, cy + 18), (cx, cy - 18),
        (cx - 30, cy + 15), (cx + 30, cy - 15),
    ]
    for lx, ly in lamp_positions:
        create_lamp_post(lx, ly)

    # Playground (NE corner — orange/blue equipment visible in photos)
    pg_objects = create_playground(cx + 18, cy + 12)

    # Stepped seating (W side — concrete amphitheatre from night photo)
    create_stepped_seating(cx - 28, cy - 5, width=6.0, depth=3.0, steps=4)

    # Fire hydrants (yellow, visible at SW and SE corners)
    create_fire_hydrant(cx - hw + 1, cy - hd + 1)
    create_fire_hydrant(cx + hw - 1, cy - hd + 1)

    # Move all park objects to collection
    for obj in bpy.context.scene.objects:
        if obj.name.startswith(("Park_", "Path_", "Tree_", "Branch_", "Boulder_",
                                 "Bench_", "Lamp_", "PG_", "Fence_", "Step_",
                                 "Hydrant_")):
            for col in obj.users_collection:
                col.objects.unlink(obj)
            park_col.objects.link(obj)

    print(f"Park created with {len(bpy.context.scene.objects)} objects")


if __name__ == "__main__":
    main()
