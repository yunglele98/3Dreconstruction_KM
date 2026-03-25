"""
Step 2: Parametric Blender building generator.

Reads JSON building parameter files from Step 1 and creates detailed 3D
architectural geometry in Blender — walls, windows, doors, roofs, porches,
and decorative elements as actual mesh geometry.

Usage (run inside Blender):
    blender --background --python generate_building.py -- --params params/22_Lippincott_St.json
    blender --python generate_building.py -- --params params/  (all buildings)

Or from Blender scripting tab:
    exec(open('C:/Users/liam1/blender_buildings/generate_building.py').read())
"""

import bpy
import bmesh
import json
import math
import os
import sys
import time
from pathlib import Path
from mathutils import Vector, Matrix

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PARAMS_DIR = Path(__file__).parent / "params" if "__file__" in dir() else Path("C:/Users/liam1/blender_buildings/params")
DEFAULT_DEPTH = 10.0  # default building depth when not specified

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def clear_scene():
    """Remove all objects from the scene."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    # Clean orphan data
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)


def get_or_create_material(name, colour_hex=None, colour_rgb=None, roughness=0.8):
    """Get existing material or create a new Principled BSDF material."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name=name)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        if colour_hex:
            r, g, b = hex_to_rgb(colour_hex)
            bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        elif colour_rgb:
            bsdf.inputs["Base Color"].default_value = (*colour_rgb, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
    return mat


def _add_wall_coords(nodes, links, target_input, scale_val=8.0):
    """Add box-projection texture coordinates that work on all wall faces.

    Uses Generated coords with X+Y as horizontal (so bricks tile correctly
    on front, back AND side walls) and Z as vertical.
    """
    texcoord = nodes.new('ShaderNodeTexCoord')
    texcoord.location = (-800, 0)

    sep = nodes.new('ShaderNodeSeparateXYZ')
    sep.location = (-650, 0)
    links.new(texcoord.outputs["Generated"], sep.inputs["Vector"])

    # Horizontal = X + Y (on front face Y≈0→gives X; on side face X≈const→gives Y)
    add = nodes.new('ShaderNodeMath')
    add.operation = 'ADD'
    add.location = (-500, 50)
    links.new(sep.outputs["X"], add.inputs[0])
    links.new(sep.outputs["Y"], add.inputs[1])

    # Combine (X+Y, Z, 0) → horizontal bricks on all vertical faces
    combine = nodes.new('ShaderNodeCombineXYZ')
    combine.location = (-350, 0)
    links.new(add.outputs["Value"], combine.inputs["X"])
    links.new(sep.outputs["Z"], combine.inputs["Y"])

    # Scale mapping
    mapping = nodes.new('ShaderNodeMapping')
    mapping.location = (-200, 0)
    mapping.inputs["Scale"].default_value = (scale_val, scale_val, scale_val)
    links.new(combine.outputs["Vector"], mapping.inputs["Vector"])

    links.new(mapping.outputs["Vector"], target_input)
    return texcoord, mapping


def create_brick_material(name, brick_hex, mortar_hex="#B0A898", scale=8.0):
    """Create a procedural brick material with mortar lines and bump."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Keep default Principled BSDF and Output, just add texture nodes
    bsdf = nodes.get("Principled BSDF")
    output = nodes.get("Material Output")
    bsdf.inputs["Roughness"].default_value = 0.85

    # Brick texture
    brick = nodes.new('ShaderNodeTexBrick')
    brick.location = (0, 0)
    r, g, b = hex_to_rgb(brick_hex)
    brick.inputs["Color1"].default_value = (r, g, b, 1.0)
    brick.inputs["Color2"].default_value = (r * 0.85, g * 0.85, b * 0.85, 1.0)
    mr, mg, mb = hex_to_rgb(mortar_hex)
    brick.inputs["Mortar"].default_value = (mr, mg, mb, 1.0)
    brick.inputs["Scale"].default_value = 1.0  # scale handled by mapping node
    brick.inputs["Mortar Size"].default_value = 0.015
    brick.inputs["Mortar Smooth"].default_value = 0.1
    brick.inputs["Brick Width"].default_value = 0.5
    brick.inputs["Row Height"].default_value = 0.25

    # Box-projection wall coordinates
    _add_wall_coords(nodes, links, brick.inputs["Vector"], scale_val=scale)

    # Bump from brick pattern
    bump = nodes.new('ShaderNodeBump')
    bump.location = (200, -200)
    bump.inputs["Strength"].default_value = 0.3
    bump.inputs["Distance"].default_value = 0.01

    links.new(brick.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(brick.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    return mat


def create_wood_material(name, wood_hex):
    """Create a procedural wood grain material."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.65

    wave = nodes.new('ShaderNodeTexWave')
    wave.location = (0, 0)
    wave.wave_type = 'RINGS'
    wave.inputs["Scale"].default_value = 3.0
    wave.inputs["Distortion"].default_value = 8.0
    wave.inputs["Detail"].default_value = 3.0

    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.location = (200, 0)
    r, g, b = hex_to_rgb(wood_hex)
    ramp.color_ramp.elements[0].color = (r * 0.7, g * 0.7, b * 0.7, 1.0)
    ramp.color_ramp.elements[1].color = (r, g, b, 1.0)

    # Box-projection wall coordinates (wave has its own scale, mapping just does coords)
    _add_wall_coords(nodes, links, wave.inputs["Vector"], scale_val=1.0)

    bump = nodes.new('ShaderNodeBump')
    bump.location = (200, -200)
    bump.inputs["Strength"].default_value = 0.15

    links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(wave.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    return mat


def create_roof_material(name, roof_hex):
    """Create a procedural roof shingle material with texture."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.92

    shingle = nodes.new('ShaderNodeTexBrick')
    shingle.location = (0, 0)
    r, g, b = hex_to_rgb(roof_hex)
    shingle.inputs["Color1"].default_value = (r * 1.2, g * 1.2, b * 1.2, 1.0)
    shingle.inputs["Color2"].default_value = (r * 0.7, g * 0.7, b * 0.7, 1.0)
    shingle.inputs["Mortar"].default_value = (r * 0.4, g * 0.4, b * 0.4, 1.0)
    shingle.inputs["Scale"].default_value = 1.0  # scale via mapping
    shingle.inputs["Mortar Size"].default_value = 0.02
    shingle.inputs["Brick Width"].default_value = 0.25
    shingle.inputs["Row Height"].default_value = 0.12

    # Roof uses Generated with X+Y for consistent shingle pattern on sloped faces
    _add_wall_coords(nodes, links, shingle.inputs["Vector"], scale_val=15.0)

    bump = nodes.new('ShaderNodeBump')
    bump.location = (200, -200)
    bump.inputs["Strength"].default_value = 0.4

    links.new(shingle.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(shingle.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    return mat


def create_glass_material(name="mat_glass"):
    """Create a realistic glass material with transparency and reflection."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")

    bsdf.inputs["Base Color"].default_value = (0.7, 0.82, 0.88, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.02
    bsdf.inputs["Alpha"].default_value = 0.3
    # Try transmission for glass look
    for key in ["Transmission Weight", "Transmission"]:
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.7
            break

    try:
        mat.blend_method = 'BLEND'
    except:
        pass
    return mat


def create_stone_material(name, stone_hex):
    """Create a procedural stone/concrete material."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.75

    r, g, b = hex_to_rgb(stone_hex)

    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (0, 0)
    noise.inputs["Scale"].default_value = 25.0
    noise.inputs["Detail"].default_value = 6.0
    noise.inputs["Roughness"].default_value = 0.6

    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.location = (200, 0)
    ramp.color_ramp.elements[0].color = (r * 0.85, g * 0.85, b * 0.85, 1.0)
    ramp.color_ramp.elements[1].color = (r, g, b, 1.0)

    # Box-projection wall coordinates (noise has its own scale, mapping just does coords)
    _add_wall_coords(nodes, links, noise.inputs["Vector"], scale_val=1.0)

    bump = nodes.new('ShaderNodeBump')
    bump.location = (200, -200)
    bump.inputs["Strength"].default_value = 0.2

    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    return mat


def create_painted_material(name, paint_hex):
    """Create a painted surface material with slight wear/aging."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.55

    r, g, b = hex_to_rgb(paint_hex)

    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (0, 0)
    noise.inputs["Scale"].default_value = 40.0
    noise.inputs["Detail"].default_value = 3.0

    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.location = (200, 0)
    ramp.color_ramp.elements[0].color = (r * 0.92, g * 0.92, b * 0.92, 1.0)
    ramp.color_ramp.elements[1].color = (r, g, b, 1.0)

    # Box-projection wall coordinates (noise has its own scale, mapping just does coords)
    _add_wall_coords(nodes, links, noise.inputs["Vector"], scale_val=1.0)

    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    return mat


def hex_to_rgb(hex_str):
    """Convert hex colour string to (r, g, b) floats in [0,1]."""
    hex_str = hex_str.lstrip('#')
    if len(hex_str) != 6:
        return (0.5, 0.5, 0.5)
    r = int(hex_str[0:2], 16) / 255.0
    g = int(hex_str[2:4], 16) / 255.0
    b = int(hex_str[4:6], 16) / 255.0
    return (r, g, b)


def colour_name_to_hex(name):
    """Map common colour names to hex values."""
    normalized = name.lower().replace(" ", "_")
    mapping = {
        "red-orange": "#B85A3A",
        "red_orange": "#B85A3A",
        "dark_red_brown": "#6B3A2E",
        "dark_red_burgundy_maroon": "#5A2020",
        "dark_forest_green": "#2D4A2D",
        "dark_green": "#2D4A2D",
        "turquoise_teal": "#3FBFBF",
        "grey_tan": "#9E9585",
        "red_brown": "#8B5A3A",
        "cream_buff": "#D4C9A8",
        "buff_tan": "#C8B88A",
        "white": "#F0F0F0",
        "grey_blue": "#5A6A7A",
        "dark_brown_stained": "#3E2A1A",
        "dark_brown": "#4A2E1A",
        "dark_grey_black": "#2E2E2E",
        "dark_grey": "#3A3A3A",
        "blue": "#4070B0",
        "red": "#C03030",
        "bright_red": "#CC2020",
        "dark_bronze": "#4A3A2A",
        "dark_alumin": "#3A3A3A",
        "natural": "#B89060",
        "black": "#1A1A1A",
        "sandstone": "#C8B88A",
        "buff_brick": "#C9A46A",
        "buff": "#D4C9A8",
        "tan": "#BFA07A",
        "cream": "#E8E0D0",
        "bronze": "#5C4632",
        "charcoal": "#2F3238",
        "olive_green": "#5D6F3A",
    }
    if normalized in mapping:
        return mapping[normalized]
    # Try to find partial match
    for key, val in mapping.items():
        if key in normalized:
            return val
    if "dark" in normalized and ("brown" in normalized or "wood" in normalized):
        return "#4A3020"
    if "dark" in normalized and ("grey" in normalized or "gray" in normalized or "black" in normalized):
        return "#2F3238"
    if "buff" in normalized or "sand" in normalized:
        return "#C8B88A"
    if "cream" in normalized or "stone" in normalized:
        return "#D8CFBF"
    if "red" in normalized and "brick" in normalized:
        return "#B85A3A"
    return "#808080"


def infer_hex_from_text(*texts, default="#808080"):
    """Infer a representative colour hex from one or more descriptive strings."""
    merged = " ".join(str(t) for t in texts if t).lower()
    if not merged:
        return default
    return colour_name_to_hex(merged)


def get_stone_hex(*texts, default="#C8C0B0"):
    """Infer a stone/trim colour from descriptive text."""
    merged = " ".join(str(t) for t in texts if t).lower()
    if "buff" in merged or "sand" in merged or "tan" in merged:
        return "#C8B88A"
    if "cream" in merged or "light" in merged:
        return "#E8E0D0"
    if "grey" in merged or "gray" in merged:
        return "#B8B2A8"
    if "red brick" in merged:
        return "#B85A3A"
    return default


def get_roof_hex(params):
    """Extract roof colour hex from params, checking multiple locations."""
    # Check roof_detail.colour_hex first
    rd = params.get("roof_detail", {})
    if isinstance(rd, dict):
        h = rd.get("colour_hex", "")
        if h and h.startswith("#"):
            return h
        # Check hip_element
        hip = rd.get("hip_element", {})
        if isinstance(hip, dict):
            h = hip.get("colour_hex", "")
            if h and h.startswith("#"):
                return h

    # Check roof_colour
    rc = str(params.get("roof_colour", "")).lower()
    if rc:
        if "dark" in rc:
            return "#3A3A3A"
        elif "grey" in rc or "gray" in rc:
            return "#5A5A5A"
        elif "red" in rc or "brown" in rc:
            return "#6B3A2E"

    # Check roof_material for colour hints
    rm = str(params.get("roof_material", "")).lower()
    if "dark" in rm and ("grey" in rm or "black" in rm):
        return "#3A3A3A"
    elif "grey" in rm or "gray" in rm:
        return "#5A5A5A"
    elif "red" in rm:
        return "#7A4030"
    elif "copper" in rm or "green" in rm:
        return "#4A6A50"

    return "#4A4A4A"


def assign_material(obj, mat):
    """Assign a material to an object."""
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


def create_box(name, width, depth, height, location=(0, 0, 0)):
    """Create a box mesh. Origin at bottom-center of front face."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (width, depth, height)
    bpy.ops.object.transform_apply(scale=True)
    # Move so origin is at bottom-center of front face
    obj.location = (location[0], location[1] - depth / 2, location[2] + height / 2)
    return obj


def boolean_cut(target, cutter, remove_cutter=True):
    """Apply a boolean difference operation."""
    # Triangulate cutter for reliable booleans with curved geometry
    bpy.context.view_layer.objects.active = cutter
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.quads_convert_to_tris(quad_method='BEAUTY', ngon_method='BEAUTY')
    bpy.ops.object.mode_set(mode='OBJECT')

    mod = target.modifiers.new(name="Bool", type='BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.object = cutter
    # EXACT solver is more reliable for arched/curved cuts
    for solver in ['EXACT', 'FAST', 'FLOAT']:
        try:
            mod.solver = solver
            break
        except TypeError:
            continue
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)
    if remove_cutter:
        bpy.data.objects.remove(cutter, do_unlink=True)
    # Fix normals after boolean
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')


def create_arch_cutter(name, width, height, spring_height, arch_type="semicircular",
                       depth=1.0, segments=24):
    """Create a mesh shape for cutting arched openings.

    The arch sits with its base at z=0, centered at x=0.
    spring_height = height of the vertical sides before the arch begins.
    """
    bm = bmesh.new()

    arch_height = height - spring_height
    half_w = width / 2
    half_d = depth / 2

    # Build 2D profile (front face), then extrude
    verts_2d = []

    # Bottom-left to top of spring line (left side)
    verts_2d.append((-half_w, 0))
    verts_2d.append((-half_w, spring_height))

    # Arch curve from left to right
    if arch_type in ("semicircular", "segmental"):
        radius = half_w
        cx, cy = 0, spring_height
        for i in range(segments + 1):
            angle = math.pi - (math.pi * i / segments)
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            verts_2d.append((x, y))
    elif arch_type in ("pointed", "pointed_gothic", "gothic"):
        # Gothic pointed arch: two arcs meeting at a point
        radius = width * 0.7  # larger radius gives more pointed arch
        for i in range(segments // 2 + 1):
            angle = math.pi / 2 + (math.pi / 3) * i / (segments // 2)
            x = -half_w + radius * math.cos(math.pi - angle)
            y = spring_height + radius * math.sin(math.pi - angle)
            # Clamp to center
            if x > 0:
                break
            verts_2d.append((x, min(y, height)))
        # Peak
        verts_2d.append((0, height))
        for i in range(segments // 2 + 1):
            angle = math.pi / 2 - (math.pi / 3) * i / (segments // 2)
            x = half_w - radius * math.cos(math.pi - angle)
            y = spring_height + radius * math.sin(math.pi - angle)
            if x < 0:
                continue
            verts_2d.append((x, min(y, height)))
    else:
        # Default rectangular
        verts_2d.append((-half_w, height))
        verts_2d.append((half_w, height))

    # Top of spring line to bottom (right side)
    verts_2d.append((half_w, spring_height))
    verts_2d.append((half_w, 0))

    # Create front face
    front_verts = []
    for x, z in verts_2d:
        v = bm.verts.new((x, -half_d, z))
        front_verts.append(v)

    # Create back face
    back_verts = []
    for x, z in verts_2d:
        v = bm.verts.new((x, half_d, z))
        back_verts.append(v)

    # Create faces
    n = len(front_verts)
    # Front face
    try:
        bm.faces.new(front_verts)
    except:
        pass
    # Back face
    try:
        bm.faces.new(list(reversed(back_verts)))
    except:
        pass
    # Side faces
    for i in range(n):
        j = (i + 1) % n
        try:
            bm.faces.new([front_verts[i], front_verts[j], back_verts[j], back_verts[i]])
        except:
            pass

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def create_rect_cutter(name, width, height, depth=0.5):
    """Create a rectangular cutter for window/door openings."""
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (width, depth, height)
    bpy.ops.object.transform_apply(scale=True)
    return obj


def get_facade_hex(params):
    """Extract facade colour hex from params."""
    facade_hex = None
    facade_detail = params.get("facade_detail", {})
    if isinstance(facade_detail, dict):
        facade_hex = facade_detail.get("brick_colour_hex")
    if not facade_hex:
        fc = params.get("facade_colour", "red-orange")
        if isinstance(fc, str) and fc.startswith("#"):
            facade_hex = fc
        else:
            facade_hex = infer_hex_from_text(fc, params.get("facade_material", "brick"), default="#B85A3A")
    return facade_hex


# ---------------------------------------------------------------------------
# HCD (Heritage Conservation District) helpers
# ---------------------------------------------------------------------------

def get_era_defaults(params):
    """Return material/style defaults based on HCD construction date."""
    hcd = params.get('hcd_data', {})
    date_str = hcd.get('construction_date', '')
    defaults = {
        'brick_colour': (0.45, 0.18, 0.10, 1.0),  # default red brick
        'mortar_colour': (0.85, 0.82, 0.75, 1.0),
        'trim_style': 'simple',
        'window_arch': 'flat',
    }
    if 'Pre-1889' in date_str:
        # Early Victorian - rich red brick, segmental arches common
        defaults['brick_colour'] = (0.5, 0.15, 0.08, 1.0)
        defaults['trim_style'] = 'ornate'
        defaults['window_arch'] = 'segmental'
    elif '1890' in date_str or '1903' in date_str or '1904' in date_str or '1913' in date_str:
        # Late Victorian / Edwardian - buff or red brick, mixed arches
        defaults['trim_style'] = 'moderate'
        defaults['window_arch'] = 'mixed'
    elif '1914' in date_str or '1930' in date_str:
        # Early 20th century - flatter details, stone trim
        defaults['trim_style'] = 'restrained'
        defaults['window_arch'] = 'flat'
    return defaults


def get_typology_hints(params):
    """Return geometry hints based on HCD building typology."""
    hcd = params.get('hcd_data', {})
    typology = hcd.get('typology', '').lower()
    hints = {
        'has_party_wall_left': False,
        'has_party_wall_right': False,
        'is_bay_and_gable': False,
        'is_ontario_cottage': False,
        'expected_floors': None,
    }
    if 'row' in typology:
        hints['has_party_wall_left'] = True
        hints['has_party_wall_right'] = True
    elif 'semi-detached' in typology:
        hints['has_party_wall_left'] = True  # shared wall on one side
    if 'bay-and-gable' in typology:
        hints['is_bay_and_gable'] = True
    if 'ontario cottage' in typology:
        hints['is_ontario_cottage'] = True
        hints['expected_floors'] = 1
    if 'institutional' in typology:
        hints['expected_floors'] = 3
    return hints


def _merge_missing_dict(target, defaults):
    """Recursively merge dict defaults without overwriting explicit params."""
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
        elif isinstance(target[key], dict) and isinstance(value, dict):
            _merge_missing_dict(target[key], value)


def apply_hcd_guide_defaults(params):
    """Derive structured generator hints from HCD guide metadata."""
    if not isinstance(params, dict):
        return params

    hcd = params.get("hcd_data", {})
    if not isinstance(hcd, dict):
        return params

    features = [str(f).lower() for f in hcd.get("building_features", [])]
    statement = str(hcd.get("statement_of_contribution", "")).lower()
    typology = str(hcd.get("typology", "")).lower()
    combined = features + [statement]

    def has(*phrases):
        return any(any(p in text for p in phrases) for text in combined)

    decorative = params.setdefault("decorative_elements", {})
    if not isinstance(decorative, dict):
        decorative = {}
        params["decorative_elements"] = decorative

    if has("string course", "string courses") and "string_courses" not in decorative:
        decorative["string_courses"] = {
            "present": True,
            "width_mm": 140,
            "projection_mm": 25,
            "colour_hex": "#D4C9A8",
        }

    if has("quoin", "quoining") and "quoins" not in decorative:
        decorative["quoins"] = {
            "present": True,
            "strip_width_mm": 220,
            "projection_mm": 18,
            "colour_hex": "#D4C9A8",
        }

    if has("voussoir", "voussoirs") and "stone_voussoirs" not in decorative and "voussoirs" not in decorative:
        decorative["stone_voussoirs"] = {
            "present": True,
            "colour_hex": "#D4C9A8",
        }

    if has("stone lintel", "stone lintels", "stone sills") and "stone_lintels" not in decorative:
        decorative["stone_lintels"] = {
            "present": True,
            "colour_hex": "#D4C9A8",
        }

    if has("bargeboard") and "bargeboard" not in decorative:
        decorative["bargeboard"] = {
            "present": True,
            "type": "decorative",
            "colour_hex": "#4A3324",
            "width_mm": 220,
        }

    if has("bracket", "brackets") and "gable_brackets" not in decorative:
        decorative["gable_brackets"] = {
            "type": "paired_scroll",
            "count": 4,
            "projection_mm": 220,
            "height_mm": 320,
            "colour_hex": "#4A3324",
        }

    if has("shingle", "shingles in gable") and "ornamental_shingles" not in decorative:
        decorative["ornamental_shingles"] = {
            "present": True,
            "colour_hex": "#6B4C3B",
            "exposure_mm": 110,
        }

    if has("cornice") and "cornice" not in decorative:
        decorative["cornice"] = {
            "present": True,
            "projection_mm": 180,
            "height_mm": 220,
            "colour_hex": "#D4C9A8",
        }

    if has("bay window", "bay windows", "double-height bay", "double-height bays") and "bay_window" not in params:
        params["bay_window"] = {
            "present": True,
            "type": "Three-sided projecting bay" if "bay-and-gable" in typology else "Projecting bay",
            "floors": [0, 1] if ("bay-and-gable" in typology or has("double-height bay", "double-height bays")) else [0],
            "width_m": min(2.6, max(1.8, params.get("facade_width_m", 5.0) * 0.42)),
            "projection_m": 0.6,
        }

    if has("commercial storefront", "storefront", "commercial glazing") and not params.get("has_storefront"):
        params["has_storefront"] = True

    if params.get("has_storefront"):
        storefront = params.setdefault("storefront", {})
        if isinstance(storefront, dict):
            _merge_missing_dict(storefront, {
                "type": "Commercial ground floor",
                "width_m": params.get("facade_width_m", 6.0),
                "height_m": params.get("floor_heights_m", [3.5])[0] if params.get("floor_heights_m") else 3.5,
            })

    roof_features = params.setdefault("roof_features", [])
    if isinstance(roof_features, list):
        if has("dormer", "dormers") and "dormers" not in roof_features:
            roof_features.append("dormers")
        if has("chimney", "chimneys") and "chimney" not in roof_features:
            roof_features.append("chimney")
        if has("turret") and "tower" not in roof_features:
            roof_features.append("tower")

    roof_type = str(params.get("roof_type", ""))
    if not roof_type and "mansard" in statement:
        params["roof_type"] = "Mansard"

    return params


# ---------------------------------------------------------------------------
# Building element generators
# ---------------------------------------------------------------------------

def create_walls(params, depth=None):
    """Create the main building walls as a hollow box."""
    width = params.get("facade_width_m", 6.0)
    if depth is None:
        depth = params.get("facade_depth_m", DEFAULT_DEPTH)
    total_h = params.get("total_height_m", 9.0)

    # Get wall height (up to eave, not gable peak)
    floor_heights = params.get("floor_heights_m", [3.0])
    wall_h = sum(floor_heights)

    wall_thickness = 0.3

    # Outer box
    outer = create_box("walls_outer", width, depth, wall_h, location=(0, 0, 0))

    # Inner box (for hollow walls) — cut all the way through to avoid interior floor
    inner = create_box("walls_inner",
                       width - 2 * wall_thickness,
                       depth - 2 * wall_thickness,
                       wall_h + 0.02,
                       location=(0, -wall_thickness, -0.01))

    boolean_cut(outer, inner)
    outer.name = "walls"

    # Fix normals after boolean — ensures textures show on exterior
    bpy.context.view_layer.objects.active = outer
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Get facade material — use procedural textures based on material type
    facade_hex = get_facade_hex(params)
    hex_id = facade_hex.lstrip('#')
    mat_type = str(params.get("facade_material", "brick")).lower()
    mortar_hex = "#B0A898"
    fd = params.get("facade_detail", {})
    if isinstance(fd, dict):
        mc = fd.get("mortar_colour", "")
        if "grey" in str(mc).lower():
            mortar_hex = "#8A8A8A"
        elif "light" in str(mc).lower():
            mortar_hex = "#C0B8A8"

    if "brick" in mat_type:
        mat = create_brick_material(f"mat_brick_{hex_id}", facade_hex, mortar_hex)
    elif "stone" in mat_type or "concrete" in mat_type:
        mat = create_stone_material(f"mat_stone_{hex_id}", facade_hex)
    elif (
        "paint" in mat_type
        or "stucco" in mat_type
        or "clapboard" in mat_type
        or "wood" in mat_type
        or "vinyl" in mat_type
        or "siding" in mat_type
    ):
        mat = create_painted_material(f"mat_painted_{hex_id}", facade_hex)
    else:
        mat = create_brick_material(f"mat_facade_{hex_id}", facade_hex, mortar_hex)
    assign_material(outer, mat)

    return outer, wall_h, width, depth


def _normalize_floor_index(floor_idx_raw, floor_heights):
    """Normalize mixed floor labels into numeric indices."""
    if isinstance(floor_idx_raw, (int, float)):
        return float(floor_idx_raw)
    if isinstance(floor_idx_raw, str):
        fl = floor_idx_raw.lower()
        if "ground" in fl or fl == "1":
            return 1.0
        if "second" in fl or fl == "2":
            return 2.0
        if "third" in fl or fl == "3":
            return 3.0
        if "fourth" in fl or fl == "4":
            return 4.0
        if "attic" in fl or "gable" in fl:
            return len(floor_heights) + 0.5
        try:
            return float(fl)
        except ValueError:
            return 1.0
    return 1.0


def _floor_has_window_spec(floor_data):
    """Return whether a floor entry contains enough data to place windows."""
    if not isinstance(floor_data, dict):
        return False
    if floor_data.get("windows"):
        return True
    if any(key in floor_data for key in ("count", "estimated_count")):
        return True
    for bay_key in ["left_bay", "center_bay", "right_bay"]:
        bay = floor_data.get(bay_key)
        if isinstance(bay, dict) and bay.get("count", 0) > 0:
            return True
    return False


def get_effective_windows_detail(params):
    """Return window detail entries with fallback counts from windows_per_floor."""
    floor_heights = params.get("floor_heights_m", [3.0])
    raw_detail = params.get("windows_detail", [])
    effective = []
    all_upper_templates = []

    for floor_data in raw_detail:
        if not isinstance(floor_data, dict):
            continue
        floor_copy = dict(floor_data)
        floor_label = str(floor_data.get("floor", "")).lower()
        if floor_label in {"all_upper", "upper", "upper_floors"}:
            all_upper_templates.append(floor_copy)
            continue
        effective.append(floor_copy)

    by_floor = {}
    for floor_data in effective:
        floor_idx = int(_normalize_floor_index(floor_data.get("floor", 1), floor_heights))
        by_floor[floor_idx] = floor_data

    windows_per_floor = params.get("windows_per_floor", [])
    default_width = params.get("window_width_m", 0.85)
    default_height = params.get("window_height_m", 1.3)
    window_type = str(params.get("window_type", "double_hung")).lower()
    arch_type = ""
    if "segment" in window_type:
        arch_type = "segmental"
    elif "arched" in window_type or "arch" in window_type:
        arch_type = "semicircular"

    for floor_num, count in enumerate(windows_per_floor, start=1):
        if not isinstance(count, int) or count <= 0:
            continue

        if floor_num in by_floor:
            floor_data = by_floor[floor_num]
            if not _floor_has_window_spec(floor_data):
                floor_data["count"] = count
                floor_data.setdefault("width_m", default_width)
                floor_data.setdefault("height_m", default_height)
                if arch_type:
                    floor_data.setdefault("head_shape", f"{arch_type}_arch")
            continue

        template = None
        if floor_num >= 2 and all_upper_templates:
            template = dict(all_upper_templates[0])

        if template is None:
            template = {"floor": floor_num}
        else:
            template["floor"] = floor_num

        template["count"] = count
        template.setdefault("width_m", default_width)
        template.setdefault("height_m", default_height)
        if arch_type:
            template.setdefault("head_shape", f"{arch_type}_arch")
        effective.append(template)
        by_floor[floor_num] = template

    return effective


def cut_windows(wall_obj, params, wall_h, facade_width, bldg_id=""):
    """Cut window openings from the front wall and add glass panes + frames."""
    windows_detail = get_effective_windows_detail(params)
    floor_heights = params.get("floor_heights_m", [3.0])
    trim_hex = get_trim_hex(params)

    # Pre-compute door x positions so we can skip overlapping ground floor windows
    door_specs = _resolve_doors(params, facade_width)
    door_x_positions = []
    for ds in door_specs:
        dpos = str(ds.get("position", "center")).lower()
        if "left" in dpos:
            door_x_positions.append(-facade_width / 4)
        elif "right" in dpos:
            door_x_positions.append(facade_width / 4)
        else:
            door_x_positions.append(0)

    has_storefront = params.get("has_storefront", False)

    window_objects = []

    for floor_data in windows_detail:
        if isinstance(floor_data, str):
            continue

        floor_idx = _normalize_floor_index(floor_data.get("floor", 1), floor_heights)

        # Skip ground floor windows for storefront buildings (storefront replaces them)
        if int(floor_idx) == 1 and has_storefront:
            continue

        # Skip ground floor windows that are described as non-window (entrance descriptions etc.)
        if int(floor_idx) == 1:
            desc = str(floor_data.get("description", "")).lower()
            if "entrance" in desc or "storefront" in desc or "glazing" in desc:
                continue

        # Calculate floor z offset — for half-floors (1.5, 2.5), use the floor below
        floor_int = int(floor_idx)
        if floor_idx != floor_int:  # half-floor (e.g. 1.5 → sum first 1 floor)
            z_base = sum(floor_heights[:floor_int])
        else:
            z_base = sum(floor_heights[:max(0, floor_int - 1)])

        # Extract windows from various formats
        windows = floor_data.get("windows", [])
        if not windows and ("count" in floor_data or "estimated_count" in floor_data):
            # Simple format — also handle estimated_* fields
            count = floor_data.get("count", floor_data.get("estimated_count", 0))
            w = floor_data.get("width_m", floor_data.get("estimated_width_m", 0.8))
            h = floor_data.get("height_m", floor_data.get("estimated_height_m", 1.3))
            windows = [{"count": count, "width_m": w, "height_m": h}]

        # Resolve gable/attic window from roof_detail if floor entry is just a note
        if not windows and floor_idx >= 2.5:
            gw = params.get("roof_detail", {}).get("gable_window", {})
            if isinstance(gw, dict) and gw.get("width_m"):
                windows = [{"count": 1, "width_m": gw["width_m"],
                           "height_m": gw.get("height_m", 0.8),
                           "type": gw.get("type", "arched"),
                           "arch_type": gw.get("arch_type", "segmental"),
                           "frame_colour": gw.get("frame_colour", "white")}]

        # Also check bay-based layouts (like 1A Leonard)
        for bay_key in ["left_bay", "center_bay", "right_bay"]:
            bay = floor_data.get(bay_key)
            if bay and isinstance(bay, dict) and bay.get("count", 0) > 0:
                windows.append(bay)

        # Check if individual window specs have position hints (e.g. "left_of_entrance")
        # If so, compute explicit x positions from those hints
        has_position_hints = any(
            isinstance(ws, dict) and ws.get("position") and
            any(kw in str(ws.get("position", "")).lower() for kw in ("left", "right", "center"))
            for ws in windows if isinstance(ws, dict)
        )

        for win_spec in windows:
            if isinstance(win_spec, str):
                continue
            if not isinstance(win_spec, dict):
                continue

            count = win_spec.get("count", 1)
            if count == 0:
                continue

            w = win_spec.get("width_m", win_spec.get("width_each_m", 0.8))
            h = win_spec.get("height_m", 1.3)

            # Window sill height — use param if provided, otherwise center in floor
            fi = max(0, int(floor_idx) - 1)
            fi = min(fi, len(floor_heights) - 1)
            floor_h_here = floor_heights[fi] if floor_heights else 3.0

            # Special case: gable/attic window — center in gable triangle
            if floor_idx >= 2.5 and "gable" in str(params.get("roof_type", "")).lower():
                pitch = params.get("roof_pitch_deg", 35)
                ridge_h = (facade_width / 2) * math.tan(math.radians(pitch))
                gable_center_z = wall_h + ridge_h * 0.45  # slightly below center
                sill_h = gable_center_z - h / 2
            else:
                explicit_sill = win_spec.get("sill_height_above_grade_m",
                                win_spec.get("sill_height_m",
                                floor_data.get("sill_height_above_grade_m")))
                if explicit_sill is not None:
                    sill_h = z_base + float(explicit_sill)
                else:
                    sill_h = z_base + max(0.8, (floor_h_here - h) / 2)

            # Determine arch type — check multiple fields
            win_type = str(win_spec.get("type", "double_hung")).lower()
            arch_spec = str(win_spec.get("arch_type", "")).lower()
            is_arched = any(kw in win_type for kw in ("arch", "gothic", "roman", "segmental")) or \
                        any(kw in arch_spec for kw in ("arch", "gothic", "semicircular", "pointed", "segmental"))

            arch_type = "semicircular"
            if "pointed" in win_type or "gothic" in win_type or "pointed" in arch_spec:
                arch_type = "pointed"
            elif "segmental" in win_type or "segmental" in arch_spec:
                arch_type = "segmental"

            # Compute x positions for this window spec
            # If individual spec has position hint, use it relative to door/facade
            win_pos = str(win_spec.get("position", "")).lower()
            c2c = floor_data.get("spacing_center_to_center_m")
            if has_position_hints and count == 1 and win_pos:
                # Use center-to-center spacing from floor data if available
                offset_x = float(c2c) if c2c else facade_width / 4
                if "left" in win_pos:
                    explicit_x = -offset_x
                elif "right" in win_pos:
                    explicit_x = offset_x
                else:
                    explicit_x = 0
                x_positions = [explicit_x]
            elif has_position_hints and count == 1 and not win_pos:
                x_positions = [0]
            else:
                # Generic even spacing
                total_win_width = count * w + (count - 1) * max(0.3, (facade_width - count * w) / (count + 1))
                start_x = -total_win_width / 2 + w / 2
                spacing = (total_win_width - w) / max(1, count - 1) if count > 1 else 0
                x_positions = [start_x + i * spacing if count > 1 else 0 for i in range(count)]

            for i, x in enumerate(x_positions):

                # Skip ground floor windows that overlap with door positions
                if int(floor_idx) == 1 and door_x_positions:
                    overlap = False
                    for dx in door_x_positions:
                        if abs(x - dx) < (w / 2 + 0.3):
                            overlap = True
                            break
                    if overlap:
                        continue

                # Create cutter
                if is_arched:
                    spring_h = h * 0.7
                    cutter = create_arch_cutter(
                        f"win_cut_{floor_idx}_{i}",
                        w, h, spring_h, arch_type=arch_type, depth=0.8
                    )
                else:
                    cutter = create_rect_cutter(f"win_cut_{floor_idx}_{i}", w, h, depth=0.8)
                    cutter.location.z = h / 2

                cutter.location.x = x
                cutter.location.z += sill_h
                cutter.location.y = 0.01  # nudge past front face to avoid coplanar boolean

                boolean_cut(wall_obj, cutter)

                # Add window frame (4 thin boxes forming a rectangle)
                frame_t = 0.04  # frame thickness
                frame_d = 0.06  # frame depth (projection)
                # Per-building frame colour from JSON (some have dark bronze, others white)
                frame_hex = trim_hex
                wf_colour = win_spec.get("frame_colour", win_spec.get("frame_colour_hex", ""))
                if isinstance(wf_colour, str) and wf_colour.startswith("#"):
                    frame_hex = wf_colour
                elif isinstance(wf_colour, str) and "bronze" in wf_colour.lower():
                    frame_hex = "#4A3A2A"
                elif isinstance(wf_colour, str) and "dark" in wf_colour.lower():
                    frame_hex = "#3A3A3A"
                frame_mat = get_or_create_material(f"mat_frame_{frame_hex.lstrip('#')}",
                    colour_hex=frame_hex, roughness=0.5)

                # Top frame
                bpy.ops.mesh.primitive_cube_add(size=1)
                ft = bpy.context.active_object
                ft.name = f"frame_t_{floor_idx}_{i}"
                ft.scale = (w + frame_t, frame_d, frame_t)
                bpy.ops.object.transform_apply(scale=True)
                ft.location = (x, frame_d / 2, sill_h + h)
                assign_material(ft, frame_mat)
                window_objects.append(ft)

                # Bottom frame (sill)
                bpy.ops.mesh.primitive_cube_add(size=1)
                fb = bpy.context.active_object
                fb.name = f"frame_b_{floor_idx}_{i}"
                fb.scale = (w + frame_t * 2, frame_d * 1.5, frame_t)
                bpy.ops.object.transform_apply(scale=True)
                fb.location = (x, frame_d * 0.75, sill_h)
                assign_material(fb, frame_mat)
                window_objects.append(fb)

                # Left frame
                bpy.ops.mesh.primitive_cube_add(size=1)
                fl = bpy.context.active_object
                fl.name = f"frame_l_{floor_idx}_{i}"
                fl.scale = (frame_t, frame_d, h)
                bpy.ops.object.transform_apply(scale=True)
                fl.location = (x - w / 2, frame_d / 2, sill_h + h / 2)
                assign_material(fl, frame_mat)
                window_objects.append(fl)

                # Right frame
                bpy.ops.mesh.primitive_cube_add(size=1)
                fr = bpy.context.active_object
                fr.name = f"frame_r_{floor_idx}_{i}"
                fr.scale = (frame_t, frame_d, h)
                bpy.ops.object.transform_apply(scale=True)
                fr.location = (x + w / 2, frame_d / 2, sill_h + h / 2)
                assign_material(fr, frame_mat)
                window_objects.append(fr)

                # Middle horizontal mullion (for double-hung look)
                bpy.ops.mesh.primitive_cube_add(size=1)
                fm = bpy.context.active_object
                fm.name = f"frame_m_{floor_idx}_{i}"
                fm.scale = (w, frame_d, frame_t * 0.7)
                bpy.ops.object.transform_apply(scale=True)
                fm.location = (x, frame_d / 2, sill_h + h / 2)
                assign_material(fm, frame_mat)
                window_objects.append(fm)

                # Vertical muntin (creates 2-over-2 pane look)
                bpy.ops.mesh.primitive_cube_add(size=1)
                mv = bpy.context.active_object
                mv.name = f"muntin_v_{floor_idx}_{i}"
                mv.scale = (frame_t * 0.5, frame_d, h * 0.92)
                bpy.ops.object.transform_apply(scale=True)
                mv.location = (x, frame_d / 2, sill_h + h / 2)
                assign_material(mv, frame_mat)
                window_objects.append(mv)

                # For wider windows, add a second vertical muntin (3-pane width)
                if w > 1.0:
                    third = w / 3
                    for mi, mx in enumerate([x - third / 2, x + third / 2]):
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        mv2 = bpy.context.active_object
                        mv2.name = f"muntin_v2_{floor_idx}_{i}_{mi}"
                        mv2.scale = (frame_t * 0.5, frame_d, h * 0.92)
                        bpy.ops.object.transform_apply(scale=True)
                        mv2.location = (mx, frame_d / 2, sill_h + h / 2)
                        assign_material(mv2, frame_mat)
                        window_objects.append(mv2)

                # Add glass pane
                bpy.ops.mesh.primitive_plane_add(size=1)
                glass = bpy.context.active_object
                glass.name = f"glass_{floor_idx}_{i}"
                glass.scale = (w * 0.9, 1, h * 0.9)
                bpy.ops.object.transform_apply(scale=True)
                glass.rotation_euler.x = math.pi / 2
                glass.location = (x, 0.02, sill_h + h / 2)

                glass_mat = create_glass_material("mat_glass")
                assign_material(glass, glass_mat)

                window_objects.append(glass)

    return window_objects


def _resolve_doors(params, facade_width):
    """Collect all door specs from params, resolving indirect references."""
    resolved = []

    # 1) Direct doors_detail entries with dimensions
    for door in params.get("doors_detail", []):
        if not isinstance(door, dict):
            continue
        if "width_m" in door:
            # Normalize: some params use height_to_crown_m instead of height_m
            d = dict(door)
            if "height_m" not in d and "height_to_crown_m" in d:
                d["height_m"] = d["height_to_crown_m"]
            # Detect glass from material field
            mat_str = str(d.get("material", "")).lower()
            dtype = str(d.get("type", "")).lower()
            if "glass" in dtype or "alumin" in mat_str or "glass" in mat_str:
                d["is_glass"] = True
            resolved.append(d)

    # 2) Resolve from ground_floor_arches (e.g. 20 Denison Sq)
    arches = params.get("ground_floor_arches", {})
    if isinstance(arches, dict):
        for arch_key in ["left_arch", "right_arch", "centre_arch", "center_arch"]:
            arch = arches.get(arch_key, {})
            if not isinstance(arch, dict):
                continue
            func = str(arch.get("function", "")).lower()
            if func == "entrance" or "door" in str(arch.get("door", {})):
                door_in_arch = arch.get("door", {})
                w = arch.get("total_width_m", 1.0)
                h = arch.get("total_height_m", 2.2)
                # Position: left_arch → left side, right_arch → right side
                if "left" in arch_key:
                    pos = "left"
                elif "right" in arch_key:
                    pos = "right"
                else:
                    pos = "center"
                colour = "dark_brown_stained"
                colour_hex = ""
                if isinstance(door_in_arch, dict):
                    colour = door_in_arch.get("colour", colour)
                    colour_hex = door_in_arch.get("colour_hex", "")
                    w = door_in_arch.get("width_m", w)
                    h = door_in_arch.get("height_m", h)
                resolved.append({
                    "width_m": w,
                    "height_m": h,
                    "position": pos,
                    "type": arch.get("type", "arched"),
                    "colour": colour,
                    "colour_hex": colour_hex,
                    "material": door_in_arch.get("material", "wood") if isinstance(door_in_arch, dict) else "wood",
                    "_source": "ground_floor_arches",
                })

    # 3) Resolve from windows_detail[].entrance (e.g. 21 Nassau St)
    for wd in params.get("windows_detail", []):
        if not isinstance(wd, dict):
            continue
        entrance = wd.get("entrance", {})
        if not isinstance(entrance, dict) or not entrance:
            continue
        w = entrance.get("width_m", 1.0)
        h = entrance.get("height_m", 2.2)
        pos = str(entrance.get("position", "center")).lower()
        etype = str(entrance.get("type", "")).lower()
        frame_col = entrance.get("frame_colour", "")
        frame_hex = entrance.get("frame_colour_hex", "")
        is_glass = "glass" in etype or "aluminum" in str(entrance.get("frame_material", "")).lower()
        d = {
            "width_m": w,
            "height_m": h,
            "position": pos,
            "type": etype,
            "colour": entrance.get("colour", frame_col),
            "colour_hex": frame_hex,
            "frame_colour": frame_col,
            "frame_colour_hex": frame_hex,
            "material": entrance.get("frame_material", "wood"),
            "glazing": entrance.get("glazing", ""),
            "is_glass": is_glass,
            "_source": "windows_detail_entrance",
        }
        # Carry awning data if present
        aw = entrance.get("awning", {})
        if isinstance(aw, dict) and aw.get("present", aw.get("type")):
            d["awning"] = aw
        resolved.append(d)

    # 4) Resolve from storefront entrance (backup for commercial buildings)
    sf = params.get("storefront", {})
    if isinstance(sf, dict):
        sf_ent = sf.get("entrance", {})
        if isinstance(sf_ent, dict) and sf_ent.get("width_m"):
            # Only add if not already captured
            already = any(d.get("_source") == "windows_detail_entrance" for d in resolved)
            if not already:
                resolved.append({
                    "width_m": sf_ent.get("width_m", 0.9),
                    "height_m": sf_ent.get("height_m", 2.1),
                    "position": str(sf_ent.get("position", "left")).lower(),
                    "type": sf_ent.get("type", "commercial_glass"),
                    "colour": sf_ent.get("colour", ""),
                    "colour_hex": sf_ent.get("colour_hex", ""),
                    "material": sf_ent.get("material", "aluminum"),
                    "is_glass": True,
                    "_source": "storefront_entrance",
                })

    # If still no doors resolved, don't fabricate one
    return resolved


def cut_doors(wall_obj, params, facade_width):
    """Cut door openings from the front wall, resolving from all param sources."""
    doors = _resolve_doors(params, facade_width)
    door_objects = []

    for i, door in enumerate(doors):
        w = door.get("width_m", 0.9)
        h = door.get("height_m", 2.2)

        # Determine x position
        pos = str(door.get("position", "center")).lower()
        if "left" in pos:
            x = -facade_width / 4
        elif "right" in pos:
            x = facade_width / 4
        else:
            x = 0

        # Check if arched — check type and arch_head fields
        door_type = str(door.get("type", "")).lower()
        arch_head = str(door.get("arch_head", "")).lower()
        is_arched = "arch" in door_type or "semicircular" in door_type or \
                    "arch" in arch_head or "segmental" in arch_head or "pointed" in arch_head
        is_glass = door.get("is_glass", False) or "glass" in door_type or "aluminum" in str(door.get("material", "")).lower()
        is_rolling = "rolling" in door_type or "shutter" in door_type
        is_double = "double" in door_type

        # Cut opening
        if is_arched:
            cutter = create_arch_cutter(f"door_cut_{i}", w, h, h * 0.7, depth=0.8)
        else:
            cutter = create_rect_cutter(f"door_cut_{i}", w, h, depth=0.8)
            cutter.location.z = h / 2

        cutter.location.x = x
        cutter.location.y = 0.01
        boolean_cut(wall_obj, cutter)

        # Determine door colour
        door_hex = door.get("colour_hex", "")
        if not door_hex or not door_hex.startswith("#"):
            col_name = str(door.get("colour", "")).lower().replace(" ", "_")
            if col_name:
                door_hex = colour_name_to_hex(col_name)
            else:
                door_hex = "#5A3A2A"

        # Frame colour
        frame_hex = door.get("frame_colour_hex", "")
        if not frame_hex or not frame_hex.startswith("#"):
            fc = str(door.get("frame_colour", "")).lower().replace(" ", "_")
            if fc and "bronze" in fc:
                frame_hex = "#4A3A2A"
            elif fc and "white" in fc:
                frame_hex = "#F0F0F0"
            elif fc:
                frame_hex = colour_name_to_hex(fc)
            elif is_glass:
                frame_hex = "#3A3A3A"
            else:
                frame_hex = "#F0F0F0"

        # --- Create door panel ---
        if is_glass:
            # Glass door — translucent panel
            glass_mat_name = f"mat_glass_door_{i}"
            if glass_mat_name not in bpy.data.materials:
                gm = bpy.data.materials.new(name=glass_mat_name)
                gm.blend_method = 'BLEND' if hasattr(gm, 'blend_method') else None
                gbsdf = gm.node_tree.nodes.get("Principled BSDF")
                if gbsdf:
                    gbsdf.inputs["Base Color"].default_value = (0.7, 0.8, 0.85, 1.0)
                    gbsdf.inputs["Roughness"].default_value = 0.05
                    if "Alpha" in gbsdf.inputs:
                        gbsdf.inputs["Alpha"].default_value = 0.3
                    if "Transmission Weight" in gbsdf.inputs:
                        gbsdf.inputs["Transmission Weight"].default_value = 0.8
                    elif "Transmission" in gbsdf.inputs:
                        gbsdf.inputs["Transmission"].default_value = 0.8
            else:
                gm = bpy.data.materials[glass_mat_name]

            bpy.ops.mesh.primitive_cube_add(size=1)
            dp = bpy.context.active_object
            dp.name = f"door_glass_{i}"
            dp.scale = (w * 0.92, 0.03, h * 0.92)
            bpy.ops.object.transform_apply(scale=True)
            dp.location = (x, 0.02, h * 0.92 / 2 + 0.05)
            assign_material(dp, gm)
            door_objects.append(dp)

            # Aluminum/metal frame bars
            frame_mat = get_or_create_material(f"mat_door_frame_{i}", colour_hex=frame_hex, roughness=0.3)
            # Centre mullion for double doors
            if is_double:
                bpy.ops.mesh.primitive_cube_add(size=1)
                cm = bpy.context.active_object
                cm.name = f"door_mullion_{i}"
                cm.scale = (0.04, 0.05, h * 0.92)
                bpy.ops.object.transform_apply(scale=True)
                cm.location = (x, 0.01, h * 0.92 / 2 + 0.05)
                assign_material(cm, frame_mat)
                door_objects.append(cm)

            # Side frames
            for side_x, fname in [(x - w / 2, "left"), (x + w / 2, "right")]:
                bpy.ops.mesh.primitive_cube_add(size=1)
                df = bpy.context.active_object
                df.name = f"door_frame_{fname}_{i}"
                df.scale = (0.04, 0.06, h)
                bpy.ops.object.transform_apply(scale=True)
                df.location = (side_x, 0.02, h / 2)
                assign_material(df, frame_mat)
                door_objects.append(df)

            # Top frame
            bpy.ops.mesh.primitive_cube_add(size=1)
            dh = bpy.context.active_object
            dh.name = f"door_header_{i}"
            dh.scale = (w + 0.08, 0.06, 0.04)
            bpy.ops.object.transform_apply(scale=True)
            dh.location = (x, 0.02, h + 0.02)
            assign_material(dh, frame_mat)
            door_objects.append(dh)

        elif is_rolling:
            # Rolling shutter door (fire station style)
            door_mat = get_or_create_material(f"mat_door_{i}", colour_hex=door_hex, roughness=0.4)
            # Horizontal slat pattern — stack thin panels
            slat_h = 0.08
            slat_count = int(h / slat_h)
            for si in range(slat_count):
                bpy.ops.mesh.primitive_cube_add(size=1)
                slat = bpy.context.active_object
                slat.name = f"door_slat_{i}_{si}"
                slat.scale = (w * 0.95, 0.04, slat_h * 0.85)
                bpy.ops.object.transform_apply(scale=True)
                slat.location = (x, 0.02, slat_h * si + slat_h / 2 + 0.05)
                assign_material(slat, door_mat)
                door_objects.append(slat)

        else:
            # Solid wood/painted door panel
            door_mat = get_or_create_material(f"mat_door_{i}", colour_hex=door_hex, roughness=0.6)
            panel_w = w * 0.9
            panel_h = h * 0.95
            bpy.ops.mesh.primitive_cube_add(size=1)
            dp = bpy.context.active_object
            dp.name = f"door_panel_{i}"
            dp.scale = (panel_w, 0.06, panel_h)
            bpy.ops.object.transform_apply(scale=True)
            dp.location = (x, 0.02, panel_h / 2)
            assign_material(dp, door_mat)
            door_objects.append(dp)

            # Raised panels — two stacked rectangular raised panels on door face
            panel_trim_mat = get_or_create_material(f"mat_door_trim_{i}", colour_hex=frame_hex, roughness=0.5)
            rpw = panel_w * 0.7  # raised panel width
            rp_gap = 0.08  # gap between panels
            # Bottom panel (taller)
            rp_bot_h = panel_h * 0.45
            bpy.ops.mesh.primitive_cube_add(size=1)
            rp1 = bpy.context.active_object
            rp1.name = f"door_rpanel_bot_{i}"
            rp1.scale = (rpw, 0.015, rp_bot_h)
            bpy.ops.object.transform_apply(scale=True)
            rp1.location = (x, 0.05, 0.1 + rp_bot_h / 2)
            assign_material(rp1, door_mat)
            door_objects.append(rp1)
            # Top panel (shorter)
            rp_top_h = panel_h * 0.35
            rp_top_z = 0.1 + rp_bot_h + rp_gap + rp_top_h / 2
            bpy.ops.mesh.primitive_cube_add(size=1)
            rp2 = bpy.context.active_object
            rp2.name = f"door_rpanel_top_{i}"
            rp2.scale = (rpw, 0.015, rp_top_h)
            bpy.ops.object.transform_apply(scale=True)
            rp2.location = (x, 0.05, rp_top_z)
            assign_material(rp2, door_mat)
            door_objects.append(rp2)

            # Door handle/knob
            handle_side = 1 if not is_double else 0
            hx = x + (panel_w / 2 - 0.08) * (1 if handle_side else -1)
            bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=0.03, vertices=12)
            knob = bpy.context.active_object
            knob.name = f"door_knob_{i}"
            knob.rotation_euler.x = math.pi / 2
            knob.location = (hx, 0.06, h * 0.45)
            knob_mat = get_or_create_material("mat_door_knob", colour_hex="#C0A060", roughness=0.3)
            assign_material(knob, knob_mat)
            door_objects.append(knob)

            # Centre mullion for double doors
            if is_double or w > 1.2:
                bpy.ops.mesh.primitive_cube_add(size=1)
                sp = bpy.context.active_object
                sp.name = f"door_split_{i}"
                sp.scale = (0.02, 0.065, h * 0.9)
                bpy.ops.object.transform_apply(scale=True)
                sp.location = (x, 0.025, h * 0.9 / 2 + 0.02)
                assign_material(sp, panel_trim_mat)
                door_objects.append(sp)

            # Frame surround
            frame_mat = get_or_create_material(f"mat_door_frame_{i}", colour_hex=frame_hex, roughness=0.5)
            for side_x, fname in [(x - w / 2, "left"), (x + w / 2, "right")]:
                bpy.ops.mesh.primitive_cube_add(size=1)
                df = bpy.context.active_object
                df.name = f"door_frame_{fname}_{i}"
                df.scale = (0.05, 0.08, h)
                bpy.ops.object.transform_apply(scale=True)
                df.location = (side_x, 0.04, h / 2)
                assign_material(df, frame_mat)
                door_objects.append(df)

            # Door header / lintel
            bpy.ops.mesh.primitive_cube_add(size=1)
            dh = bpy.context.active_object
            dh.name = f"door_header_{i}"
            dh.scale = (w + 0.1, 0.08, 0.06)
            bpy.ops.object.transform_apply(scale=True)
            dh.location = (x, 0.04, h + 0.03)
            assign_material(dh, frame_mat)
            door_objects.append(dh)

            # Threshold / sill
            bpy.ops.mesh.primitive_cube_add(size=1)
            thr = bpy.context.active_object
            thr.name = f"door_threshold_{i}"
            thr.scale = (w, 0.12, 0.03)
            bpy.ops.object.transform_apply(scale=True)
            thr.location = (x, 0.04, 0.015)
            assign_material(thr, frame_mat)
            door_objects.append(thr)

        # Awning / canopy over door (from any door type)
        aw = door.get("awning", {})
        if isinstance(aw, dict) and aw.get("present", aw.get("type")):
            aw_w = aw.get("width_m", w + 0.5)
            aw_proj = aw.get("projection_m", 1.2)
            aw_z = aw.get("height_above_grade_m", h + 0.3)
            aw_hex = aw.get("colour_hex", "")
            if not aw_hex or not aw_hex.startswith("#"):
                aw_hex = colour_name_to_hex(str(aw.get("colour", "dark_grey")))
            aw_mat = get_or_create_material(f"mat_awning_{i}", colour_hex=aw_hex, roughness=0.6)
            bpy.ops.mesh.primitive_cube_add(size=1)
            canopy = bpy.context.active_object
            canopy.name = f"door_awning_{i}"
            canopy.scale = (aw_w, aw_proj, 0.05)
            bpy.ops.object.transform_apply(scale=True)
            canopy.location = (x, aw_proj / 2, aw_z)
            assign_material(canopy, aw_mat)
            door_objects.append(canopy)

    return door_objects


def create_gable_walls(params, wall_h, width, depth, bldg_id=""):
    """Create triangular gable walls to fill the gap between wall top and roof."""
    pitch = params.get("roof_pitch_deg", 35)
    pitch_rad = math.radians(pitch)
    ridge_height = (width / 2) * math.tan(pitch_rad)

    facade_hex = get_facade_hex(params)
    hex_id = facade_hex.lstrip('#')
    mat_type = str(params.get("facade_material", "brick")).lower()
    if "brick" in mat_type:
        mat = create_brick_material(f"mat_brick_{hex_id}", facade_hex)
    elif "stone" in mat_type or "concrete" in mat_type:
        mat = create_stone_material(f"mat_stone_{hex_id}", facade_hex)
    elif (
        "paint" in mat_type
        or "stucco" in mat_type
        or "clapboard" in mat_type
        or "wood" in mat_type
        or "vinyl" in mat_type
        or "siding" in mat_type
    ):
        mat = create_painted_material(f"mat_painted_{hex_id}", facade_hex)
    else:
        mat = create_brick_material(f"mat_facade_{hex_id}", facade_hex)

    objects = []
    wall_t = 0.3
    half_w = width / 2

    # Walls go from y=0 (front) to y=-depth (back)
    # Gable is a single triangle face + solidify, positioned flush with wall exterior
    for y_pos, solidify_offset, name in [(0, 1, "gable_front"), (-depth, -1, "gable_back")]:
        bm = bmesh.new()
        v0 = bm.verts.new((-half_w, 0, wall_h))
        v1 = bm.verts.new((half_w, 0, wall_h))
        v2 = bm.verts.new((0, 0, wall_h + ridge_height))
        bm.faces.new([v0, v1, v2])

        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        obj.location.y = y_pos

        # Solidify inward (toward building interior)
        mod = obj.modifiers.new("Solidify", 'SOLIDIFY')
        mod.thickness = wall_t
        mod.offset = solidify_offset
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)

        assign_material(obj, mat)
        objects.append(obj)

    return objects


def create_gable_roof(params, wall_h, width, depth):
    """Create a gable roof."""
    pitch = params.get("roof_pitch_deg", 35)
    pitch_rad = math.radians(pitch)

    ridge_height = (width / 2) * math.tan(pitch_rad)

    roof_hex = get_roof_hex(params)

    bm = bmesh.new()

    # Per-building eave overhang from params
    rd = params.get("roof_detail", {})
    eave_mm = 300
    if isinstance(rd, dict):
        eave_mm = rd.get("eave_overhang_mm", 300)
    else:
        eave_mm = params.get("eave_overhang_mm", 300)
    overhang_eave = eave_mm / 1000.0
    overhang_side = overhang_eave * 0.5
    half_w = width / 2 + overhang_side
    roof_thick = 0.08

    # Walls go from y=0 (front) to y=-depth (back)
    # Roof extends with overhang beyond both ends
    y_front = overhang_eave
    y_back = -depth - overhang_eave

    # Outer roof surface
    v0 = bm.verts.new((-half_w, y_back, wall_h))
    v1 = bm.verts.new((half_w, y_back, wall_h))
    v2 = bm.verts.new((half_w, y_front, wall_h))
    v3 = bm.verts.new((-half_w, y_front, wall_h))
    v4 = bm.verts.new((0, y_back, wall_h + ridge_height))
    v5 = bm.verts.new((0, y_front, wall_h + ridge_height))

    # Left slope
    bm.faces.new([v0, v3, v5, v4])
    # Right slope
    bm.faces.new([v1, v4, v5, v2])
    # Front gable triangle (roof underside visible)
    bm.faces.new([v0, v4, v1])
    # Back gable triangle
    bm.faces.new([v2, v5, v3])

    mesh = bpy.data.meshes.new("roof")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new("roof", mesh)
    bpy.context.collection.objects.link(obj)

    # Give the roof some thickness via solidify
    mod = obj.modifiers.new("Solidify", 'SOLIDIFY')
    mod.thickness = roof_thick
    mod.offset = -1
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)

    mat = create_roof_material(f"mat_roof_{roof_hex.lstrip('#')}", roof_hex)
    assign_material(obj, mat)

    return obj, ridge_height


def create_cross_gable_roof(params, wall_h, width, depth):
    """Create a cross-gable roof for bay-and-gable buildings.

    Main roof: side gable (ridge runs left-right, parallel to facade).
    Secondary: front-facing cross-gable projecting forward from main roof.
    """
    pitch = params.get("roof_pitch_deg", 35)
    pitch_rad = math.radians(pitch)

    roof_hex = get_roof_hex(params)
    roof_thick = 0.08

    rd = params.get("roof_detail", {})
    eave_mm = 300
    if isinstance(rd, dict):
        eave_mm = rd.get("eave_overhang_mm", 300)
    else:
        eave_mm = params.get("eave_overhang_mm", 300)
    overhang = eave_mm / 1000.0

    # --- Main side gable (ridge parallel to facade, runs left-right) ---
    # Ridge height governed by width (shorter facade dimension), not depth.
    # Using depth would produce absurd heights on deep lots (e.g. 32m * tan(45°) = 16m).
    main_ridge_height = (width / 2) * math.tan(pitch_rad)
    half_w = width / 2 + overhang * 0.5
    y_front = overhang
    y_back = -depth - overhang
    y_mid = -depth / 2  # ridge runs along this Y at wall_h + main_ridge_height

    bm = bmesh.new()

    # Main roof: 4 verts at eaves, 2 at ridge
    m0 = bm.verts.new((-half_w, y_front, wall_h))   # front-left
    m1 = bm.verts.new((half_w, y_front, wall_h))     # front-right
    m2 = bm.verts.new((half_w, y_back, wall_h))      # back-right
    m3 = bm.verts.new((-half_w, y_back, wall_h))     # back-left
    m4 = bm.verts.new((-half_w, y_mid, wall_h + main_ridge_height))  # ridge-left
    m5 = bm.verts.new((half_w, y_mid, wall_h + main_ridge_height))   # ridge-right

    # Front slope
    bm.faces.new([m0, m1, m5, m4])
    # Back slope
    bm.faces.new([m2, m3, m4, m5])
    # Left gable triangle
    bm.faces.new([m3, m0, m4])
    # Right gable triangle
    bm.faces.new([m1, m2, m5])

    mesh_main = bpy.data.meshes.new("roof_main")
    bm.to_mesh(mesh_main)
    bm.free()

    obj_main = bpy.data.objects.new("roof_main", mesh_main)
    bpy.context.collection.objects.link(obj_main)

    mod = obj_main.modifiers.new("Solidify", 'SOLIDIFY')
    mod.thickness = roof_thick
    mod.offset = -1
    bpy.context.view_layer.objects.active = obj_main
    bpy.ops.object.modifier_apply(modifier=mod.name)

    mat = create_roof_material(f"mat_roof_{roof_hex.lstrip('#')}", roof_hex)
    assign_material(obj_main, mat)

    # --- Secondary cross-gable (front-facing, projects forward) ---
    cross_w = width * 0.5  # roughly half facade width
    cross_ridge_height = (cross_w / 2) * math.tan(pitch_rad)
    # Ensure cross ridge meets or slightly exceeds main ridge
    if cross_ridge_height < main_ridge_height:
        cross_ridge_height = main_ridge_height * 1.05

    # Cross-gable sits on the left side (above bay window area)
    cx_center = -width / 4  # left quarter of facade
    cx_half = cross_w / 2 + overhang * 0.5
    # Depth: from front of building to the main ridge line
    cy_front = overhang
    cy_back = y_mid  # meets main ridge

    bm2 = bmesh.new()

    c0 = bm2.verts.new((cx_center - cx_half, cy_front, wall_h))   # front-left
    c1 = bm2.verts.new((cx_center + cx_half, cy_front, wall_h))   # front-right
    c2 = bm2.verts.new((cx_center + cx_half, cy_back, wall_h))    # back-right
    c3 = bm2.verts.new((cx_center - cx_half, cy_back, wall_h))    # back-left
    c4 = bm2.verts.new((cx_center, cy_front, wall_h + cross_ridge_height))  # ridge-front
    c5 = bm2.verts.new((cx_center, cy_back, wall_h + cross_ridge_height))   # ridge-back

    # Left slope
    bm2.faces.new([c3, c0, c4, c5])
    # Right slope
    bm2.faces.new([c1, c2, c5, c4])
    # Front gable triangle
    bm2.faces.new([c0, c1, c4])
    # Back triangle (mostly hidden by main roof)
    bm2.faces.new([c2, c3, c5])

    mesh_cross = bpy.data.meshes.new("roof_cross_gable")
    bm2.to_mesh(mesh_cross)
    bm2.free()

    obj_cross = bpy.data.objects.new("roof_cross_gable", mesh_cross)
    bpy.context.collection.objects.link(obj_cross)

    mod2 = obj_cross.modifiers.new("Solidify", 'SOLIDIFY')
    mod2.thickness = roof_thick
    mod2.offset = -1
    bpy.context.view_layer.objects.active = obj_cross
    bpy.ops.object.modifier_apply(modifier=mod2.name)

    assign_material(obj_cross, mat)

    # Join cross-gable into main roof object
    bpy.context.view_layer.objects.active = obj_main
    obj_main.select_set(True)
    obj_cross.select_set(True)
    bpy.ops.object.join()

    ridge_height = max(main_ridge_height, cross_ridge_height)
    return obj_main, ridge_height


def create_hip_roof(params, wall_h, width, depth):
    """Create a hip roof."""
    pitch = params.get("roof_pitch_deg", 25)
    if pitch < 5:
        pitch = 25  # sensible default for hip roofs with missing/zero pitch
    pitch_rad = math.radians(pitch)

    hip_height = min(width, depth) / 2 * math.tan(pitch_rad)
    ridge_len = abs(depth - width) / 2

    roof_hex = get_roof_hex(params)

    bm = bmesh.new()

    rd = params.get("roof_detail", {})
    eave_mm = 300
    if isinstance(rd, dict):
        eave_mm = rd.get("eave_overhang_mm", 300)
    else:
        eave_mm = params.get("eave_overhang_mm", 300)
    overhang = eave_mm / 1000.0
    hw = width / 2 + overhang

    # Walls go from y=0 (front) to y=-depth (back)
    y_front = overhang
    y_back = -depth - overhang
    y_mid = -depth / 2  # center of the building

    # Base corners
    v0 = bm.verts.new((-hw, y_back, wall_h))
    v1 = bm.verts.new((hw, y_back, wall_h))
    v2 = bm.verts.new((hw, y_front, wall_h))
    v3 = bm.verts.new((-hw, y_front, wall_h))

    if ridge_len > 0.1:
        # Ridge line centered on building
        v4 = bm.verts.new((0, y_mid - ridge_len, wall_h + hip_height))
        v5 = bm.verts.new((0, y_mid + ridge_len, wall_h + hip_height))

        bm.faces.new([v0, v4, v1])  # back hip
        bm.faces.new([v0, v3, v5, v4])  # left slope
        bm.faces.new([v1, v4, v5, v2])  # right slope
        bm.faces.new([v2, v5, v3])  # front hip
    else:
        # Pyramid
        v4 = bm.verts.new((0, y_mid, wall_h + hip_height))
        bm.faces.new([v0, v4, v1])
        bm.faces.new([v1, v4, v2])
        bm.faces.new([v2, v4, v3])
        bm.faces.new([v3, v4, v0])

    mesh = bpy.data.meshes.new("roof_hip")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new("roof", mesh)
    bpy.context.collection.objects.link(obj)

    mat = create_roof_material(f"mat_roof_{roof_hex.lstrip('#')}", roof_hex)
    assign_material(obj, mat)

    return obj, hip_height


def create_flat_roof(params, wall_h, width, depth):
    """Create a flat roof with parapet."""
    parapet_h = 0.3
    cornice = params.get("cornice", {})
    if isinstance(cornice, dict):
        parapet_h = cornice.get("height_mm", 300) / 1000

    bpy.ops.mesh.primitive_plane_add(size=1)
    roof = bpy.context.active_object
    roof.name = "roof_flat"
    roof.scale = (width + 0.1, depth + 0.1, 1)
    bpy.ops.object.transform_apply(scale=True)
    # Walls go from y=0 to y=-depth, center at y=-depth/2
    roof.location = (0, -depth / 2, wall_h + 0.01)

    roof_hex = get_roof_hex(params)
    mat = create_roof_material(f"mat_roof_{roof_hex.lstrip('#')}", roof_hex)
    assign_material(roof, mat)

    return roof, parapet_h


def create_porch(params, facade_width):
    """Create a front porch with posts and optional roof."""
    porch_data = params.get("porch", {})
    if not isinstance(porch_data, dict):
        return []
    if not porch_data.get("present", porch_data.get("type")):
        return []

    porch_w = porch_data.get("width_m", facade_width)
    porch_d = porch_data.get("depth_m", 2.0)
    porch_h = porch_data.get("height_m", 2.8)
    floor_h = porch_data.get("floor_height_above_grade_m",
              porch_data.get("deck_height_above_sidewalk_m", 0.5))

    objects = []

    # Porch floor/deck
    bpy.ops.mesh.primitive_cube_add(size=1)
    deck = bpy.context.active_object
    deck.name = "porch_deck"
    deck.scale = (porch_w, porch_d, 0.1)
    bpy.ops.object.transform_apply(scale=True)
    deck.location = (0, porch_d / 2, floor_h)

    wood_mat = create_wood_material("mat_wood", "#8B7355")
    assign_material(deck, wood_mat)
    objects.append(deck)

    # Posts
    posts_data = porch_data.get("posts", {})
    post_count = posts_data.get("count", 4) if isinstance(posts_data, dict) else 4
    post_colour = "#3A2A20"
    if isinstance(posts_data, dict):
        post_colour = posts_data.get("colour_hex", "#3A2A20")

    post_mat = get_or_create_material("mat_post", colour_hex=post_colour, roughness=0.6)

    # Porch beam (placed first so we know its z)
    beam_h = 0.12
    beam_z = porch_h
    bpy.ops.mesh.primitive_cube_add(size=1)
    beam = bpy.context.active_object
    beam.name = "porch_beam"
    beam.scale = (porch_w + 0.1, 0.1, beam_h)
    bpy.ops.object.transform_apply(scale=True)
    beam.location = (0, porch_d, beam_z)
    assign_material(beam, post_mat)
    objects.append(beam)

    # Posts — extend into beam to close gap
    post_h = porch_h - floor_h + beam_h / 2 + 0.06
    for i in range(post_count):
        x = -porch_w / 2 + (porch_w / max(1, post_count - 1)) * i if post_count > 1 else 0

        bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=post_h)
        post = bpy.context.active_object
        post.name = f"porch_post_{i}"
        post.location = (x, porch_d, floor_h + post_h / 2)
        assign_material(post, post_mat)
        objects.append(post)

    # Porch roof (simple shed)
    bpy.ops.mesh.primitive_cube_add(size=1)
    proofroof = bpy.context.active_object
    proofroof.name = "porch_roof"
    proofroof.scale = (porch_w + 0.2, porch_d + 0.3, 0.08)
    bpy.ops.object.transform_apply(scale=True)
    proofroof.location = (0, porch_d / 2, beam_z + beam_h / 2 + 0.04)

    roof_mat = get_or_create_material("mat_roof_2E2E2E", colour_hex="#2E2E2E", roughness=0.9)
    assign_material(proofroof, roof_mat)
    objects.append(proofroof)

    # Steps — compute step position/width for railing gap calculation
    steps_data = porch_data.get("steps", porch_data.get("stairs", {}))
    step_w = 1.2
    step_x = 0.0
    step_count = 3
    run = 0.28
    if isinstance(steps_data, dict):
        step_count = steps_data.get("count", steps_data.get("rise_count", 3))
        step_w = steps_data.get("width_m", 1.2)
        step_pos = str(steps_data.get("position", "center")).lower()
        if "left" in step_pos:
            step_x = -porch_w / 4
        elif "right" in step_pos:
            step_x = porch_w / 4
        rise = floor_h / max(1, step_count)
        run = 0.28

        for s in range(step_count):
            bpy.ops.mesh.primitive_cube_add(size=1)
            step = bpy.context.active_object
            step.name = f"step_{s}"
            step.scale = (step_w, run, rise)
            bpy.ops.object.transform_apply(scale=True)
            step.location = (step_x, porch_d + run * (s + 0.5), rise * (step_count - s - 0.5))
            step_mat = get_or_create_material("mat_concrete", colour_hex="#A0A0A0", roughness=0.9)
            assign_material(step, step_mat)
            objects.append(step)

    # Railing — front with entry gap, plus both sides
    railing_data = porch_data.get("railing", {})
    if isinstance(railing_data, dict) and railing_data.get("present", True):
        rail_h = railing_data.get("height_mm", 800) / 1000 if isinstance(railing_data.get("height_mm"), (int, float)) else 0.8
        rail_z = floor_h + rail_h

        # Entry gap in front railing (where steps are)
        gap_left = step_x - step_w / 2 - 0.05
        gap_right = step_x + step_w / 2 + 0.05

        # Front railing — LEFT section (from left edge to gap)
        left_rail_w = gap_left - (-porch_w / 2)
        if left_rail_w > 0.2:
            left_rail_cx = (-porch_w / 2 + gap_left) / 2
            bpy.ops.mesh.primitive_cube_add(size=1)
            rl = bpy.context.active_object
            rl.name = "rail_front_left"
            rl.scale = (left_rail_w, 0.04, 0.04)
            bpy.ops.object.transform_apply(scale=True)
            rl.location = (left_rail_cx, porch_d, rail_z)
            assign_material(rl, post_mat)
            objects.append(rl)

            # Bottom rail
            bpy.ops.mesh.primitive_cube_add(size=1)
            rbl = bpy.context.active_object
            rbl.name = "rail_front_left_bot"
            rbl.scale = (left_rail_w, 0.04, 0.03)
            bpy.ops.object.transform_apply(scale=True)
            rbl.location = (left_rail_cx, porch_d, floor_h + 0.05)
            assign_material(rbl, post_mat)
            objects.append(rbl)

            # Balusters for left section
            bal_count = max(1, int(left_rail_w / 0.12))
            for bi in range(bal_count):
                bx = -porch_w / 2 + (left_rail_w / bal_count) * (bi + 0.5)
                bpy.ops.mesh.primitive_cube_add(size=1)
                bal = bpy.context.active_object
                bal.name = f"bal_fl_{bi}"
                bal.scale = (0.025, 0.025, rail_h - 0.08)
                bpy.ops.object.transform_apply(scale=True)
                bal.location = (bx, porch_d, floor_h + (rail_h - 0.08) / 2 + 0.04)
                assign_material(bal, post_mat)
                objects.append(bal)

        # Front railing — RIGHT section (from gap to right edge)
        right_rail_w = porch_w / 2 - gap_right
        if right_rail_w > 0.2:
            right_rail_cx = (gap_right + porch_w / 2) / 2
            bpy.ops.mesh.primitive_cube_add(size=1)
            rr = bpy.context.active_object
            rr.name = "rail_front_right"
            rr.scale = (right_rail_w, 0.04, 0.04)
            bpy.ops.object.transform_apply(scale=True)
            rr.location = (right_rail_cx, porch_d, rail_z)
            assign_material(rr, post_mat)
            objects.append(rr)

            # Bottom rail
            bpy.ops.mesh.primitive_cube_add(size=1)
            rbr = bpy.context.active_object
            rbr.name = "rail_front_right_bot"
            rbr.scale = (right_rail_w, 0.04, 0.03)
            bpy.ops.object.transform_apply(scale=True)
            rbr.location = (right_rail_cx, porch_d, floor_h + 0.05)
            assign_material(rbr, post_mat)
            objects.append(rbr)

            # Balusters for right section
            bal_count = max(1, int(right_rail_w / 0.12))
            for bi in range(bal_count):
                bx = gap_right + (right_rail_w / bal_count) * (bi + 0.5)
                bpy.ops.mesh.primitive_cube_add(size=1)
                bal = bpy.context.active_object
                bal.name = f"bal_fr_{bi}"
                bal.scale = (0.025, 0.025, rail_h - 0.08)
                bpy.ops.object.transform_apply(scale=True)
                bal.location = (bx, porch_d, floor_h + (rail_h - 0.08) / 2 + 0.04)
                assign_material(bal, post_mat)
                objects.append(bal)

        # SIDE railings (left and right edges of porch)
        side_rail_len = porch_d - 0.1  # slightly shorter than porch depth
        for side_name, sx in [("left", -porch_w / 2), ("right", porch_w / 2)]:
            # Top rail
            bpy.ops.mesh.primitive_cube_add(size=1)
            sr = bpy.context.active_object
            sr.name = f"rail_side_{side_name}"
            sr.scale = (0.04, side_rail_len, 0.04)
            bpy.ops.object.transform_apply(scale=True)
            sr.location = (sx, porch_d / 2 + 0.05, rail_z)
            assign_material(sr, post_mat)
            objects.append(sr)

            # Bottom rail
            bpy.ops.mesh.primitive_cube_add(size=1)
            srb = bpy.context.active_object
            srb.name = f"rail_side_{side_name}_bot"
            srb.scale = (0.04, side_rail_len, 0.03)
            bpy.ops.object.transform_apply(scale=True)
            srb.location = (sx, porch_d / 2 + 0.05, floor_h + 0.05)
            assign_material(srb, post_mat)
            objects.append(srb)

            # Side balusters
            side_bal_count = max(1, int(side_rail_len / 0.12))
            for bi in range(side_bal_count):
                by = 0.1 + (side_rail_len / side_bal_count) * (bi + 0.5)
                bpy.ops.mesh.primitive_cube_add(size=1)
                sbal = bpy.context.active_object
                sbal.name = f"bal_s{side_name}_{bi}"
                sbal.scale = (0.025, 0.025, rail_h - 0.08)
                bpy.ops.object.transform_apply(scale=True)
                sbal.location = (sx, by, floor_h + (rail_h - 0.08) / 2 + 0.04)
                assign_material(sbal, post_mat)
                objects.append(sbal)

    # Brick piers at porch corners
    piers = porch_data.get("brick_piers", {})
    if isinstance(piers, dict) and piers.get("present", False):
        pier_w = piers.get("width_m", 0.4)
        pier_h = piers.get("height_m", 0.8)
        pier_count = piers.get("count", 2)
        pier_mat = create_brick_material("mat_pier_brick",
                                          get_facade_hex(params))
        for pi in range(pier_count):
            if pier_count == 2:
                px = (-porch_w / 2 + pier_w / 2) if pi == 0 else (porch_w / 2 - pier_w / 2)
            else:
                px = -porch_w / 2 + (porch_w / max(1, pier_count - 1)) * pi
            bpy.ops.mesh.primitive_cube_add(size=1)
            pier = bpy.context.active_object
            pier.name = f"brick_pier_{pi}"
            pier.scale = (pier_w, pier_w, pier_h)
            bpy.ops.object.transform_apply(scale=True)
            pier.location = (px, porch_d, pier_h / 2)
            assign_material(pier, pier_mat)
            objects.append(pier)
            # Stone cap on pier
            cap_hex = piers.get("cap_hex", "#C8B88A")
            cap_mat = get_or_create_material("mat_pier_cap", colour_hex=cap_hex, roughness=0.5)
            bpy.ops.mesh.primitive_cube_add(size=1)
            cap = bpy.context.active_object
            cap.name = f"pier_cap_{pi}"
            cap.scale = (pier_w + 0.04, pier_w + 0.04, 0.05)
            bpy.ops.object.transform_apply(scale=True)
            cap.location = (px, porch_d, pier_h + 0.025)
            assign_material(cap, cap_mat)
            objects.append(cap)

    return objects


def create_chimney(params, wall_h, ridge_height, width):
    """Create chimneys based on roof detail."""
    roof_detail = params.get("roof_detail", {})
    chimney_data = None

    if isinstance(roof_detail, dict):
        chimney_data = roof_detail.get("chimneys", {})

    if not chimney_data or not isinstance(chimney_data, dict):
        # Check roof_features
        features = params.get("roof_features", [])
        if any("chimney" in str(f).lower() for f in features):
            chimney_data = {"count": 1}
        else:
            return []

    count = chimney_data.get("count", 0)
    if count == 0:
        return []

    objects = []
    # Use facade brick colour for chimneys
    facade_hex = get_facade_hex(params)
    brick_mat = get_or_create_material("mat_chimney_brick", colour_hex=facade_hex, roughness=0.85)

    hw = width / 2
    depth = params.get("facade_depth_m", DEFAULT_DEPTH)

    for key in ["left_chimney", "right_chimney"]:
        ch = chimney_data.get(key, {})
        if not isinstance(ch, dict):
            continue

        ch_w = ch.get("width_m", 0.5)
        ch_d = ch.get("depth_m", 0.4)
        above = ch.get("height_above_ridge_m", 1.0)

        pos = str(ch.get("position", key)).lower()

        # X position: party wall chimneys sit at the building edge
        if "left" in pos:
            x = -hw + ch_w / 2
        elif "right" in pos:
            x = hw - ch_w / 2
        else:
            x = 0

        # Chimney extends from partway down the wall up above the ridge
        # Start below eave line so it looks embedded in the roof
        ch_bottom = wall_h * 0.6
        ch_top = wall_h + ridge_height + above
        ch_h = ch_top - ch_bottom

        # Y position: centered on building depth (near ridge for gable roofs)
        # For front-gable buildings, ridge runs front-to-back, chimneys at sides
        ch_y = -depth * 0.3  # slightly toward front

        bpy.ops.mesh.primitive_cube_add(size=1)
        chimney = bpy.context.active_object
        chimney.name = f"chimney_{key}"
        chimney.scale = (ch_w, ch_d, ch_h)
        bpy.ops.object.transform_apply(scale=True)
        chimney.location = (x, ch_y, ch_bottom + ch_h / 2)
        assign_material(chimney, brick_mat)
        objects.append(chimney)

    return objects


def create_bay_window(params, wall_h, facade_width):
    """Create bay window projection if specified.

    Supports top-level bay_window key, canted (3-sided) geometry,
    double-height bays via floors_spanned, and position offsets.
    """
    floor_heights = params.get("floor_heights_m", [3.0, 3.0])
    objects = []

    # --- Collect bay specs from two sources ---
    bay_specs = []  # list of (bay_dict, floor_idx)

    # Source 1: top-level bay_window key
    top_bay = params.get("bay_window", {})
    if isinstance(top_bay, dict) and top_bay.get("present", False):
        floor_idx = top_bay.get("floor", 1)
        bay_specs.append((top_bay, floor_idx))

    # Source 2: windows_detail entries (existing behavior)
    windows_detail = params.get("windows_detail", [])
    for floor_data in windows_detail:
        if not isinstance(floor_data, dict):
            continue
        bay = floor_data.get("bay_window", {})
        if not isinstance(bay, dict) or not bay.get("type"):
            continue
        floor_idx = floor_data.get("floor", 2)
        bay_specs.append((bay, floor_idx))

    if not bay_specs:
        return objects

    facade_hex = get_facade_hex(params)
    hex_id = facade_hex.lstrip('#')
    facade_mat = get_or_create_material(f"mat_facade_{hex_id}", colour_hex=facade_hex, roughness=0.85)
    glass_mat = create_glass_material("mat_glass")
    trim_mat = get_or_create_material("mat_trim_white", colour_hex="#F0F0F0", roughness=0.5)

    for bay, floor_idx in bay_specs:
        proj = bay.get("projection_m", 0.4)
        bay_w = bay.get("width_m", 2.5)
        bay_h = bay.get("height_m", 2.0)
        sill_offset = bay.get("sill_height_m", 0.5)

        # --- Double-height: floors_spanned overrides bay_h ---
        floors_spanned = bay.get("floors_spanned", None)
        if floors_spanned and isinstance(floors_spanned, list) and len(floors_spanned) >= 2:
            span_indices = []
            for fs in floors_spanned:
                if isinstance(fs, (int, float)):
                    span_indices.append(int(fs))
                elif isinstance(fs, str):
                    name_map = {"ground": 1, "first": 1, "second": 2, "third": 3, "fourth": 4}
                    span_indices.append(name_map.get(fs.lower(), 1))
            if span_indices:
                first_floor = min(span_indices)
                last_floor = max(span_indices)
                floor_idx = first_floor
                z_start = sum(floor_heights[:max(0, first_floor - 1)])
                z_end = sum(floor_heights[:min(last_floor, len(floor_heights))])
                bay_h = (z_end - z_start) - sill_offset * 0.5

        # --- Z base ---
        z_base = sum(floor_heights[:max(0, int(floor_idx) - 1)]) if isinstance(floor_idx, (int, float)) else 3.0

        # --- X offset from position field ---
        x_offset = 0.0
        position = bay.get("position", "")
        if isinstance(position, str):
            pos_lower = position.lower()
            if "left" in pos_lower:
                x_offset = -facade_width / 4
            elif "right" in pos_lower:
                x_offset = facade_width / 4
            elif "center" in pos_lower or "centre" in pos_lower:
                x_offset = 0.0

        # --- Determine if canted (3-sided) or box ---
        bay_type = bay.get("type", "")
        sides = bay.get("sides", 0)
        is_canted = (
            sides == 3
            or "three_sided" in str(bay_type).lower()
            or "canted" in str(bay_type).lower()
        )

        if is_canted:
            objects.extend(_create_canted_bay(
                bay, proj, bay_w, bay_h, z_base, sill_offset, x_offset,
                facade_mat, glass_mat, trim_mat
            ))
        else:
            objects.extend(_create_box_bay(
                bay, proj, bay_w, bay_h, z_base, sill_offset, x_offset,
                facade_mat, glass_mat, trim_mat
            ))

    return objects


def _create_box_bay(bay, proj, bay_w, bay_h, z_base, sill_offset, x_offset,
                    facade_mat, glass_mat, trim_mat):
    """Create a rectangular (flat-front) box bay window."""
    objects = []

    bpy.ops.mesh.primitive_cube_add(size=1)
    bay_obj = bpy.context.active_object
    bay_obj.name = "bay_window"
    bay_obj.scale = (bay_w, proj, bay_h)
    bpy.ops.object.transform_apply(scale=True)
    bay_obj.location = (x_offset, proj / 2, z_base + sill_offset + bay_h / 2)
    assign_material(bay_obj, facade_mat)
    objects.append(bay_obj)

    # Glass panes on front face
    win_count = bay.get("window_count_in_bay", 3)
    win_w = bay.get("individual_window_width_m", bay_w / win_count * 0.8)
    win_h = bay.get("individual_window_height_m", bay_h * 0.7)

    for i in range(win_count):
        x = x_offset - bay_w / 2 + bay_w / win_count * (i + 0.5)
        bpy.ops.mesh.primitive_plane_add(size=1)
        g = bpy.context.active_object
        g.name = f"bay_glass_{i}"
        g.scale = (win_w * 0.9, 1, win_h * 0.9)
        bpy.ops.object.transform_apply(scale=True)
        g.rotation_euler.x = math.pi / 2
        g.location = (x, proj + 0.01, z_base + sill_offset + bay_h / 2)
        assign_material(g, glass_mat)
        objects.append(g)

    # Cornice
    bpy.ops.mesh.primitive_cube_add(size=1)
    bay_cap = bpy.context.active_object
    bay_cap.name = "bay_cornice"
    bay_cap.scale = (bay_w + 0.1, proj + 0.15, 0.08)
    bpy.ops.object.transform_apply(scale=True)
    bay_cap.location = (x_offset, proj / 2, z_base + sill_offset + bay_h + 0.04)
    assign_material(bay_cap, trim_mat)
    objects.append(bay_cap)

    return objects


def _create_canted_bay(bay, proj, bay_w, bay_h, z_base, sill_offset, x_offset,
                       facade_mat, glass_mat, trim_mat):
    """Create a canted (3-sided) bay window using bmesh.

    Geometry (top-down view, facade along X axis at y=0):

        v0 (-bay_w/2, 0) ---- v3 (bay_w/2, 0)       <- facade plane
            \\                    /
         v1  \\                /  v2
              front panel                             <- at y=proj

    Front panel (v1-v2) is bay_w*0.5 wide, parallel to facade.
    Side panels connect facade corners to front panel corners.
    """
    objects = []
    angle_deg = bay.get("angle_deg", 45)

    front_w = bay_w * 0.5
    half_front = front_w / 2
    half_total = bay_w / 2

    z_bot = z_base + sill_offset
    z_top = z_bot + bay_h

    # 4 vertices at bottom, 4 at top
    verts_bot = [
        (-half_total + x_offset, 0, z_bot),        # v0: left at facade
        (-half_front + x_offset, proj, z_bot),      # v1: left-front
        (half_front + x_offset, proj, z_bot),       # v2: right-front
        (half_total + x_offset, 0, z_bot),          # v3: right at facade
    ]
    verts_top = [
        (-half_total + x_offset, 0, z_top),        # v4
        (-half_front + x_offset, proj, z_top),     # v5
        (half_front + x_offset, proj, z_top),      # v6
        (half_total + x_offset, 0, z_top),         # v7
    ]

    all_verts = verts_bot + verts_top  # indices 0-3 bottom, 4-7 top

    faces = [
        (0, 1, 2, 3),      # bottom (floor)
        (7, 6, 5, 4),      # top (ceiling)
        (0, 4, 5, 1),      # left side panel
        (1, 5, 6, 2),      # front panel
        (2, 6, 7, 3),      # right side panel
    ]

    mesh = bpy.data.meshes.new("canted_bay_mesh")
    bm = bmesh.new()

    bm_verts = [bm.verts.new(v) for v in all_verts]
    bm.verts.ensure_lookup_table()

    for face_indices in faces:
        bm.faces.new([bm_verts[i] for i in face_indices])

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    bay_obj = bpy.data.objects.new("bay_window_canted", mesh)
    bpy.context.collection.objects.link(bay_obj)
    assign_material(bay_obj, facade_mat)
    objects.append(bay_obj)

    # --- Glass windows ---
    z_glass_center = z_bot + bay_h / 2
    win_h = bay.get("individual_window_height_m", bay_h * 0.7)

    # Front face glass (center panel)
    front_win_count = bay.get("window_count_in_bay", 3)
    front_pane_count = max(1, front_win_count - 2)
    front_pane_w = front_w / front_pane_count * 0.75

    for i in range(front_pane_count):
        fx = x_offset - half_front + front_w / front_pane_count * (i + 0.5)
        bpy.ops.mesh.primitive_plane_add(size=1)
        g = bpy.context.active_object
        g.name = f"bay_canted_front_glass_{i}"
        g.scale = (front_pane_w, 1, win_h * 0.9)
        bpy.ops.object.transform_apply(scale=True)
        g.rotation_euler.x = math.pi / 2
        g.location = (fx, proj + 0.01, z_glass_center)
        assign_material(g, glass_mat)
        objects.append(g)

    # Side panel glass (one pane per side)
    side_dx = half_total - half_front
    side_dy = proj
    side_len = math.sqrt(side_dx ** 2 + side_dy ** 2)
    side_angle = math.atan2(side_dy, side_dx)
    side_pane_w = side_len * 0.6

    # Left side panel glass
    lx_mid = x_offset + (-half_total + -half_front) / 2
    ly_mid = proj / 2
    bpy.ops.mesh.primitive_plane_add(size=1)
    gl = bpy.context.active_object
    gl.name = "bay_canted_left_glass"
    gl.scale = (side_pane_w, 1, win_h * 0.9)
    bpy.ops.object.transform_apply(scale=True)
    gl.rotation_euler.x = math.pi / 2
    gl.rotation_euler.z = -(math.pi / 2 - side_angle)
    gl.location = (lx_mid, ly_mid + 0.01, z_glass_center)
    assign_material(gl, glass_mat)
    objects.append(gl)

    # Right side panel glass
    rx_mid = x_offset + (half_total + half_front) / 2
    ry_mid = proj / 2
    bpy.ops.mesh.primitive_plane_add(size=1)
    gr = bpy.context.active_object
    gr.name = "bay_canted_right_glass"
    gr.scale = (side_pane_w, 1, win_h * 0.9)
    bpy.ops.object.transform_apply(scale=True)
    gr.rotation_euler.x = math.pi / 2
    gr.rotation_euler.z = (math.pi / 2 - side_angle)
    gr.location = (rx_mid, ry_mid + 0.01, z_glass_center)
    assign_material(gr, glass_mat)
    objects.append(gr)

    # --- Cornice (follows canted footprint) ---
    cornice_h = 0.08
    c_overhang = 0.05
    c_verts_bot = [
        (-half_total - c_overhang + x_offset, -c_overhang, z_top),
        (-half_front - c_overhang + x_offset, proj + c_overhang, z_top),
        (half_front + c_overhang + x_offset, proj + c_overhang, z_top),
        (half_total + c_overhang + x_offset, -c_overhang, z_top),
    ]
    c_verts_top = [
        (v[0], v[1], v[2] + cornice_h) for v in c_verts_bot
    ]
    c_all = c_verts_bot + c_verts_top
    c_faces = [
        (0, 1, 2, 3),
        (7, 6, 5, 4),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (0, 3, 7, 4),
    ]

    c_mesh = bpy.data.meshes.new("canted_bay_cornice_mesh")
    c_bm = bmesh.new()
    c_bm_verts = [c_bm.verts.new(v) for v in c_all]
    c_bm.verts.ensure_lookup_table()
    for fi in c_faces:
        c_bm.faces.new([c_bm_verts[i] for i in fi])
    c_bm.to_mesh(c_mesh)
    c_bm.free()
    c_mesh.update()

    cornice_obj = bpy.data.objects.new("bay_canted_cornice", c_mesh)
    bpy.context.collection.objects.link(cornice_obj)
    assign_material(cornice_obj, trim_mat)
    objects.append(cornice_obj)

    return objects


def create_storefront(params, wall_obj, facade_width):
    """Create commercial storefront: cut large opening, add glass panels, mullions, awning."""
    sf = params.get("storefront", {})
    if not isinstance(sf, dict) or not params.get("has_storefront"):
        return []

    objects = []

    # Storefront dimensions
    sf_w = sf.get("width_m", facade_width * 0.85)
    sf_h = sf.get("height_m", 2.5)
    bulkhead_h = 0.0
    bulkhead = sf.get("bulkhead", {})
    if isinstance(bulkhead, dict) and bulkhead.get("present", True):
        bulkhead_h = bulkhead.get("height_m", sf.get("bulkhead_height_m", 0.4))

    # Cut the storefront opening from the wall
    cutter = create_rect_cutter("sf_cut", sf_w, sf_h, depth=0.8)
    cutter.location.x = 0
    cutter.location.y = 0.01
    cutter.location.z = bulkhead_h + sf_h / 2
    boolean_cut(wall_obj, cutter)

    # Glass panel (full storefront)
    glass_mat = create_glass_material("mat_sf_glass")
    bpy.ops.mesh.primitive_plane_add(size=1)
    gp = bpy.context.active_object
    gp.name = "storefront_glass"
    gp.scale = (sf_w * 0.95, 1, sf_h * 0.95)
    bpy.ops.object.transform_apply(scale=True)
    gp.rotation_euler.x = math.pi / 2
    gp.location = (0, -0.05, bulkhead_h + sf_h / 2)
    assign_material(gp, glass_mat)
    objects.append(gp)

    # Mullions (vertical dividers)
    glazing = sf.get("glazing", {})
    panel_count = 2
    if isinstance(glazing, dict):
        panel_count = glazing.get("panel_count", 2)
    else:
        panel_count = max(2, int(sf_w / 2.0))

    mullion_hex = "#3A3A3A"
    frame_desc = sf.get("frame", str(glazing.get("frame", "")) if isinstance(glazing, dict) else "")
    if "bronze" in str(frame_desc).lower():
        mullion_hex = "#4A3A2A"

    mullion_mat = get_or_create_material(f"mat_sf_mullion", colour_hex=mullion_hex, roughness=0.3)

    # Vertical mullions
    for mi in range(panel_count + 1):
        mx = -sf_w / 2 + (sf_w / panel_count) * mi
        bpy.ops.mesh.primitive_cube_add(size=1)
        mul = bpy.context.active_object
        mul.name = f"sf_mullion_v_{mi}"
        mul.scale = (0.04, 0.06, sf_h)
        bpy.ops.object.transform_apply(scale=True)
        mul.location = (mx, 0.02, bulkhead_h + sf_h / 2)
        assign_material(mul, mullion_mat)
        objects.append(mul)

    # Horizontal frame at top and bottom
    for hz, hname in [(bulkhead_h + sf_h, "sf_head"), (bulkhead_h, "sf_sill")]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        hf = bpy.context.active_object
        hf.name = hname
        hf.scale = (sf_w + 0.1, 0.06, 0.05)
        bpy.ops.object.transform_apply(scale=True)
        hf.location = (0, 0.02, hz)
        assign_material(hf, mullion_mat)
        objects.append(hf)

    # Bulkhead (solid base panel below glass)
    if bulkhead_h > 0.1:
        facade_hex = get_facade_hex(params)
        bk_mat_str = str(bulkhead.get("material", "brick") if isinstance(bulkhead, dict) else "brick").lower()
        if "brick" in bk_mat_str:
            bk_mat = create_brick_material(f"mat_bulkhead_{facade_hex.lstrip('#')}", facade_hex)
        else:
            bk_mat = get_or_create_material("mat_bulkhead", colour_hex=facade_hex)
        bpy.ops.mesh.primitive_cube_add(size=1)
        bk = bpy.context.active_object
        bk.name = "sf_bulkhead"
        bk.scale = (sf_w, 0.3, bulkhead_h)
        bpy.ops.object.transform_apply(scale=True)
        bk.location = (0, 0, bulkhead_h / 2)
        assign_material(bk, bk_mat)
        objects.append(bk)

    # Awning
    awning = sf.get("awning", {})
    if isinstance(awning, dict) and awning.get("present", awning.get("type")):
        aw_w = awning.get("width_m", facade_width)
        aw_proj = awning.get("projection_m", 1.2)
        aw_h_top = awning.get("height_at_fascia_m", 2.8)
        aw_h_bot = awning.get("height_at_drip_edge_m", aw_h_top - 0.5)

        aw_colour = awning.get("colour", "blue")
        aw_hex = awning.get("colour_hex") if "colour_hex" in awning else colour_name_to_hex(str(aw_colour))

        bm = bmesh.new()
        v0 = bm.verts.new((-aw_w / 2, 0, aw_h_top))
        v1 = bm.verts.new((aw_w / 2, 0, aw_h_top))
        v2 = bm.verts.new((aw_w / 2, aw_proj, aw_h_bot))
        v3 = bm.verts.new((-aw_w / 2, aw_proj, aw_h_bot))
        bm.faces.new([v0, v1, v2, v3])

        mesh = bpy.data.meshes.new("awning")
        bm.to_mesh(mesh)
        bm.free()

        aw_obj = bpy.data.objects.new("awning", mesh)
        bpy.context.collection.objects.link(aw_obj)

        aw_mat = get_or_create_material("mat_awning", colour_hex=aw_hex, roughness=0.6)
        assign_material(aw_obj, aw_mat)
        objects.append(aw_obj)

    return objects


def create_string_courses(params, wall_h, width, depth, bldg_id=""):
    """Create horizontal string courses / belt courses between floors."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []

    sc = dec.get("string_courses", {})
    if not isinstance(sc, dict) or not sc.get("present", False):
        # Also check top-level string_course
        sc = params.get("string_course", {})
        if not isinstance(sc, dict):
            return []

    objects = []
    sc_hex = sc.get("colour_hex", "#D4C9A8")
    sc_h = sc.get("height_mm", sc.get("width_mm", 120))
    if isinstance(sc_h, (int, float)):
        sc_h = sc_h / 1000
    else:
        sc_h = 0.12
    sc_proj = sc.get("projection_mm", 20)
    if isinstance(sc_proj, (int, float)):
        sc_proj = sc_proj / 1000
    else:
        sc_proj = 0.02

    sc_mat = create_stone_material(f"mat_stone_{sc_hex.lstrip('#')}", sc_hex)

    floor_heights = params.get("floor_heights_m", [3.0])
    z_positions = []
    z = 0
    for fh in floor_heights[:-1]:
        z += fh
        z_positions.append(z)

    positions = sc.get("positions", [])
    if isinstance(positions, list):
        pos_text = " ".join(str(p).lower() for p in positions)
        if "parapet_base" in pos_text or "parapet base" in pos_text:
            z_positions.append(wall_h - sc_h / 2)

    seen = set()
    for i, z in enumerate(sorted(z_positions)):
        z_key = round(z, 4)
        if z_key in seen:
            continue
        seen.add(z_key)
        bpy.ops.mesh.primitive_cube_add(size=1)
        band = bpy.context.active_object
        band.name = f"string_course_{i}"
        band.scale = (width + sc_proj * 2, sc_proj, sc_h)
        bpy.ops.object.transform_apply(scale=True)
        band.location = (0, sc_proj / 2, z)
        assign_material(band, sc_mat)
        objects.append(band)

    return objects


def _create_corbel_band(name_prefix, cx, y_face, z_base, width, course_count=3,
                        brick_w=0.22, brick_h=0.075, base_proj=0.035,
                        step_proj=0.02, colour_hex="#B85A3A"):
    """Create a simple stepped corbel table along a front-facing wall."""
    objects = []
    mat = create_brick_material(f"mat_{name_prefix}_{colour_hex.lstrip('#')}", colour_hex)
    count = max(3, int(width / max(brick_w, 0.18)))
    spacing = width / count

    for course in range(course_count):
        proj = base_proj + course * step_proj
        z = z_base + course * brick_h
        for i in range(count):
            x = cx - width / 2 + spacing * (i + 0.5)
            bpy.ops.mesh.primitive_cube_add(size=1)
            corbel = bpy.context.active_object
            corbel.name = f"{name_prefix}_{course}_{i}"
            corbel.scale = (spacing * 0.46, proj, brick_h * 0.48)
            bpy.ops.object.transform_apply(scale=True)
            corbel.location = (x, y_face + proj / 2, z + brick_h / 2)
            assign_material(corbel, mat)
            objects.append(corbel)

    return objects


def _create_arch_voussoirs(name_prefix, cx, y_face, sill_z, width, height, spring_h,
                           count=11, colour_hex="#C8C0B0", depth=0.12):
    """Create wedge-like voussoir blocks around a front-facing arch."""
    objects = []
    mat = create_stone_material(f"mat_{name_prefix}_{colour_hex.lstrip('#')}", colour_hex)
    radius = width / 2 + 0.08
    center_z = sill_z + spring_h
    stone_w = max(0.08, width * 0.06)
    stone_h = max(0.10, height * 0.08)

    for si in range(count):
        angle = math.pi * si / max(1, count - 1)
        sx = cx + radius * math.cos(angle)
        sz = center_z + radius * math.sin(angle)
        bpy.ops.mesh.primitive_cube_add(size=1)
        stone = bpy.context.active_object
        stone.name = f"{name_prefix}_{si}"
        stone.scale = (stone_w, depth, stone_h)
        bpy.ops.object.transform_apply(scale=True)
        stone.location = (sx, y_face + depth / 2, sz)
        stone.rotation_euler.y = math.pi / 2 - angle
        assign_material(stone, mat)
        objects.append(stone)

    return objects


def create_corbelling(params, wall_h, width, depth, bldg_id=""):
    """Create simple corbel tables from decorative metadata."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []

    corbelling = dec.get("corbelling", {})
    if corbelling is False:
        return []
    if not isinstance(corbelling, dict) or not corbelling:
        return []

    course_count = corbelling.get("course_count", 3)
    if not isinstance(course_count, int):
        text = json.dumps(corbelling).lower()
        if "5 course" in text or "5-course" in text:
            course_count = 5
        elif "4 course" in text or "4-course" in text:
            course_count = 4
        else:
            course_count = 3

    facade_hex = get_facade_hex(params)
    z_base = wall_h - 0.28
    return _create_corbel_band(f"corbel_{bldg_id}", 0, 0.02, z_base, width,
                               course_count=course_count, colour_hex=facade_hex)


def create_tower(params, bldg_id=""):
    """Create a clock tower (for fire station or similar)."""
    volumes = params.get("volumes", [])
    tower_data = None
    for vol in volumes:
        if isinstance(vol, dict) and "tower" in vol.get("id", "").lower():
            tower_data = vol
            break

    if not tower_data:
        return []

    objects = []
    tw = tower_data.get("width_m", 3.5)
    td = tower_data.get("depth_m", 3.5)
    th = tower_data.get("total_height_m", 22.0)

    # Tower position relative to heritage hall
    # Place it at the right side of the building
    facade_w = params.get("facade_width_m", 18.0)
    tx = facade_w / 2 - tw / 2

    facade_hex = get_facade_hex(params)
    hex_id = facade_hex.lstrip('#')
    tower_mat = get_or_create_material(f"mat_facade_{hex_id}", colour_hex=facade_hex, roughness=0.85)

    # Main tower shaft
    bpy.ops.mesh.primitive_cube_add(size=1)
    shaft = bpy.context.active_object
    shaft.name = "tower_shaft"
    shaft.scale = (tw, td, th)
    bpy.ops.object.transform_apply(scale=True)
    shaft.location = (tx, -td / 2, th / 2)
    assign_material(shaft, tower_mat)
    objects.append(shaft)

    # String courses between tower levels
    levels = tower_data.get("level_details", [])
    sc_mat = get_or_create_material(f"mat_tower_sc_{bldg_id}", colour_hex="#D4C9A8", roughness=0.6)
    z = 0
    for lvl in levels:
        if isinstance(lvl, dict):
            lvl_h = lvl.get("height_m", 4.0)
            z += lvl_h
            bpy.ops.mesh.primitive_cube_add(size=1)
            band = bpy.context.active_object
            band.name = f"tower_band_{lvl.get('level', 0)}"
            band.scale = (tw + 0.06, td + 0.06, 0.1)
            bpy.ops.object.transform_apply(scale=True)
            band.location = (tx, -td / 2, z)
            assign_material(band, sc_mat)
            objects.append(band)

            # Clock face(s)
            clock = lvl.get("clock_face", {})
            if isinstance(clock, dict) and clock.get("type"):
                diameter = clock.get("diameter_m", 1.5)
                faces_count = clock.get("faces_count", 1)
                clock_mat = get_or_create_material("mat_clock", colour_hex="#F0F0E0", roughness=0.3)
                clock_z = z - lvl_h / 2

                # Front face (Y+) — always created
                face_defs = [
                    ("clock_face_front", {"rx": math.pi / 2, "ry": 0},
                     (tx, -td / 2 + td / 2 + 0.05, clock_z)),
                ]
                if faces_count >= 4:
                    # Back face (Y-)
                    face_defs.append(
                        ("clock_face_back", {"rx": -math.pi / 2, "ry": 0},
                         (tx, -td / 2 - td / 2 - 0.05, clock_z))
                    )
                    # Left face (X-)
                    face_defs.append(
                        ("clock_face_left", {"rx": 0, "ry": math.pi / 2},
                         (tx - tw / 2 - 0.05, -td / 2, clock_z))
                    )
                    # Right face (X+)
                    face_defs.append(
                        ("clock_face_right", {"rx": 0, "ry": -math.pi / 2},
                         (tx + tw / 2 + 0.05, -td / 2, clock_z))
                    )

                for cf_name, rot, loc in face_defs:
                    bpy.ops.mesh.primitive_cylinder_add(radius=diameter / 2, depth=0.1, vertices=32)
                    cf = bpy.context.active_object
                    cf.name = cf_name
                    cf.rotation_euler.x = rot["rx"]
                    cf.rotation_euler.y = rot["ry"]
                    cf.location = loc
                    assign_material(cf, clock_mat)
                    objects.append(cf)

    # Tower parapet cap
    bpy.ops.mesh.primitive_cube_add(size=1)
    cap = bpy.context.active_object
    cap.name = "tower_cap"
    cap.scale = (tw + 0.15, td + 0.15, 0.15)
    bpy.ops.object.transform_apply(scale=True)
    cap.location = (tx, -td / 2, th + 0.075)
    assign_material(cap, sc_mat)
    objects.append(cap)

    return objects


def create_quoins(params, wall_h, width, depth, bldg_id=""):
    """Create vertical quoin strips at building corners."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []

    quoins = dec.get("quoins", {})
    if not isinstance(quoins, dict) or not quoins.get("present", False):
        return []

    objects = []
    q_hex = quoins.get("colour_hex", "#D4C9A8")
    q_w = quoins.get("strip_width_mm", 200) / 1000
    q_proj = quoins.get("projection_mm", 15) / 1000

    q_mat = get_or_create_material(f"mat_quoins_{bldg_id}", colour_hex=q_hex, roughness=0.6)

    hw = width / 2
    positions = [(-hw, "quoin_left"), (hw, "quoin_right")]

    total_strips = quoins.get("total_vertical_strips")
    locations = quoins.get("locations", [])
    if isinstance(total_strips, int) and total_strips >= 3:
        positions = []
        spacing = width / max(1, total_strips - 1)
        for idx in range(total_strips):
            x = -hw + spacing * idx
            positions.append((x, f"quoin_strip_{idx}"))
    elif isinstance(locations, list) and any("between_bays" in str(loc).lower() for loc in locations):
        positions = [
            (-hw, "quoin_left"),
            (-width / 6, "quoin_inner_left"),
            (width / 6, "quoin_inner_right"),
            (hw, "quoin_right"),
        ]

    for x, name in positions:
        bpy.ops.mesh.primitive_cube_add(size=1)
        q = bpy.context.active_object
        q.name = name
        q.scale = (q_w, q_proj, wall_h)
        bpy.ops.object.transform_apply(scale=True)
        q.location = (x, q_proj / 2, wall_h / 2)
        assign_material(q, q_mat)
        objects.append(q)

    return objects


def create_bargeboard(params, wall_h, width, depth, bldg_id=""):
    """Create decorative bargeboard along gable rake edges."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        dec = {}

    bb = dec.get("bargeboard", {})
    # Also check roof_detail.bargeboard for detailed dimensions
    rd_bb = params.get("roof_detail", {}).get("bargeboard", {})
    if isinstance(rd_bb, dict) and rd_bb:
        # Merge: roof_detail.bargeboard has priority for dimensions
        merged = dict(bb) if isinstance(bb, dict) else {}
        merged.update(rd_bb)
        bb = merged

    if not isinstance(bb, dict) or not bb.get("present", True):
        # Check roof_features for bargeboard mentions
        rf = params.get("roof_features", [])
        has_bb = any("bargeboard" in str(f).lower() or "rake" in str(f).lower() for f in rf)
        if not has_bb:
            return []
        bb = {"type": "simple", "colour_hex": "#3E2A1A"}

    pitch = params.get("roof_pitch_deg", 35)
    pitch_rad = math.radians(pitch)
    ridge_height = (width / 2) * math.tan(pitch_rad)

    # Get eave overhang for positioning
    rd = params.get("roof_detail", {})
    eave_mm = rd.get("eave_overhang_mm", 300) if isinstance(rd, dict) else 300
    overhang = eave_mm / 1000.0

    bb_hex = bb.get("colour_hex", bb.get("colour", "#3E2A1A"))
    if not bb_hex.startswith("#"):
        bb_hex = colour_name_to_hex(str(bb_hex))
    bb_width = bb.get("width_mm", 220) / 1000
    bb_proj = overhang  # bargeboard hangs at the eave overhang
    bb_thick = 0.04

    bb_mat = get_or_create_material(f"mat_bargeboard_{bb_hex.lstrip('#')}", colour_hex=bb_hex, roughness=0.6)

    objects = []
    half_w = width / 2
    rake_len = math.sqrt((half_w) ** 2 + ridge_height ** 2)
    rake_angle = math.atan2(ridge_height, half_w)

    # Front gable bargeboard (y ~ 0)
    for side in [-1, 1]:  # left and right rake
        bm = bmesh.new()
        # Board as a flat rectangle, then rotate to follow rake
        hw = rake_len / 2
        hh = bb_width / 2

        v0 = bm.verts.new((-hw, 0, -hh))
        v1 = bm.verts.new((hw, 0, -hh))
        v2 = bm.verts.new((hw, 0, hh))
        v3 = bm.verts.new((-hw, 0, hh))
        # Front face
        bm.faces.new([v0, v1, v2, v3])
        # Back face (give thickness)
        v4 = bm.verts.new((-hw, -bb_thick, -hh))
        v5 = bm.verts.new((hw, -bb_thick, -hh))
        v6 = bm.verts.new((hw, -bb_thick, hh))
        v7 = bm.verts.new((-hw, -bb_thick, hh))
        bm.faces.new([v7, v6, v5, v4])
        # Sides
        bm.faces.new([v0, v4, v5, v1])
        bm.faces.new([v1, v5, v6, v2])
        bm.faces.new([v2, v6, v7, v3])
        bm.faces.new([v3, v7, v4, v0])

        # Add scalloped cutouts along bottom edge if ornate
        bb_type = str(bb.get("type", "")).lower()
        if "scallop" in bb_type or "fretwork" in bb_type or "scroll" in bb_type:
            pattern_repeat = bb.get("pattern_repeat_mm", 150) / 1000
            n_scallops = max(3, int(rake_len / pattern_repeat))
            scallop_r = pattern_repeat * 0.35
            for si in range(n_scallops):
                cx = -hw + pattern_repeat * (si + 0.5)
                if cx > hw:
                    break
                # Create semicircular cutout vertices (approximate with 6 segments)
                cut_verts_f = []
                cut_verts_b = []
                for seg in range(7):
                    angle = math.pi * seg / 6
                    sx = cx + scallop_r * math.cos(angle)
                    sz = -hh + scallop_r * math.sin(angle)
                    cut_verts_f.append(bm.verts.new((sx, 0.01, sz)))
                    cut_verts_b.append(bm.verts.new((sx, -bb_thick - 0.01, sz)))

        mesh = bpy.data.meshes.new(f"bargeboard_{side}")
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new(f"bargeboard_{side}", mesh)
        bpy.context.collection.objects.link(obj)

        # Position: center of rake line, hanging from eave overhang
        cx = side * half_w / 2
        cz = wall_h + ridge_height / 2
        obj.location = (cx, bb_proj + 0.05, cz)  # in front of wall at eave edge
        obj.rotation_euler.y = side * rake_angle
        assign_material(obj, bb_mat)
        objects.append(obj)

    return objects


def create_cornice_band(params, wall_h, width, depth, bldg_id=""):
    """Create projecting cornice moulding at the eave line."""
    cornice = params.get("cornice", {})
    if not cornice:
        dec = params.get("decorative_elements", {})
        if isinstance(dec, dict):
            cornice = dec.get("cornice", {})
    if isinstance(cornice, str):
        if "none" in cornice.lower():
            return []
        cornice = {"type": cornice}
    if not isinstance(cornice, dict):
        return []
    if cornice.get("type", "") == "none":
        return []

    # Get cornice dimensions
    proj = cornice.get("projection_mm", 80)
    if isinstance(proj, (int, float)):
        proj = proj / 1000
    else:
        proj = 0.08
    height = cornice.get("height_mm", 150)
    if isinstance(height, (int, float)):
        height = height / 1000
    else:
        height = 0.15

    # Cornice colour — usually matches trim
    cornice_hex = cornice.get("colour_hex", "")
    if not isinstance(cornice_hex, str) or not cornice_hex.startswith("#"):
        colour_palette = params.get("colour_palette", {})
        trim = colour_palette.get("trim", {})
        cornice_hex = "#D4C9A8"
        if isinstance(trim, dict):
            cornice_hex = trim.get("hex_approx", "#D4C9A8")
        else:
            cornice_hex = get_trim_hex(params)

    mat = get_or_create_material(f"mat_cornice_{cornice_hex.lstrip('#')}", colour_hex=cornice_hex, roughness=0.5)

    objects = []

    # Front cornice
    bpy.ops.mesh.primitive_cube_add(size=1)
    c = bpy.context.active_object
    c.name = f"cornice_front_{bldg_id}"
    c.scale = (width + proj * 2, proj, height)
    bpy.ops.object.transform_apply(scale=True)
    c.location = (0, proj / 2, wall_h + height / 2)
    assign_material(c, mat)
    objects.append(c)

    # Side cornices
    for side_x, side_name in [(-width / 2 - proj / 2, "left"), (width / 2 + proj / 2, "right")]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        sc = bpy.context.active_object
        sc.name = f"cornice_{side_name}_{bldg_id}"
        sc.scale = (proj, depth, height)
        bpy.ops.object.transform_apply(scale=True)
        sc.location = (side_x, -depth / 2, wall_h + height / 2)
        assign_material(sc, mat)
        objects.append(sc)

    # Optional storefront head/cornice band
    sf = params.get("storefront", {})
    if params.get("has_storefront") and isinstance(sf, dict):
        sf_h = sf.get("height_m", 3.2)
        bulkhead_h = sf.get("bulkhead_height_m", 0.0)
        storefront_z = bulkhead_h + sf_h + height / 2
        sf_proj = max(proj * 0.8, 0.08)
        bpy.ops.mesh.primitive_cube_add(size=1)
        sh = bpy.context.active_object
        sh.name = f"storefront_cornice_{bldg_id}"
        sh.scale = (width + sf_proj * 1.5, sf_proj, height * 0.9)
        bpy.ops.object.transform_apply(scale=True)
        sh.location = (0, sf_proj / 2, storefront_z)
        assign_material(sh, mat)
        objects.append(sh)

    return objects


def create_stained_glass_transoms(params, facade_width, bldg_id=""):
    """Create simple stained-glass transom panels for storefronts/entries."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []
    transom = dec.get("stained_glass_transoms", {})
    if not isinstance(transom, dict) or not transom.get("present", False):
        return []

    sf = params.get("storefront", {})
    if not params.get("has_storefront") or not isinstance(sf, dict):
        return []

    sf_h = sf.get("height_m", 3.2)
    bulkhead_h = sf.get("bulkhead_height_m", 0.0)
    transom_h = min(0.45, max(0.25, sf_h * 0.12))
    y = 0.03
    z = bulkhead_h + sf_h - transom_h / 2 - 0.08
    palette = str(transom.get("colour_palette", "amber_green_red")).lower()
    colours = ["#A96F2D", "#5C7A3A", "#8E2F2F"] if "amber" in palette else ["#6A6A8A", "#8A6A4A", "#6A8A6A"]

    objects = []
    panel_count = 3
    panel_w = facade_width / (panel_count + 2)
    start_x = -panel_w
    for i in range(panel_count):
        bpy.ops.mesh.primitive_plane_add(size=1)
        panel = bpy.context.active_object
        panel.name = f"transom_{i}_{bldg_id}"
        panel.scale = (panel_w * 0.42, 1, transom_h * 0.48)
        bpy.ops.object.transform_apply(scale=True)
        panel.rotation_euler.x = math.pi / 2
        panel.location = (start_x + i * panel_w, y, z)
        mat = get_or_create_material(f"mat_transom_{i}_{bldg_id}", colour_hex=colours[i % len(colours)], roughness=0.15)
        assign_material(panel, mat)
        objects.append(panel)

    return objects


def create_hip_rooflet(params, wall_h, width, depth, bldg_id=""):
    """Create a small hip-roofed rooftop element from roof_detail.hip_element."""
    rd = params.get("roof_detail", {})
    if not isinstance(rd, dict):
        return []
    hip = rd.get("hip_element", {})
    if not isinstance(hip, dict) or not hip.get("present", False):
        return []

    pitch = hip.get("pitch_deg", 20)
    base_w = max(1.2, min(width * 0.22, 2.5))
    base_d = max(1.2, min(depth * 0.18, 2.2))
    rise = min(base_w, base_d) * 0.35 * math.tan(math.radians(max(5, pitch)))
    x = width * 0.28 if "corner" in str(hip.get("location", "")).lower() else 0
    y = -depth * 0.28
    z = wall_h

    bm = bmesh.new()
    hw = base_w / 2
    hd = base_d / 2
    v0 = bm.verts.new((x - hw, y - hd, z))
    v1 = bm.verts.new((x + hw, y - hd, z))
    v2 = bm.verts.new((x + hw, y + hd, z))
    v3 = bm.verts.new((x - hw, y + hd, z))
    v4 = bm.verts.new((x, y, z + rise))
    bm.faces.new([v0, v1, v4])
    bm.faces.new([v1, v2, v4])
    bm.faces.new([v2, v3, v4])
    bm.faces.new([v3, v0, v4])

    mesh = bpy.data.meshes.new(f"hip_rooflet_{bldg_id}")
    bm.to_mesh(mesh)
    bm.free()

    rooflet = bpy.data.objects.new(f"hip_rooflet_{bldg_id}", mesh)
    bpy.context.collection.objects.link(rooflet)
    mat = create_roof_material(f"mat_hip_rooflet_{bldg_id}", infer_hex_from_text(hip.get("colour", ""), hip.get("material", ""), default="#3A3A3A"))
    assign_material(rooflet, mat)
    return [rooflet]


def create_window_lintels(params, wall_h, facade_width, bldg_id=""):
    """Create projecting lintels above windows and sills below."""
    windows_detail = get_effective_windows_detail(params)
    floor_heights = params.get("floor_heights_m", [3.0])
    if not windows_detail:
        return []

    # Check if building has lintels described
    dec = params.get("decorative_elements", {})
    has_lintels = False
    if isinstance(dec, dict):
        for key in ["lintels", "stone_lintels", "window_hoods"]:
            if dec.get(key):
                has_lintels = True
                break

    # Also check individual window specs for lintel/sill data
    for fd in windows_detail:
        if isinstance(fd, dict):
            for w in fd.get("windows", []):
                if isinstance(w, dict) and (w.get("lintel") or w.get("sill") or w.get("surround")):
                    has_lintels = True

    if not has_lintels:
        return []

    # Lintel material — usually stone/cream
    lintel_hex = "#D4C9A8"
    if isinstance(dec, dict):
        lint = dec.get("lintels", dec.get("stone_lintels", {}))
        if isinstance(lint, dict):
            lintel_hex = lint.get("colour_hex", lint.get("colour", "#D4C9A8"))
            if not lintel_hex.startswith("#"):
                lintel_hex = colour_name_to_hex(str(lintel_hex))

    mat = get_or_create_material(f"mat_lintel_{lintel_hex.lstrip('#')}", colour_hex=lintel_hex, roughness=0.5)
    objects = []

    for floor_data in windows_detail:
        if not isinstance(floor_data, dict):
            continue

        floor_idx = _normalize_floor_index(floor_data.get("floor", 1), floor_heights)

        z_base = sum(floor_heights[:max(0, int(floor_idx) - 1)])

        windows = floor_data.get("windows", [])
        if not windows and "count" in floor_data:
            count = floor_data.get("count", 0)
            w = floor_data.get("width_m", 0.8)
            h = floor_data.get("height_m", 1.3)
            windows = [{"count": count, "width_m": w, "height_m": h}]

        for win_spec in windows:
            if not isinstance(win_spec, dict):
                continue
            count = win_spec.get("count", 1)
            if count == 0:
                continue
            w = win_spec.get("width_m", win_spec.get("width_each_m", 0.8))
            h = win_spec.get("height_m", 1.3)

            fi = max(0, int(floor_idx) - 1)
            fi = min(fi, len(floor_heights) - 1)
            floor_h = floor_heights[fi] if floor_heights else 3.0
            sill_h = z_base + max(0.8, (floor_h - h) / 2)

            total_win_w = count * w + (count - 1) * max(0.3, (facade_width - count * w) / (count + 1))
            start_x = -total_win_w / 2 + w / 2
            spacing = (total_win_w - w) / max(1, count - 1) if count > 1 else 0

            for i in range(count):
                x = start_x + i * spacing if count > 1 else 0

                # Lintel (above window)
                bpy.ops.mesh.primitive_cube_add(size=1)
                lt = bpy.context.active_object
                lt.name = f"lintel_{floor_idx}_{i}"
                lt.scale = (w + 0.08, 0.06, 0.07)
                bpy.ops.object.transform_apply(scale=True)
                lt.location = (x, 0.03, sill_h + h + 0.035)
                assign_material(lt, mat)
                objects.append(lt)

                # Sill (below window) — slightly wider and more projecting
                bpy.ops.mesh.primitive_cube_add(size=1)
                sl = bpy.context.active_object
                sl.name = f"sill_{floor_idx}_{i}"
                sl.scale = (w + 0.1, 0.08, 0.04)
                bpy.ops.object.transform_apply(scale=True)
                sl.location = (x, 0.04, sill_h - 0.02)
                assign_material(sl, mat)
                objects.append(sl)

    return objects


def create_brackets(params, wall_h, width, depth, bldg_id=""):
    """Create decorative brackets at gable eave or porch."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []

    objects = []

    # Gable brackets
    gb = dec.get("gable_brackets", dec.get("brackets", {}))
    if isinstance(gb, dict) and gb.get("type"):
        proj = gb.get("projection_mm", 200) / 1000
        bracket_h = gb.get("height_mm", 300) / 1000
        bracket_w = 0.06
        bracket_hex = gb.get("colour_hex", "#3E2A1A")
        if not bracket_hex.startswith("#"):
            bracket_hex = colour_name_to_hex(str(bracket_hex))

        br_mat = get_or_create_material(f"mat_bracket_{bracket_hex.lstrip('#')}", colour_hex=bracket_hex, roughness=0.6)

        # Place brackets under eave at regular intervals
        count = gb.get("count", 4)
        half_w = width / 2
        for i in range(count):
            x = -half_w + (width / max(1, count - 1)) * i if count > 1 else 0

            # Bracket as a right-triangle profile (scroll bracket shape)
            bm = bmesh.new()
            v0 = bm.verts.new((-bracket_w / 2, 0, 0))
            v1 = bm.verts.new((-bracket_w / 2, 0, bracket_h))
            v2 = bm.verts.new((-bracket_w / 2, proj, 0))
            v3 = bm.verts.new((bracket_w / 2, 0, 0))
            v4 = bm.verts.new((bracket_w / 2, 0, bracket_h))
            v5 = bm.verts.new((bracket_w / 2, proj, 0))
            bm.faces.new([v0, v1, v2])  # left
            bm.faces.new([v3, v5, v4])  # right
            bm.faces.new([v0, v2, v5, v3])  # bottom
            bm.faces.new([v1, v4, v5, v2])  # slope
            bm.faces.new([v0, v3, v4, v1])  # back

            mesh = bpy.data.meshes.new(f"bracket_{i}")
            bm.to_mesh(mesh)
            bm.free()

            obj = bpy.data.objects.new(f"bracket_{i}", mesh)
            bpy.context.collection.objects.link(obj)
            obj.location = (x, 0, wall_h - bracket_h)
            assign_material(obj, br_mat)
            objects.append(obj)

    # Porch brackets
    pb = dec.get("porch_brackets", {})
    if isinstance(pb, dict) and pb.get("type"):
        proj = pb.get("projection_mm", 200) / 1000
        bracket_h = pb.get("height_mm", 250) / 1000
        bracket_hex = pb.get("colour_hex", "#3E2A1A")
        if not bracket_hex.startswith("#"):
            bracket_hex = colour_name_to_hex(str(bracket_hex))

        pb_mat = get_or_create_material(f"mat_pbracket_{bracket_hex.lstrip('#')}", colour_hex=bracket_hex, roughness=0.6)
        porch = params.get("porch", {})
        porch_h = porch.get("height_m", 2.8) if isinstance(porch, dict) else 2.8
        porch_d = porch.get("depth_m", 2.0) if isinstance(porch, dict) else 2.0

        count = pb.get("count", 4)
        porch_w = porch.get("width_m", width) if isinstance(porch, dict) else width

        for i in range(count):
            x = -porch_w / 2 + (porch_w / max(1, count - 1)) * i if count > 1 else 0

            bm = bmesh.new()
            bw = 0.05
            v0 = bm.verts.new((-bw / 2, 0, 0))
            v1 = bm.verts.new((-bw / 2, 0, bracket_h))
            v2 = bm.verts.new((-bw / 2, proj, 0))
            v3 = bm.verts.new((bw / 2, 0, 0))
            v4 = bm.verts.new((bw / 2, 0, bracket_h))
            v5 = bm.verts.new((bw / 2, proj, 0))
            bm.faces.new([v0, v1, v2])
            bm.faces.new([v3, v5, v4])
            bm.faces.new([v0, v2, v5, v3])
            bm.faces.new([v1, v4, v5, v2])
            bm.faces.new([v0, v3, v4, v1])

            mesh = bpy.data.meshes.new(f"porch_bracket_{i}")
            bm.to_mesh(mesh)
            bm.free()

            obj = bpy.data.objects.new(f"porch_bracket_{i}", mesh)
            bpy.context.collection.objects.link(obj)
            obj.location = (x, porch_d, porch_h - bracket_h)
            assign_material(obj, pb_mat)
            objects.append(obj)

    return objects


def create_ridge_finial(params, wall_h, width, depth, bldg_id=""):
    """Create decorative finial at gable ridge peak."""
    # Check for finial data
    dec = params.get("decorative_elements", {})
    ridge_el = None
    if isinstance(dec, dict):
        ridge_el = dec.get("ridge_element", dec.get("finial", {}))

    # Also check roof_features
    if not ridge_el:
        rf = params.get("roof_features", [])
        for f in rf:
            if isinstance(f, dict) and ("finial" in str(f.get("type", "")).lower() or
                                         "ridge" in str(f.get("type", "")).lower()):
                ridge_el = f
                break

    if not ridge_el or not isinstance(ridge_el, dict):
        return []

    pitch = params.get("roof_pitch_deg", 35)
    ridge_height = (width / 2) * math.tan(math.radians(pitch))

    finial_h = ridge_el.get("height_m", 0.3)
    finial_hex = ridge_el.get("colour_hex", "#4A4A4A")
    if isinstance(finial_hex, str) and not finial_hex.startswith("#"):
        finial_hex = colour_name_to_hex(str(finial_hex))

    mat = get_or_create_material(f"mat_finial_{finial_hex.lstrip('#')}", colour_hex=finial_hex, roughness=0.4)

    objects = []

    # Front gable finial — cone + sphere at ridge peak
    peak_z = wall_h + ridge_height

    # Cone/spike
    bpy.ops.mesh.primitive_cone_add(radius1=0.06, radius2=0.01, depth=finial_h, vertices=8)
    cone = bpy.context.active_object
    cone.name = f"finial_{bldg_id}"
    cone.location = (0, 0, peak_z + finial_h / 2)
    assign_material(cone, mat)
    objects.append(cone)

    # Small ball on top
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.04, segments=8, ring_count=6)
    ball = bpy.context.active_object
    ball.name = f"finial_ball_{bldg_id}"
    ball.location = (0, 0, peak_z + finial_h + 0.02)
    assign_material(ball, mat)
    objects.append(ball)

    return objects


def create_voussoirs(params, wall_h, facade_width, bldg_id=""):
    """Create voussoir (wedge-shaped arch stones) around arched window openings."""
    windows_detail = get_effective_windows_detail(params)
    floor_heights = params.get("floor_heights_m", [3.0])
    trim_hex = get_trim_hex(params)

    # Check if building explicitly has voussoirs (contrasting stone arch details)
    dec = params.get("decorative_elements", {})
    has_voussoirs = False
    stone_hex = trim_hex
    if isinstance(dec, dict):
        vous = dec.get("voussoirs", {})
        if isinstance(vous, dict) and vous.get("present", False):
            has_voussoirs = True
            stone_hex = vous.get("colour_hex", vous.get("material_hex", trim_hex))
            if not stone_hex.startswith("#"):
                stone_hex = colour_name_to_hex(stone_hex)
        # Also check stone_voussoirs key (used by 20 Denison)
        sv = dec.get("stone_voussoirs", {})
        if isinstance(sv, dict) and sv.get("present", False):
            has_voussoirs = True
            stone_hex = sv.get("colour_hex", trim_hex)
            if not stone_hex.startswith("#"):
                stone_hex = colour_name_to_hex(stone_hex)

    # Don't generate voussoirs if explicitly disabled or not present
    if not has_voussoirs:
        return []

    mat = create_stone_material(f"mat_voussoir_{stone_hex.lstrip('#')}", stone_hex)
    objects = []

    for fd in windows_detail:
        if not isinstance(fd, dict):
            continue

        floor_idx = int(_normalize_floor_index(fd.get("floor", 1), floor_heights))

        z_base = sum(floor_heights[:max(0, floor_idx - 1)])

        wins = fd.get("windows", [])
        for w in wins:
            if not isinstance(w, dict):
                continue

            arch = w.get("arch", {})
            wtype = str(w.get("type", "")).lower()
            if not ("arch" in wtype or (isinstance(arch, dict) and arch)):
                continue

            count = w.get("count", 1)
            win_w = w.get("width_m", 0.8)
            win_h = w.get("height_m", 1.3)
            sill_h = w.get("sill_height_m", 0.8)

            spacing = facade_width / (count + 1)
            for ci in range(count):
                cx = -facade_width / 2 + spacing * (ci + 1)
                win_top_z = z_base + sill_h + win_h

                # Create voussoir stones around arch
                num_stones = 9
                radius = win_w / 2 + 0.04
                stone_w = 0.08
                stone_d = 0.12
                for si in range(num_stones):
                    angle = math.pi * si / (num_stones - 1)
                    sx = cx + radius * math.cos(angle)
                    sz = win_top_z - win_w / 2 + radius * math.sin(angle)

                    bpy.ops.mesh.primitive_cube_add(size=1)
                    stone = bpy.context.active_object
                    stone.name = f"voussoir_{bldg_id}_{ci}_{si}"
                    stone.scale = (stone_w, stone_d, 0.06)
                    stone.location = (sx, 0.16, sz)
                    stone.rotation_euler.y = -(angle - math.pi / 2)
                    assign_material(stone, mat)
                    objects.append(stone)

    return objects


def create_gable_shingles(params, wall_h, width, depth, bldg_id=""):
    """Create fish-scale ornamental shingle infill in gable triangle."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []

    shingles = dec.get("ornamental_shingles", {})
    if not isinstance(shingles, dict) or not shingles:
        # Also check roof features
        rf = params.get("roof_features", [])
        for f in rf:
            if isinstance(f, dict):
                infill = f.get("ornamental_shingle_infill", {})
                if isinstance(infill, dict) and infill:
                    shingles = infill
                    break

    if not shingles:
        return []

    shingle_hex = shingles.get("colour_hex", None)
    if not shingle_hex:
        colour = str(shingles.get("colour", "")).lower()
        shingle_hex = get_facade_hex(params)  # default to facade colour

    pitch = params.get("roof_pitch_deg", 35)
    half_w = width / 2
    ridge_h = half_w * math.tan(math.radians(pitch))

    mat = get_or_create_material(f"mat_shingle_{shingle_hex.lstrip('#')}", colour_hex=shingle_hex, roughness=0.7)

    objects = []
    exposure = shingles.get("exposure_mm", 100) / 1000.0  # convert to metres
    shingle_radius = exposure * 0.6

    # Fill gable triangle with rows of half-round shingles
    # Start above any gable window and go up to near the peak
    start_z = wall_h + ridge_h * 0.35  # above gable window
    end_z = wall_h + ridge_h * 0.92   # near peak

    row = 0
    z = start_z
    while z < end_z:
        # Width at this height (narrowing triangle)
        frac = (z - wall_h) / ridge_h
        row_half_w = half_w * (1.0 - frac) - 0.1  # inset from rake edge

        if row_half_w < shingle_radius * 2:
            break

        # Place shingles across the row
        x = -row_half_w
        col = 0
        # Offset every other row
        offset_x = shingle_radius if (row % 2) else 0
        x += offset_x

        while x < row_half_w:
            bpy.ops.mesh.primitive_uv_sphere_add(
                radius=shingle_radius, segments=8, ring_count=4,
                location=(x, 0.16, z)
            )
            sh = bpy.context.active_object
            sh.name = f"shingle_{bldg_id}_{row}_{col}"
            sh.scale.y = 0.3  # flatten into the wall
            sh.scale.z = 0.8  # slightly oval
            assign_material(sh, mat)
            objects.append(sh)
            x += shingle_radius * 1.8
            col += 1

        z += exposure
        row += 1

    return objects


def create_dormer(params, wall_h, width, depth, bldg_id=""):
    """Create a gable dormer on a flat or sloped roof."""
    dormer_data = params.get("dormer", {})
    if not isinstance(dormer_data, dict) or not dormer_data:
        return []

    d_type = str(dormer_data.get("type", "gable")).lower()
    d_count = dormer_data.get("count", 1)
    d_w = dormer_data.get("width_m", 2.0)
    d_h = dormer_data.get("height_m", 2.5)
    d_pitch = dormer_data.get("gable_pitch_deg", 45)
    d_depth = d_w * 0.8  # dormer depth proportional to width

    # Dormer wall material
    wall_col = str(dormer_data.get("wall_colour", "")).lower()
    if wall_col:
        d_wall_hex = colour_name_to_hex(wall_col)
    else:
        d_wall_hex = get_facade_hex(params)

    roof_col = str(dormer_data.get("roof_colour", "dark_grey")).lower()
    d_roof_hex = colour_name_to_hex(roof_col) if roof_col else "#3A3A3A"

    trim_hex = get_trim_hex(params)

    objects = []

    for di in range(d_count):
        # Position dormer(s) along the roof
        if d_count == 1:
            dx = 0
        else:
            spacing = width / (d_count + 1)
            dx = -width / 2 + spacing * (di + 1)

        # Dormer sits on the roof surface — for flat roofs, at wall_h
        # For pitched roofs, partway up the slope
        roof_type = str(params.get("roof_type", "")).lower()
        if "flat" in roof_type:
            dz_base = wall_h
        else:
            pitch = params.get("roof_pitch_deg", 35)
            dz_base = wall_h + (width / 2) * math.tan(math.radians(pitch)) * 0.3

        dy = -depth * 0.3  # set back from front

        # Dormer front wall (cheek walls)
        wall_mat = create_brick_material(f"mat_dormer_wall_{d_wall_hex.lstrip('#')}",
                                          d_wall_hex)

        bpy.ops.mesh.primitive_cube_add(size=1)
        front_wall = bpy.context.active_object
        front_wall.name = f"dormer_wall_{bldg_id}_{di}"
        front_wall.scale = (d_w, 0.15, d_h * 0.6)
        bpy.ops.object.transform_apply(scale=True)
        front_wall.location = (dx, dy + d_depth / 2, dz_base + d_h * 0.3)
        assign_material(front_wall, wall_mat)
        objects.append(front_wall)

        # Left cheek wall
        bpy.ops.mesh.primitive_cube_add(size=1)
        lw = bpy.context.active_object
        lw.name = f"dormer_cheek_L_{bldg_id}_{di}"
        lw.scale = (0.12, d_depth, d_h * 0.6)
        bpy.ops.object.transform_apply(scale=True)
        lw.location = (dx - d_w / 2, dy, dz_base + d_h * 0.3)
        assign_material(lw, wall_mat)
        objects.append(lw)

        # Right cheek wall
        bpy.ops.mesh.primitive_cube_add(size=1)
        rw = bpy.context.active_object
        rw.name = f"dormer_cheek_R_{bldg_id}_{di}"
        rw.scale = (0.12, d_depth, d_h * 0.6)
        bpy.ops.object.transform_apply(scale=True)
        rw.location = (dx + d_w / 2, dy, dz_base + d_h * 0.3)
        assign_material(rw, wall_mat)
        objects.append(rw)

        # Dormer roof
        top_z = dz_base + d_h * 0.6

        if "turret" in d_type:
            # Conical turret roof (octagonal cone)
            cone_h = d_w * 0.6
            bpy.ops.mesh.primitive_cone_add(
                vertices=8,
                radius1=d_w / 2 + 0.05,
                radius2=0.0,
                depth=cone_h
            )
            cone = bpy.context.active_object
            cone.name = f"dormer_turret_{bldg_id}_{di}"
            cone.location = (dx, dy, top_z + cone_h / 2)
            d_roof_mat = create_roof_material(f"mat_droof_{d_roof_hex.lstrip('#')}", d_roof_hex)
            assign_material(cone, d_roof_mat)
            objects.append(cone)
        else:
            # Standard gable roof
            d_ridge = (d_w / 2) * math.tan(math.radians(d_pitch))
            bm = bmesh.new()
            hw = d_w / 2 + 0.05
            y_f = dy + d_depth / 2 + 0.05
            y_b = dy - d_depth / 2 - 0.05

            v0 = bm.verts.new((-hw + dx, y_b, top_z))
            v1 = bm.verts.new((hw + dx, y_b, top_z))
            v2 = bm.verts.new((hw + dx, y_f, top_z))
            v3 = bm.verts.new((-hw + dx, y_f, top_z))
            v4 = bm.verts.new((dx, y_b, top_z + d_ridge))
            v5 = bm.verts.new((dx, y_f, top_z + d_ridge))

            bm.faces.new([v0, v3, v5, v4])  # left slope
            bm.faces.new([v1, v4, v5, v2])  # right slope
            bm.faces.new([v2, v5, v3])      # front triangle
            bm.faces.new([v0, v4, v1])      # back triangle

            d_mesh = bpy.data.meshes.new(f"dormer_roof_{di}")
            bm.to_mesh(d_mesh)
            bm.free()

            d_roof_obj = bpy.data.objects.new(f"dormer_roof_{bldg_id}_{di}", d_mesh)
            bpy.context.collection.objects.link(d_roof_obj)

            # Solidify
            mod = d_roof_obj.modifiers.new("Solidify", 'SOLIDIFY')
            mod.thickness = 0.05
            mod.offset = -1
            bpy.context.view_layer.objects.active = d_roof_obj
            bpy.ops.object.modifier_apply(modifier=mod.name)

            d_roof_mat = create_roof_material(f"mat_droof_{d_roof_hex.lstrip('#')}", d_roof_hex)
            assign_material(d_roof_obj, d_roof_mat)
            objects.append(d_roof_obj)

        # Dormer window
        gwin = dormer_data.get("gable_window", {})
        if isinstance(gwin, dict):
            gw_w = gwin.get("width_m", 0.6)
            gw_h = gwin.get("height_m", 0.7)

            # Glass pane
            bpy.ops.mesh.primitive_cube_add(size=1)
            glass = bpy.context.active_object
            glass.name = f"dormer_glass_{bldg_id}_{di}"
            glass.scale = (gw_w, 0.02, gw_h)
            bpy.ops.object.transform_apply(scale=True)
            glass.location = (dx, dy + d_depth / 2 + 0.08, dz_base + d_h * 0.3)
            glass_mat = create_glass_material()
            assign_material(glass, glass_mat)
            objects.append(glass)

            # Frame
            frame_col = str(gwin.get("frame_colour", "white")).lower()
            frame_hex = colour_name_to_hex(frame_col) if frame_col else trim_hex
            frame_mat = get_or_create_material(f"mat_dframe_{frame_hex.lstrip('#')}",
                                                colour_hex=frame_hex, roughness=0.5)
            frame_thick = 0.04
            for fname, fscale, floc in [
                ("top", (gw_w + frame_thick * 2, 0.03, frame_thick),
                 (dx, dy + d_depth / 2 + 0.08, dz_base + d_h * 0.3 + gw_h / 2)),
                ("bot", (gw_w + frame_thick * 2, 0.03, frame_thick),
                 (dx, dy + d_depth / 2 + 0.08, dz_base + d_h * 0.3 - gw_h / 2)),
                ("left", (frame_thick, 0.03, gw_h),
                 (dx - gw_w / 2 - frame_thick / 2, dy + d_depth / 2 + 0.08, dz_base + d_h * 0.3)),
                ("right", (frame_thick, 0.03, gw_h),
                 (dx + gw_w / 2 + frame_thick / 2, dy + d_depth / 2 + 0.08, dz_base + d_h * 0.3)),
            ]:
                bpy.ops.mesh.primitive_cube_add(size=1)
                fr = bpy.context.active_object
                fr.name = f"dormer_frame_{fname}_{bldg_id}_{di}"
                fr.scale = fscale
                bpy.ops.object.transform_apply(scale=True)
                fr.location = floc
                assign_material(fr, frame_mat)
                objects.append(fr)

    return objects


def create_fascia_boards(params, wall_h, width, depth, bldg_id=""):
    """Create fascia and soffit boards along eaves and rakes of gable roofs."""
    roof_type = str(params.get("roof_type", "gable")).lower()
    if "flat" in roof_type:
        return []

    trim_hex = get_trim_hex(params)
    # Check for fascia colour in params
    rd = params.get("roof_detail", {})
    fascia_hex = trim_hex
    if isinstance(rd, dict):
        fc = rd.get("fascia_colour_hex", "")
        if fc and fc.startswith("#"):
            fascia_hex = fc

    mat = get_or_create_material(f"mat_fascia_{fascia_hex.lstrip('#')}",
                                  colour_hex=fascia_hex, roughness=0.5)

    pitch = params.get("roof_pitch_deg", 35)
    pitch_rad = math.radians(pitch)
    ridge_h = (width / 2) * math.tan(pitch_rad)

    rd2 = params.get("roof_detail", {})
    eave_mm = 300
    if isinstance(rd2, dict):
        eave_mm = rd2.get("eave_overhang_mm", 300)
    else:
        eave_mm = params.get("eave_overhang_mm", 300)
    overhang_eave = eave_mm / 1000.0
    overhang_side = overhang_eave * 0.5
    half_w = width / 2 + overhang_side

    fascia_h = 0.12  # fascia board height
    fascia_d = 0.025  # fascia board thickness

    objects = []

    # Eave fascia — front horizontal board
    bpy.ops.mesh.primitive_cube_add(size=1)
    f_front = bpy.context.active_object
    f_front.name = f"fascia_front_{bldg_id}"
    f_front.scale = (half_w * 2, fascia_d, fascia_h)
    bpy.ops.object.transform_apply(scale=True)
    f_front.location = (0, overhang_eave, wall_h - fascia_h)
    assign_material(f_front, mat)
    objects.append(f_front)

    # Eave fascia — back
    bpy.ops.mesh.primitive_cube_add(size=1)
    f_back = bpy.context.active_object
    f_back.name = f"fascia_back_{bldg_id}"
    f_back.scale = (half_w * 2, fascia_d, fascia_h)
    bpy.ops.object.transform_apply(scale=True)
    f_back.location = (0, -depth - overhang_eave, wall_h - fascia_h)
    assign_material(f_back, mat)
    objects.append(f_back)

    # Rake boards (along gable slope) — front gable, left and right
    rake_len = math.sqrt((width / 2 + overhang_side) ** 2 + ridge_h ** 2)
    rake_angle = math.atan2(ridge_h, width / 2 + overhang_side)

    for side, sign in [("L", -1), ("R", 1)]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        rake = bpy.context.active_object
        rake.name = f"fascia_rake_{side}_{bldg_id}"
        rake.scale = (rake_len, fascia_d, fascia_h)
        bpy.ops.object.transform_apply(scale=True)
        # Position at midpoint of rake
        mid_x = sign * (width / 4 + overhang_side / 2)
        mid_z = wall_h + ridge_h / 2
        rake.location = (mid_x, overhang_eave + fascia_d, mid_z)
        rake.rotation_euler.y = sign * rake_angle
        assign_material(rake, mat)
        objects.append(rake)

    # Soffit boards (horizontal underside of overhang) — front
    bpy.ops.mesh.primitive_cube_add(size=1)
    soffit = bpy.context.active_object
    soffit.name = f"soffit_front_{bldg_id}"
    soffit.scale = (half_w * 2, overhang_eave, 0.015)
    bpy.ops.object.transform_apply(scale=True)
    soffit.location = (0, overhang_eave / 2, wall_h - fascia_h)
    soffit_mat = get_or_create_material("mat_soffit", colour_hex="#E8E0D0", roughness=0.6)
    assign_material(soffit, soffit_mat)
    objects.append(soffit)

    # Soffit — back
    bpy.ops.mesh.primitive_cube_add(size=1)
    soffit_b = bpy.context.active_object
    soffit_b.name = f"soffit_back_{bldg_id}"
    soffit_b.scale = (half_w * 2, overhang_eave, 0.015)
    bpy.ops.object.transform_apply(scale=True)
    soffit_b.location = (0, -depth - overhang_eave / 2, wall_h - fascia_h)
    assign_material(soffit_b, soffit_mat)
    objects.append(soffit_b)

    return objects


def create_parapet_coping(params, wall_h, width, depth, bldg_id=""):
    """Create parapet walls with metal coping cap for flat-roofed buildings."""
    roof_type = str(params.get("roof_type", "")).lower()
    if "flat" not in roof_type:
        return []

    # Get parapet dimensions
    rd = params.get("roof_detail", {})
    parapet_h = 0.3
    parapet_material = "brick"
    coping = True

    if isinstance(rd, dict):
        parapet_h = rd.get("parapet_height_mm", 300) / 1000.0
        parapet_material = str(rd.get("parapet_material", "brick")).lower()
        if rd.get("parapet") is False:
            return []
    else:
        # Check top-level cornice
        cornice = params.get("cornice", {})
        if isinstance(cornice, dict):
            parapet_h = cornice.get("height_mm", 300) / 1000.0

    facade_hex = get_facade_hex(params)
    wall_thick = 0.2

    if "brick" in parapet_material:
        parapet_mat = create_brick_material(f"mat_parapet_{facade_hex.lstrip('#')}",
                                             facade_hex)
    else:
        parapet_mat = get_or_create_material(f"mat_parapet_{facade_hex.lstrip('#')}",
                                              colour_hex=facade_hex)

    coping_mat = get_or_create_material("mat_coping", colour_hex="#8A8A8A", roughness=0.3)

    objects = []

    # Four parapet walls
    segments = [
        ("front", (width, wall_thick, parapet_h), (0, 0, wall_h + parapet_h / 2)),
        ("back", (width, wall_thick, parapet_h), (0, -depth, wall_h + parapet_h / 2)),
        ("left", (wall_thick, depth, parapet_h), (-width / 2, -depth / 2, wall_h + parapet_h / 2)),
        ("right", (wall_thick, depth, parapet_h), (width / 2, -depth / 2, wall_h + parapet_h / 2)),
    ]

    for name, scale, loc in segments:
        bpy.ops.mesh.primitive_cube_add(size=1)
        pw = bpy.context.active_object
        pw.name = f"parapet_{name}_{bldg_id}"
        pw.scale = scale
        bpy.ops.object.transform_apply(scale=True)
        pw.location = loc
        assign_material(pw, parapet_mat)
        objects.append(pw)

    # Metal coping cap on top of parapet
    coping_h = 0.04
    coping_overhang = 0.03
    coping_segments = [
        ("front", (width + coping_overhang * 2, wall_thick + coping_overhang * 2, coping_h),
         (0, 0, wall_h + parapet_h + coping_h / 2)),
        ("back", (width + coping_overhang * 2, wall_thick + coping_overhang * 2, coping_h),
         (0, -depth, wall_h + parapet_h + coping_h / 2)),
        ("left", (wall_thick + coping_overhang * 2, depth + wall_thick * 2 + coping_overhang * 2, coping_h),
         (-width / 2, -depth / 2, wall_h + parapet_h + coping_h / 2)),
        ("right", (wall_thick + coping_overhang * 2, depth + wall_thick * 2 + coping_overhang * 2, coping_h),
         (width / 2, -depth / 2, wall_h + parapet_h + coping_h / 2)),
    ]

    for name, scale, loc in coping_segments:
        bpy.ops.mesh.primitive_cube_add(size=1)
        cap = bpy.context.active_object
        cap.name = f"coping_{name}_{bldg_id}"
        cap.scale = scale
        bpy.ops.object.transform_apply(scale=True)
        cap.location = loc
        assign_material(cap, coping_mat)
        objects.append(cap)

    return objects


def create_gabled_parapet(params, wall_h, width, depth, bldg_id=""):
    """Create a gabled parapet — a decorative wall extending above roofline at the facade."""
    rd = params.get("roof_detail", {})
    gp = None
    if isinstance(rd, dict):
        gp = rd.get("gabled_parapet", {})
    if not isinstance(gp, dict) or not gp.get("present", False):
        return []

    objects = []
    parapet_h = gp.get("height_m", 0.8)
    facade_hex = get_facade_hex(params)
    wall_mat = create_brick_material(f"mat_gparapet_{facade_hex.lstrip('#')}", facade_hex)

    # Triangular parapet wall at the front face, extending above the eave line
    # with a small gable peak centred on the facade
    half_w = width / 2
    peak_z = wall_h + parapet_h
    eave_z = wall_h
    wall_thick = 0.15

    bm = bmesh.new()
    # Front face vertices (triangular gable shape)
    v0 = bm.verts.new((-half_w, 0, eave_z))
    v1 = bm.verts.new((half_w, 0, eave_z))
    v2 = bm.verts.new((half_w, 0, eave_z + parapet_h * 0.3))
    v3 = bm.verts.new((0, 0, peak_z))
    v4 = bm.verts.new((-half_w, 0, eave_z + parapet_h * 0.3))

    # Back face vertices (offset by wall thickness)
    v5 = bm.verts.new((-half_w, -wall_thick, eave_z))
    v6 = bm.verts.new((half_w, -wall_thick, eave_z))
    v7 = bm.verts.new((half_w, -wall_thick, eave_z + parapet_h * 0.3))
    v8 = bm.verts.new((0, -wall_thick, peak_z))
    v9 = bm.verts.new((-half_w, -wall_thick, eave_z + parapet_h * 0.3))

    # Front face
    bm.faces.new([v0, v4, v3, v2, v1])
    # Back face
    bm.faces.new([v5, v6, v7, v8, v9])
    # Top left slope
    bm.faces.new([v4, v9, v8, v3])
    # Top right slope
    bm.faces.new([v3, v8, v7, v2])
    # Left side
    bm.faces.new([v0, v5, v9, v4])
    # Right side
    bm.faces.new([v1, v2, v7, v6])
    # Bottom
    bm.faces.new([v0, v1, v6, v5])

    mesh = bpy.data.meshes.new(f"gabled_parapet_{bldg_id}")
    bm.to_mesh(mesh)
    bm.free()

    parapet_obj = bpy.data.objects.new(f"gabled_parapet_{bldg_id}", mesh)
    bpy.context.collection.objects.link(parapet_obj)
    assign_material(parapet_obj, wall_mat)
    objects.append(parapet_obj)

    # Optional coping strip along the gable edges
    trim_hex = get_trim_hex(params)
    coping_mat = get_or_create_material(f"mat_gp_coping_{trim_hex.lstrip('#')}",
                                         colour_hex=trim_hex, roughness=0.3)
    slope_len = math.sqrt((half_w) ** 2 + (parapet_h * 0.7) ** 2)
    slope_angle = math.atan2(parapet_h * 0.7, half_w)

    for side in (-1, 1):
        bpy.ops.mesh.primitive_cube_add(size=1)
        coping = bpy.context.active_object
        coping.name = f"gp_coping_{'L' if side == -1 else 'R'}_{bldg_id}"
        coping.scale = (slope_len, wall_thick + 0.02, 0.04)
        bpy.ops.object.transform_apply(scale=True)
        coping.location = (side * half_w / 2, -wall_thick / 2, eave_z + parapet_h * 0.3 + (parapet_h * 0.7) / 2)
        coping.rotation_euler = (0, side * slope_angle, 0)
        assign_material(coping, coping_mat)
        objects.append(coping)

    return objects


def create_turned_posts(porch_objs, params, facade_width):
    """Replace simple cylinder porch posts with turned Victorian posts (vase-and-ring)."""
    porch_data = params.get("porch", {})
    if not isinstance(porch_data, dict):
        return porch_objs

    posts_data = porch_data.get("posts", {})
    if not isinstance(posts_data, dict):
        return porch_objs

    style = str(posts_data.get("style", posts_data.get("type", ""))).lower()
    if "turned" not in style and "victorian" not in style:
        return porch_objs

    post_colour = posts_data.get("colour_hex", "#3A2A20")
    post_mat = get_or_create_material(f"mat_turned_post_{post_colour.lstrip('#')}",
                                       colour_hex=post_colour, roughness=0.55)

    # Find and replace existing porch_post objects
    new_objs = []
    for obj in porch_objs:
        if not obj or not obj.name.startswith("porch_post_"):
            new_objs.append(obj)
            continue

        # Get post position and dimensions from existing cylinder
        loc = obj.location.copy()
        sz = obj.dimensions.z  # post height

        # Remove old cylinder
        bpy.data.objects.remove(obj, do_unlink=True)

        # Build turned post with lathe-like profile using stacked segments
        post_parts = []
        base_r = 0.05
        # Start at bottom of post, extend slightly to close any gap
        z_bottom = loc.z - sz / 2
        z_top = loc.z + sz / 2 + 0.06  # extend into beam to ensure no gap
        total_h = z_top - z_bottom
        z_cursor = z_bottom

        # Square plinth base
        bpy.ops.mesh.primitive_cube_add(size=1)
        plinth = bpy.context.active_object
        plinth.name = f"turned_plinth_{loc.x:.1f}"
        plinth.scale = (0.09, 0.09, 0.08)
        bpy.ops.object.transform_apply(scale=True)
        plinth.location = (loc.x, loc.y, z_cursor + 0.04)
        assign_material(plinth, post_mat)
        post_parts.append(plinth)
        z_cursor += 0.08

        # Main shaft segments: ring-vase-ring-vase-ring profile
        shaft_h = total_h - 0.16  # minus plinth and cap
        seg_h = shaft_h / 7

        profiles = [
            (base_r * 0.8, seg_h * 0.5),   # thin ring
            (base_r * 1.2, seg_h * 1.5),   # vase bulge
            (base_r * 0.7, seg_h * 0.4),   # narrow neck
            (base_r * 0.9, seg_h * 1.2),   # ring
            (base_r * 0.7, seg_h * 0.4),   # narrow neck
            (base_r * 1.1, seg_h * 1.3),   # vase bulge
            (base_r * 0.8, seg_h * 0.7),   # thin ring top
        ]

        for radius, height in profiles:
            bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=height, vertices=8)
            seg = bpy.context.active_object
            seg.name = f"turned_seg_{loc.x:.1f}"
            seg.location = (loc.x, loc.y, z_cursor + height / 2)
            assign_material(seg, post_mat)
            post_parts.append(seg)
            z_cursor += height

        # Cap block
        bpy.ops.mesh.primitive_cube_add(size=1)
        cap = bpy.context.active_object
        cap.name = f"turned_cap_{loc.x:.1f}"
        cap.scale = (0.09, 0.09, 0.08)
        bpy.ops.object.transform_apply(scale=True)
        cap.location = (loc.x, loc.y, z_cursor + 0.04)
        assign_material(cap, post_mat)
        post_parts.append(cap)

        # Join all parts into a single smooth post
        if len(post_parts) > 1:
            bpy.ops.object.select_all(action='DESELECT')
            for p in post_parts:
                p.select_set(True)
            bpy.context.view_layer.objects.active = post_parts[0]
            bpy.ops.object.join()
            joined_post = bpy.context.active_object
            joined_post.name = f"turned_post_{loc.x:.1f}"
            # Smooth shading for seamless look
            bpy.ops.object.shade_smooth()
            new_objs.append(joined_post)
        else:
            new_objs.extend(post_parts)

    return new_objs


def create_storefront_awning(params, facade_width, bldg_id=""):
    """Create commercial storefront awning with signage."""
    sf_data = params.get("storefront", {})
    if not isinstance(sf_data, dict):
        return []

    awning_data = sf_data.get("awning", {})
    if not isinstance(awning_data, dict) or not awning_data:
        return []

    objects = []

    aw_w = awning_data.get("width_m", facade_width)
    aw_proj = awning_data.get("projection_m", 1.2)
    aw_h_top = awning_data.get("height_at_fascia_m", 2.8)
    aw_h_bot = awning_data.get("height_at_drip_edge_m", 2.3)
    aw_colour = str(awning_data.get("colour", "blue")).lower()

    # Map colour name to hex
    awning_colours = {
        "blue": "#2060A0", "red": "#A02020", "green": "#206020",
        "yellow": "#C0A020", "white": "#E8E8E8", "black": "#2A2A2A",
    }
    aw_hex = "#2060A0"
    for key, val in awning_colours.items():
        if key in aw_colour:
            aw_hex = val
            break

    aw_mat = get_or_create_material(f"mat_awning_{aw_hex.lstrip('#')}",
                                     colour_hex=aw_hex, roughness=0.7)

    # Awning as a sloped plane
    bm = bmesh.new()
    hw = aw_w / 2
    v0 = bm.verts.new((-hw, 0, aw_h_top))
    v1 = bm.verts.new((hw, 0, aw_h_top))
    v2 = bm.verts.new((hw, aw_proj, aw_h_bot))
    v3 = bm.verts.new((-hw, aw_proj, aw_h_bot))
    bm.faces.new([v0, v1, v2, v3])

    mesh = bpy.data.meshes.new(f"awning_{bldg_id}")
    bm.to_mesh(mesh)
    bm.free()

    aw_obj = bpy.data.objects.new(f"awning_{bldg_id}", mesh)
    bpy.context.collection.objects.link(aw_obj)

    # Solidify for thickness
    mod = aw_obj.modifiers.new("Solidify", 'SOLIDIFY')
    mod.thickness = 0.03
    mod.offset = -1
    bpy.context.view_layer.objects.active = aw_obj
    bpy.ops.object.modifier_apply(modifier=mod.name)

    assign_material(aw_obj, aw_mat)
    objects.append(aw_obj)

    # Valance (scalloped bottom edge) — simple strip along the front
    bpy.ops.mesh.primitive_cube_add(size=1)
    val = bpy.context.active_object
    val.name = f"awning_valance_{bldg_id}"
    val.scale = (aw_w, 0.015, 0.12)
    bpy.ops.object.transform_apply(scale=True)
    val.location = (0, aw_proj, aw_h_bot - 0.06)
    assign_material(val, aw_mat)
    objects.append(val)

    # Signage
    signage = sf_data.get("signage", {})
    primary = signage.get("primary", {}) if isinstance(signage, dict) else {}
    if isinstance(primary, dict) and primary:
        sign_w = primary.get("width_m", 4.0)
        sign_h = primary.get("height_m", 0.5)
        sign_bg = primary.get("background", "white").lower()
        sign_hex = "#F0F0F0" if "white" in sign_bg else "#3A3A3A"

        sign_mat = get_or_create_material(f"mat_sign_{bldg_id}", colour_hex=sign_hex, roughness=0.4)

        bpy.ops.mesh.primitive_cube_add(size=1)
        sign = bpy.context.active_object
        sign.name = f"sign_{bldg_id}"
        sign.scale = (sign_w, 0.03, sign_h)
        bpy.ops.object.transform_apply(scale=True)
        sign.location = (0, 0.02, aw_h_top + sign_h / 2 + 0.05)
        assign_material(sign, sign_mat)
        objects.append(sign)

    return objects


def create_foundation(params, width, depth, bldg_id=""):
    """Create visible foundation/water table at ground level."""
    foundation_h = 0.2
    foundation_proj = 0.03  # slight projection from wall face

    stone_mat = create_stone_material("mat_foundation", "#7A7A78")

    objects = []

    # Front
    bpy.ops.mesh.primitive_cube_add(size=1)
    ff = bpy.context.active_object
    ff.name = f"foundation_front_{bldg_id}"
    ff.scale = (width + foundation_proj * 2, foundation_proj * 2, foundation_h)
    bpy.ops.object.transform_apply(scale=True)
    ff.location = (0, foundation_proj, foundation_h / 2)
    assign_material(ff, stone_mat)
    objects.append(ff)

    # Back
    bpy.ops.mesh.primitive_cube_add(size=1)
    fb = bpy.context.active_object
    fb.name = f"foundation_back_{bldg_id}"
    fb.scale = (width + foundation_proj * 2, foundation_proj * 2, foundation_h)
    bpy.ops.object.transform_apply(scale=True)
    fb.location = (0, -depth - foundation_proj, foundation_h / 2)
    assign_material(fb, stone_mat)
    objects.append(fb)

    # Left side
    bpy.ops.mesh.primitive_cube_add(size=1)
    fl = bpy.context.active_object
    fl.name = f"foundation_left_{bldg_id}"
    fl.scale = (foundation_proj * 2, depth + foundation_proj * 2, foundation_h)
    bpy.ops.object.transform_apply(scale=True)
    fl.location = (-width / 2 - foundation_proj, -depth / 2, foundation_h / 2)
    assign_material(fl, stone_mat)
    objects.append(fl)

    # Right side
    bpy.ops.mesh.primitive_cube_add(size=1)
    fr = bpy.context.active_object
    fr.name = f"foundation_right_{bldg_id}"
    fr.scale = (foundation_proj * 2, depth + foundation_proj * 2, foundation_h)
    bpy.ops.object.transform_apply(scale=True)
    fr.location = (width / 2 + foundation_proj, -depth / 2, foundation_h / 2)
    assign_material(fr, stone_mat)
    objects.append(fr)

    return objects


def create_gutters(params, wall_h, width, depth, bldg_id=""):
    """Create gutters along eaves and downspouts at corners."""
    roof_type = str(params.get("roof_type", "gable")).lower()
    if "flat" in roof_type:
        return []  # flat roofs have internal drainage

    gutter_mat = get_or_create_material("mat_gutter", colour_hex="#4A4A4A", roughness=0.4)

    objects = []
    gutter_r = 0.04

    rd = params.get("roof_detail", {})
    eave_mm = 300
    if isinstance(rd, dict):
        eave_mm = rd.get("eave_overhang_mm", 300)
    else:
        eave_mm = params.get("eave_overhang_mm", 300)
    overhang = eave_mm / 1000.0

    # Front gutter (horizontal along eave)
    bpy.ops.mesh.primitive_cylinder_add(radius=gutter_r, depth=width + overhang,
                                         vertices=8)
    gf = bpy.context.active_object
    gf.name = f"gutter_front_{bldg_id}"
    gf.rotation_euler.y = math.pi / 2
    gf.location = (0, overhang, wall_h - 0.02)
    assign_material(gf, gutter_mat)
    objects.append(gf)

    # Back gutter
    bpy.ops.mesh.primitive_cylinder_add(radius=gutter_r, depth=width + overhang,
                                         vertices=8)
    gb = bpy.context.active_object
    gb.name = f"gutter_back_{bldg_id}"
    gb.rotation_euler.y = math.pi / 2
    gb.location = (0, -depth - overhang, wall_h - 0.02)
    assign_material(gb, gutter_mat)
    objects.append(gb)

    # Downspouts at front corners
    for side, sx in [("L", -width / 2 - 0.02), ("R", width / 2 + 0.02)]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.025, depth=wall_h, vertices=6)
        ds = bpy.context.active_object
        ds.name = f"downspout_{side}_{bldg_id}"
        ds.location = (sx, overhang + 0.02, wall_h / 2)
        assign_material(ds, gutter_mat)
        objects.append(ds)

    return objects


def create_chimney_caps(params, wall_h, ridge_height, width, bldg_id=""):
    """Add flared corbelled caps to existing chimneys."""
    chimney_data = params.get("chimneys", params.get("roof_detail", {}).get("chimneys", {}))
    if not isinstance(chimney_data, dict):
        return []

    objects = []
    facade_hex = get_facade_hex(params)
    cap_mat = create_brick_material(f"mat_chimcap_{facade_hex.lstrip('#')}", facade_hex)
    stone_cap = get_or_create_material("mat_chimcap_stone", colour_hex="#8A8A88", roughness=0.7)

    depth = params.get("facade_depth_m", DEFAULT_DEPTH)
    hw = width / 2

    for key in chimney_data:
        ch = chimney_data[key]
        if not isinstance(ch, dict):
            continue

        ch_w = ch.get("width_m", 0.6)
        ch_d = ch.get("depth_m", 0.4)
        above = ch.get("height_above_ridge_m", 1.0)
        pos = str(ch.get("position", "")).lower()

        # Match chimney x position (flush at building edge)
        if "left" in pos:
            cx = -hw + ch_w / 2
        elif "right" in pos:
            cx = hw - ch_w / 2
        else:
            cx = 0

        # Match chimney y position
        ch_y = -depth * 0.3

        ch_top_z = wall_h + ridge_height + above

        # Corbelled flare (wider course below cap)
        bpy.ops.mesh.primitive_cube_add(size=1)
        flare = bpy.context.active_object
        flare.name = f"chimcap_flare_{key}_{bldg_id}"
        flare.scale = (ch_w + 0.08, ch_d + 0.08, 0.06)
        bpy.ops.object.transform_apply(scale=True)
        flare.location = (cx, ch_y, ch_top_z - 0.03)
        assign_material(flare, cap_mat)
        objects.append(flare)

        # Second corbel course
        bpy.ops.mesh.primitive_cube_add(size=1)
        flare2 = bpy.context.active_object
        flare2.name = f"chimcap_flare2_{key}_{bldg_id}"
        flare2.scale = (ch_w + 0.12, ch_d + 0.12, 0.04)
        bpy.ops.object.transform_apply(scale=True)
        flare2.location = (cx, ch_y, ch_top_z + 0.02)
        assign_material(flare2, cap_mat)
        objects.append(flare2)

        # Stone/concrete cap slab
        bpy.ops.mesh.primitive_cube_add(size=1)
        slab = bpy.context.active_object
        slab.name = f"chimcap_slab_{key}_{bldg_id}"
        slab.scale = (ch_w + 0.16, ch_d + 0.16, 0.04)
        bpy.ops.object.transform_apply(scale=True)
        slab.location = (cx, ch_y, ch_top_z + 0.06)
        assign_material(slab, stone_cap)
        objects.append(slab)

    return objects


def create_porch_lattice(params, facade_width, bldg_id=""):
    """Create lattice skirt panel under porch deck using contained diagonal bars."""
    porch_data = params.get("porch", {})
    if not isinstance(porch_data, dict):
        return []
    if not porch_data.get("present", porch_data.get("type")):
        return []

    porch_w = porch_data.get("width_m", facade_width)
    floor_h = porch_data.get("floor_height_above_grade_m",
              porch_data.get("deck_height_above_sidewalk_m", 0.5))

    if floor_h < 0.2:
        return []

    porch_d = porch_data.get("depth_m", 2.0)
    trim_hex = get_trim_hex(params)
    lattice_mat = get_or_create_material(f"mat_lattice_{trim_hex.lstrip('#')}",
                                          colour_hex=trim_hex, roughness=0.6)

    objects = []

    # Front lattice — contained panel using bmesh for precise clipping
    # Create diagonal grid within the rectangle [0, floor_h] x [-porch_w/2, porch_w/2]
    bm = bmesh.new()
    bar_w = 0.012
    spacing = 0.1  # diamond spacing
    hw = porch_w / 2

    # Diagonal bars direction 1 (top-left to bottom-right)
    x = -hw
    while x < hw + floor_h:
        # Bar runs from top-left to bottom-right, clipped to panel bounds
        x0, z0 = x, floor_h
        x1, z1 = x + floor_h, 0

        # Clip to panel bounds
        if x0 < -hw:
            z0 = floor_h - (-hw - x0)
            x0 = -hw
        if x1 > hw:
            z1 = floor_h - (hw - x + floor_h) if (x + floor_h - hw) < floor_h else x1 - hw
            z1 = (x1 - hw) / floor_h * floor_h
            z1 = floor_h * (1.0 - (hw - x) / floor_h) if (hw - x) < floor_h else 0
            x1_new = min(x1, hw)
            z1 = max(0, z0 - (x1_new - x0))
            x1 = x1_new
        if z0 < 0:
            z0 = 0
        if z1 > floor_h:
            z1 = floor_h

        if x0 < hw and x1 > -hw and z0 > 0.01:
            v0 = bm.verts.new((x0 - bar_w / 2, 0, z0))
            v1 = bm.verts.new((x0 + bar_w / 2, 0, z0))
            v2 = bm.verts.new((x1 + bar_w / 2, 0, z1))
            v3 = bm.verts.new((x1 - bar_w / 2, 0, z1))
            bm.faces.new([v0, v1, v2, v3])

        x += spacing

    # Diagonal bars direction 2 (bottom-left to top-right — mirror of direction 1)
    x = -hw
    while x < hw + floor_h:
        # Bar runs from bottom-left to top-right
        x0, z0 = x, 0
        x1, z1 = x + floor_h, floor_h

        # Clip to panel bounds
        if x0 < -hw:
            z0 = -hw - x0
            x0 = -hw
        if x1 > hw:
            z1 = floor_h - (x1 - hw)
            x1 = hw
        if z0 < 0:
            z0 = 0
        if z1 > floor_h:
            z1 = floor_h
        if z0 > floor_h:
            x += spacing
            continue

        if x0 < hw and x1 > -hw and z1 > z0 + 0.01:
            v0 = bm.verts.new((x0 - bar_w / 2, 0, z0))
            v1 = bm.verts.new((x0 + bar_w / 2, 0, z0))
            v2 = bm.verts.new((x1 + bar_w / 2, 0, z1))
            v3 = bm.verts.new((x1 - bar_w / 2, 0, z1))
            bm.faces.new([v0, v1, v2, v3])

        x += spacing

    mesh = bpy.data.meshes.new(f"lattice_{bldg_id}")
    bm.to_mesh(mesh)
    bm.free()

    lattice_obj = bpy.data.objects.new(f"lattice_{bldg_id}", mesh)
    bpy.context.collection.objects.link(lattice_obj)
    lattice_obj.location = (0, porch_d, 0)

    # Give thickness
    mod = lattice_obj.modifiers.new("Solidify", 'SOLIDIFY')
    mod.thickness = 0.02
    mod.offset = 0
    bpy.context.view_layer.objects.active = lattice_obj
    bpy.ops.object.modifier_apply(modifier=mod.name)

    assign_material(lattice_obj, lattice_mat)
    objects.append(lattice_obj)

    # Frame border around lattice panel
    frame_mat = get_or_create_material(f"mat_lattice_frame_{trim_hex.lstrip('#')}",
                                        colour_hex=trim_hex, roughness=0.55)
    for fname, fscale, floc in [
        ("top", (porch_w, 0.03, 0.03), (0, porch_d, floor_h)),
        ("bot", (porch_w, 0.03, 0.03), (0, porch_d, 0.015)),
        ("left", (0.03, 0.03, floor_h), (-porch_w / 2, porch_d, floor_h / 2)),
        ("right", (0.03, 0.03, floor_h), (porch_w / 2, porch_d, floor_h / 2)),
    ]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        fr = bpy.context.active_object
        fr.name = f"lattice_frame_{fname}_{bldg_id}"
        fr.scale = fscale
        bpy.ops.object.transform_apply(scale=True)
        fr.location = floc
        assign_material(fr, frame_mat)
        objects.append(fr)

    return objects


def create_step_handrails(params, facade_width, bldg_id=""):
    """Create metal handrails alongside porch steps."""
    porch_data = params.get("porch", {})
    if not isinstance(porch_data, dict):
        return []
    if not porch_data.get("present", porch_data.get("type")):
        return []

    steps_data = porch_data.get("steps", porch_data.get("stairs", {}))
    if not isinstance(steps_data, dict):
        return []

    step_count = steps_data.get("count", 3)
    floor_h = porch_data.get("floor_height_above_grade_m", 0.5)
    porch_d = porch_data.get("depth_m", 2.0)
    step_w = steps_data.get("width_m", 1.2)
    run = 0.28

    # Step x-offset (must match create_porch step placement)
    step_pos = str(steps_data.get("position", "center")).lower()
    porch_w = porch_data.get("width_m", facade_width)
    if "left" in step_pos:
        step_x = -porch_w / 4
    elif "right" in step_pos:
        step_x = porch_w / 4
    else:
        step_x = 0.0

    if step_count < 2:
        return []

    rail_mat = get_or_create_material("mat_handrail", colour_hex="#2A2A2A", roughness=0.3)
    objects = []

    total_run = step_count * run
    rail_len = math.sqrt(total_run ** 2 + floor_h ** 2)
    rail_angle = math.atan2(floor_h, total_run)

    for side, sx in [("L", step_x - step_w / 2 - 0.04), ("R", step_x + step_w / 2 + 0.04)]:
        # Sloped rail
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=rail_len, vertices=8)
        rail = bpy.context.active_object
        rail.name = f"handrail_{side}_{bldg_id}"
        rail.rotation_euler.x = math.pi / 2 - rail_angle
        rail.location = (sx, porch_d + total_run / 2, floor_h / 2 + 0.4)
        assign_material(rail, rail_mat)
        objects.append(rail)

        # Bottom post — from ground level (z=0) up to rail height
        bot_post_h = 0.9
        bpy.ops.mesh.primitive_cylinder_add(radius=0.015, depth=bot_post_h, vertices=8)
        bp = bpy.context.active_object
        bp.name = f"rail_post_bot_{side}_{bldg_id}"
        bp.location = (sx, porch_d + total_run, bot_post_h / 2)
        assign_material(bp, rail_mat)
        objects.append(bp)

        # Top post — from porch deck to rail height
        top_post_h = 0.9
        bpy.ops.mesh.primitive_cylinder_add(radius=0.015, depth=top_post_h, vertices=8)
        tp = bpy.context.active_object
        tp.name = f"rail_post_top_{side}_{bldg_id}"
        tp.location = (sx, porch_d, floor_h + top_post_h / 2)
        assign_material(tp, rail_mat)
        objects.append(tp)

    return objects


def get_trim_hex(params):
    """Get trim colour hex from params."""
    cp = params.get("colour_palette", {})
    if isinstance(cp, dict):
        trim = cp.get("trim", {})
        if isinstance(trim, dict):
            return trim.get("hex_approx", infer_hex_from_text(trim, default="#F0F0F0"))
    fd = params.get("facade_detail", {})
    if isinstance(fd, dict):
        tc = fd.get("trim_colour", "")
        if isinstance(tc, str):
            return infer_hex_from_text(tc, default="#F0F0F0")
    dec = params.get("decorative_elements", {})
    if isinstance(dec, dict):
        scheme = dec.get("trim_colour_scheme", {})
        if isinstance(scheme, dict):
            return infer_hex_from_text(scheme.get("primary_trim", ""), default="#F0F0F0")
    return "#F0F0F0"


# ---------------------------------------------------------------------------
# Main building generator
# ---------------------------------------------------------------------------

def generate_multi_volume(params, offset=(0, 0, 0)):
    """Generate a multi-volume building (like 132 Bellevue fire station)."""
    address = "unknown"
    meta = params.get("_meta", {})
    if isinstance(meta, dict):
        address = meta.get("address", "unknown")

    bldg_id = address.replace(" ", "_").replace(",", "").replace(".", "")
    print(f"[GENERATE MULTI-VOLUME] {address}")

    volumes = params.get("volumes", [])
    all_objs = []

    # Track x position for placing volumes side by side
    total_width = sum(v.get("width_m", 5) for v in volumes)
    x_cursor = -total_width / 2

    def log_volume_feature(name, before_count):
        delta = len(all_objs) - before_count
        if delta > 0:
            print(f"    {name}: {delta} elements")

    def _obj_valid(o):
        try:
            return o is not None and o.name is not None
        except ReferenceError:
            return False

    def join_by_prefix(prefix, objs_list):
        """Join all objects whose name starts with prefix into a single mesh."""
        targets = []
        for o in objs_list:
            try:
                if o and o.name.startswith(prefix):
                    targets.append(o)
            except ReferenceError:
                continue
        if len(targets) < 2:
            return objs_list
        bpy.ops.object.select_all(action='DESELECT')
        for o in targets:
            o.select_set(True)
        bpy.context.view_layer.objects.active = targets[0]
        bpy.ops.object.join()
        joined = bpy.context.active_object
        joined.name = f"{prefix}{bldg_id}"
        new_list = [o for o in objs_list if _obj_valid(o) and o not in targets]
        new_list.append(joined)
        return new_list

    for vi, vol in enumerate(volumes):
        vol_id = vol.get("id", f"vol_{vi}")
        vol_w = vol.get("width_m", 5.0)
        vol_d = vol.get("depth_m", 10.0)
        vol_floors = vol.get("floor_heights_m", [3.5])
        vol_h = sum(vol_floors)
        vol_total_h = vol.get("total_height_m", vol_h)

        print(f"  Volume: {vol_id} ({vol_w}m x {vol_d}m x {vol_total_h}m)")

        # Volume center x
        vol_cx = x_cursor + vol_w / 2

        # Facade material
        fc = str(vol.get("facade_colour", vol.get("facade_material", "brick"))).lower()
        if "glass" in fc or "curtain" in fc:
            vol_hex = "#5A6A7A"
        else:
            vol_hex = infer_hex_from_text(vol.get("facade_colour", ""), vol.get("facade_material", ""), default=get_facade_hex(params))

        mat_type = str(vol.get("facade_material", "brick")).lower()
        mortar_hex = "#8A8A8A"

        if vol_id == "clock_tower":
            # Tall square tower
            outer = create_box(f"tower_walls_{bldg_id}", vol_w, vol_d, vol_total_h,
                               location=(vol_cx, 0, 0))
            inner = create_box(f"tower_inner_{bldg_id}",
                               vol_w - 0.5, vol_d - 0.5, vol_total_h + 0.02,
                               location=(vol_cx, 0, -0.01))
            boolean_cut(outer, inner)
            outer.name = f"tower_{bldg_id}"

            tower_mat = create_brick_material(f"mat_tower_{vol_hex.lstrip('#')}",
                                               vol_hex, mortar_hex)
            assign_material(outer, tower_mat)
            all_objs.append(outer)
            tower_string_course_count = 0

            # Corner treatment: shallow brick pilaster/quoins
            corner_text = json.dumps(vol.get("decorative_elements", {})).lower()
            if "corner_treatment" in vol.get("decorative_elements", {}) or "quoin" in corner_text or "pilaster" in corner_text:
                corner_start = len(all_objs)
                pil_w = 0.12
                pil_proj = 0.04
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        pil = bpy.context.active_object
                        pil.name = f"tower_corner_{sx}_{sy}_{bldg_id}"
                        pil.scale = (pil_w, pil_proj, vol_total_h)
                        bpy.ops.object.transform_apply(scale=True)
                        pil.location = (
                            vol_cx + sx * (vol_w / 2 - pil_w / 2),
                            -vol_d / 2 + sy * (vol_d / 2 - pil_proj / 2),
                            vol_total_h / 2,
                        )
                        assign_material(pil, tower_mat)
                        all_objs.append(pil)
                log_volume_feature("Tower corner treatment", corner_start)

            # String courses between levels
            level_details = vol.get("level_details", [])
            z_acc = 0
            for li, ld in enumerate(level_details):
                lh = ld.get("height_m", 3.5)
                z_acc += lh
                if li < len(level_details) - 1:
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    sc = bpy.context.active_object
                    sc.name = f"tower_sc_{li}_{bldg_id}"
                    sc.scale = (vol_w + 0.06, vol_d + 0.06, 0.06)
                    bpy.ops.object.transform_apply(scale=True)
                    sc.location = (vol_cx, -vol_d / 2, z_acc)
                    stone_mat = create_stone_material("mat_stone_sc", "#C0B8A0")
                    assign_material(sc, stone_mat)
                    all_objs.append(sc)
                    tower_string_course_count += 1
                win_start = len(all_objs)
                # Windows for this level
                wins = ld.get("windows", [])
                for wi, w_spec in enumerate(wins):
                    if not isinstance(w_spec, dict):
                        continue
                    ww = w_spec.get("width_m", 0.5)
                    wh = w_spec.get("height_m", 0.7)
                    wz = z_acc - lh / 2
                    # Glass + frame on front face
                    bpy.ops.mesh.primitive_plane_add(size=1)
                    gl = bpy.context.active_object
                    gl.name = f"tower_glass_{li}_{bldg_id}"
                    gl.scale = (ww * 0.85, 1, wh * 0.85)
                    bpy.ops.object.transform_apply(scale=True)
                    gl.rotation_euler.x = math.pi / 2
                    gl.location = (vol_cx, 0.02, wz)
                    assign_material(gl, create_glass_material())
                    all_objs.append(gl)
                log_volume_feature(f"Tower level {li + 1} windows", win_start)

                clock_start = len(all_objs)
                # Clock face
                clock = ld.get("clock_face", {})
                if isinstance(clock, dict) and clock:
                    diam = clock.get("diameter_m", 1.5)
                    clock_z = z_acc - lh / 2
                    bpy.ops.mesh.primitive_circle_add(
                        radius=diam / 2, vertices=32, fill_type='NGON')
                    cf = bpy.context.active_object
                    cf.name = f"clock_face_{bldg_id}"
                    cf.rotation_euler.x = math.pi / 2
                    cf.location = (vol_cx, 0.16, clock_z)
                    clock_mat = get_or_create_material("mat_clock_face",
                                                        colour_hex="#F0F0F0", roughness=0.3)
                    assign_material(cf, clock_mat)
                    all_objs.append(cf)

                    surround_text = str(clock.get("surround", "")).lower()
                    if "frame" in surround_text or "stone" in surround_text or "brick" in surround_text:
                        bpy.ops.mesh.primitive_torus_add(
                            major_radius=diam / 2 + 0.12,
                            minor_radius=0.06,
                            major_segments=32,
                            minor_segments=10,
                        )
                        ring = bpy.context.active_object
                        ring.name = f"clock_surround_{li}_{bldg_id}"
                        ring.rotation_euler.x = math.pi / 2
                        ring.location = (vol_cx, 0.17, clock_z)
                        surround_hex = get_stone_hex(clock.get("surround", ""), default="#C8C0B0")
                        surround_mat = create_stone_material("mat_clock_surround", surround_hex)
                        assign_material(ring, surround_mat)
                        all_objs.append(ring)

                    # Clock hands (hour + minute)
                    hand_mat = get_or_create_material("mat_clock_hands",
                                                       colour_hex="#1A1A1A", roughness=0.5)
                    for hname, hlen, hangle in [("hour", diam * 0.25, 60), ("min", diam * 0.35, 160)]:
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        hand = bpy.context.active_object
                        hand.name = f"clock_{hname}_{bldg_id}"
                        hand.scale = (0.02, 0.01, hlen)
                        bpy.ops.object.transform_apply(scale=True)
                        hand.location = (vol_cx, 0.18, clock_z)
                        hand.rotation_euler.y = math.radians(hangle)
                        assign_material(hand, hand_mat)
                        all_objs.append(hand)
                log_volume_feature(f"Tower level {li + 1} clock detail", clock_start)

                corbel_start = len(all_objs)
                # Decorative corbel band below parapet or upper tower stages
                parapet_info = ld.get("parapet", {})
                ld_text = json.dumps(ld).lower()
                if ("corbel" in ld_text or "corbelling" in ld_text or
                        (isinstance(parapet_info, dict) and "corbel" in json.dumps(parapet_info).lower())):
                    course_count = 3
                    if "5" in ld_text:
                        course_count = 5
                    elif "4" in ld_text:
                        course_count = 4
                    all_objs.extend(_create_corbel_band(
                        f"tower_corbel_{li}_{bldg_id}",
                        vol_cx,
                        0.02,
                        z_acc - 0.32,
                        vol_w,
                        course_count=course_count,
                        colour_hex=vol_hex,
                    ))
                log_volume_feature(f"Tower level {li + 1} corbelling", corbel_start)

            if tower_string_course_count:
                print(f"    Tower string courses: {tower_string_course_count} elements")

            # Tower parapet
            parapet_start = len(all_objs)
            top_level = level_details[-1] if level_details else {}
            parapet = top_level.get("parapet", {})
            if isinstance(parapet, dict) and parapet:
                ph = parapet.get("height_m", 0.8)
                for side, sc, loc in [
                    ("f", (vol_w, 0.15, ph), (vol_cx, 0, vol_total_h + ph / 2)),
                    ("b", (vol_w, 0.15, ph), (vol_cx, -vol_d, vol_total_h + ph / 2)),
                    ("l", (0.15, vol_d, ph), (vol_cx - vol_w / 2, -vol_d / 2, vol_total_h + ph / 2)),
                    ("r", (0.15, vol_d, ph), (vol_cx + vol_w / 2, -vol_d / 2, vol_total_h + ph / 2)),
                ]:
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    pw = bpy.context.active_object
                    pw.name = f"tower_parapet_{side}_{bldg_id}"
                    pw.scale = sc
                    bpy.ops.object.transform_apply(scale=True)
                    pw.location = loc
                    assign_material(pw, tower_mat)
                    all_objs.append(pw)

                # Coping cap
                bpy.ops.mesh.primitive_cube_add(size=1)
                cap = bpy.context.active_object
                cap.name = f"tower_coping_{bldg_id}"
                cap.scale = (vol_w + 0.1, vol_d + 0.1, 0.06)
                bpy.ops.object.transform_apply(scale=True)
                cap.location = (vol_cx, -vol_d / 2, vol_total_h + ph + 0.03)
                coping_mat = get_or_create_material("mat_coping", colour_hex="#8A8A8A", roughness=0.3)
                assign_material(cap, coping_mat)
                all_objs.append(cap)
            log_volume_feature("Tower parapet/coping", parapet_start)

            vegetation_start = len(all_objs)
            vegetation = top_level.get("vegetation", {})
            if isinstance(vegetation, dict) and vegetation:
                coverage = vegetation.get("coverage_percent", 10)
                tuft_count = max(2, min(8, int(coverage / 2)))
                veg_mat = get_or_create_material("mat_tower_vegetation", colour_hex="#5D6F3A", roughness=0.95)
                for ti in range(tuft_count):
                    fx = ((ti % 3) - 1) * (vol_w * 0.18)
                    fy = ((ti // 3) - 0.5) * (vol_d * 0.18)
                    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.10 + (ti % 2) * 0.03, segments=8, ring_count=6)
                    tuft = bpy.context.active_object
                    tuft.name = f"tower_veg_{ti}_{bldg_id}"
                    tuft.scale.z = 0.6
                    tuft.location = (vol_cx + fx, -vol_d / 2 + fy, vol_total_h + ph + 0.08)
                    assign_material(tuft, veg_mat)
                    all_objs.append(tuft)
            log_volume_feature("Tower vegetation", vegetation_start)

        elif vol_id == "modern_addition":
            # Glass curtain wall building
            outer = create_box(f"modern_walls_{bldg_id}", vol_w, vol_d, vol_h,
                               location=(vol_cx, 0, 0))
            inner = create_box(f"modern_inner_{bldg_id}",
                               vol_w - 0.4, vol_d - 0.4, vol_h + 0.02,
                               location=(vol_cx, 0, -0.01))
            boolean_cut(outer, inner)
            outer.name = f"modern_{bldg_id}"

            # Brick base
            base = vol.get("base", {})
            base_h = base.get("height_m", 1.0) if isinstance(base, dict) else 1.0
            base_mat = create_brick_material(f"mat_modern_base_{vol_hex.lstrip('#')}",
                                              "#B85A3A", mortar_hex)
            assign_material(outer, base_mat)
            all_objs.append(outer)

            # Curtain wall bays
            curtain_start = len(all_objs)
            cw = vol.get("curtain_wall", {})
            if isinstance(cw, dict):
                bay_count = cw.get("bay_count", 4)
                bay_w = cw.get("bay_width_m", 2.2)
                bay_h = cw.get("bay_height_m", 5.5)
                mullion_w = cw.get("mullion_width_mm", 80) / 1000.0

                glass_mat = create_glass_material("mat_curtain_glass")
                mullion_hex = cw.get("mullion_colour", "#2A2A2A")
                if not mullion_hex.startswith("#"):
                    mullion_hex = "#2A2A2A"
                mullion_mat = get_or_create_material("mat_mullion", colour_hex=mullion_hex, roughness=0.4)

                cw_start_x = vol_cx - (bay_count * bay_w) / 2 + bay_w / 2
                cw_z = base_h + bay_h / 2

                for bi in range(bay_count):
                    bx = cw_start_x + bi * bay_w

                    # Glass panel
                    bpy.ops.mesh.primitive_plane_add(size=1)
                    gp = bpy.context.active_object
                    gp.name = f"curtain_glass_{bi}_{bldg_id}"
                    gp.scale = (bay_w - mullion_w, 1, bay_h)
                    bpy.ops.object.transform_apply(scale=True)
                    gp.rotation_euler.x = math.pi / 2
                    gp.location = (bx, 0.16, cw_z)
                    assign_material(gp, glass_mat)
                    all_objs.append(gp)

                    # Vertical mullion (right side of each bay)
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    mul = bpy.context.active_object
                    mul.name = f"mullion_{bi}_{bldg_id}"
                    mul.scale = (mullion_w, 0.08, bay_h)
                    bpy.ops.object.transform_apply(scale=True)
                    mul.location = (bx + bay_w / 2, 0.14, cw_z)
                    assign_material(mul, mullion_mat)
                    all_objs.append(mul)

                # Horizontal mullion at mid height
                bpy.ops.mesh.primitive_cube_add(size=1)
                hmul = bpy.context.active_object
                hmul.name = f"mullion_h_{bldg_id}"
                hmul.scale = (bay_count * bay_w, 0.08, mullion_w)
                bpy.ops.object.transform_apply(scale=True)
                hmul.location = (vol_cx, 0.14, base_h + bay_h / 2)
                assign_material(hmul, mullion_mat)
                all_objs.append(hmul)
            log_volume_feature("Curtain wall", curtain_start)

            # Flat roof
            modern_roof_start = len(all_objs)
            bpy.ops.mesh.primitive_plane_add(size=1)
            mroof = bpy.context.active_object
            mroof.name = f"modern_roof_{bldg_id}"
            mroof.scale = (vol_w + 0.1, vol_d + 0.1, 1)
            bpy.ops.object.transform_apply(scale=True)
            mroof.location = (vol_cx, -vol_d / 2, vol_h + 0.01)
            roof_mat = get_or_create_material("mat_roof_flat_modern", colour_hex="#4A4A4A", roughness=0.9)
            assign_material(mroof, roof_mat)
            all_objs.append(mroof)
            log_volume_feature("Modern roof", modern_roof_start)

        else:
            # Heritage hall or generic volume
            outer = create_box(f"hall_walls_{bldg_id}", vol_w, vol_d, vol_h,
                               location=(vol_cx, 0, 0))
            inner = create_box(f"hall_inner_{bldg_id}",
                               vol_w - 0.5, vol_d - 0.5, vol_h + 0.02,
                               location=(vol_cx, 0, -0.01))
            boolean_cut(outer, inner)
            outer.name = f"hall_{bldg_id}"

            hall_mat = create_brick_material(f"mat_hall_{vol_hex.lstrip('#')}",
                                              vol_hex, mortar_hex)
            assign_material(outer, hall_mat)
            all_objs.append(outer)

            # Engine bay arch (ground floor)
            ground_opening_start = len(all_objs)
            gf = vol.get("ground_floor", {})
            if isinstance(gf, dict):
                primary = gf.get("primary_opening", {})
                if isinstance(primary, dict) and primary:
                    pw = primary.get("width_m", 3.5)
                    ph = primary.get("height_to_crown_m", 4.0)
                    spring = primary.get("spring_line_height_m", 2.8)

                    cutter = create_arch_cutter(f"arch_cut_{bldg_id}", pw, ph, spring,
                                                arch_type="semicircular", depth=0.8)
                    cutter.location.x = vol_cx
                    cutter.location.y = 0.01
                    boolean_cut(outer, cutter)

                    # Red rolling door
                    infill = primary.get("infill", {})
                    door_hex = "#CC2020"  # fire engine red
                    if isinstance(infill, dict):
                        dc = str(infill.get("colour", "")).lower()
                        if "red" in dc:
                            door_hex = "#CC2020"

                    bpy.ops.mesh.primitive_cube_add(size=1)
                    door = bpy.context.active_object
                    door.name = f"engine_door_{bldg_id}"
                    door.scale = (pw * 0.95, 0.06, spring * 0.95)
                    bpy.ops.object.transform_apply(scale=True)
                    door.location = (vol_cx, 0.04, spring * 0.48)
                    door_mat = get_or_create_material("mat_fire_door", colour_hex=door_hex, roughness=0.4)
                    assign_material(door, door_mat)
                    all_objs.append(door)

                    # Fanlight glass above door
                    bpy.ops.mesh.primitive_circle_add(radius=pw / 2 * 0.9, vertices=16,
                                                       fill_type='NGON')
                    fan = bpy.context.active_object
                    fan.name = f"fanlight_{bldg_id}"
                    fan.rotation_euler.x = math.pi / 2
                    fan.location = (vol_cx, 0.04, spring)
                    # Clip bottom half by scaling
                    fan.scale.z = 0.5
                    assign_material(fan, create_glass_material())
                    all_objs.append(fan)

                    vous_start = len(all_objs)
                    vous = primary.get("voussoirs", {})
                    if isinstance(vous, dict) and vous:
                        stone_hex = get_stone_hex(vous.get("material", ""), vous.get("profile", ""), default="#C8C0B0")
                        all_objs.extend(_create_arch_voussoirs(
                            f"engine_voussoir_{bldg_id}",
                            vol_cx,
                            0.02,
                            0.0,
                            pw,
                            ph,
                            spring,
                            count=vous.get("count_approx", 15),
                            colour_hex=stone_hex,
                        ))
                    log_volume_feature("Engine-bay voussoirs", vous_start)

                # Personnel door
                sec = gf.get("secondary_opening", {})
                if isinstance(sec, dict) and sec:
                    sw = sec.get("width_m", 0.9)
                    sh = sec.get("height_m", 2.2)
                    cutter = create_rect_cutter(f"pers_door_cut_{bldg_id}", sw, sh, depth=0.8)
                    cutter.location.z = sh / 2
                    cutter.location.x = vol_cx + pw / 2 + 1.0
                    cutter.location.y = 0.01
                    boolean_cut(outer, cutter)

                    bpy.ops.mesh.primitive_cube_add(size=1)
                    pd = bpy.context.active_object
                    pd.name = f"pers_door_{bldg_id}"
                    pd.scale = (sw * 0.9, 0.06, sh * 0.95)
                    bpy.ops.object.transform_apply(scale=True)
                    pd.location = (vol_cx + pw / 2 + 1.0, 0.04, sh * 0.48)
                    assign_material(pd, door_mat)
                    all_objs.append(pd)
            log_volume_feature("Ground openings", ground_opening_start)

            # Second floor windows
            second_floor_start = len(all_objs)
            sf = vol.get("second_floor", {})
            if isinstance(sf, dict):
                sf_wins = sf.get("windows", [])
                for wi, ws in enumerate(sf_wins):
                    if not isinstance(ws, dict):
                        continue
                    wcount = ws.get("count", 2)
                    ww = ws.get("width_m", 0.9)
                    wh = ws.get("height_m", 1.6)
                    z2 = vol_floors[0] if vol_floors else 4.2
                    sill_z = z2 + (vol_floors[1] if len(vol_floors) > 1 else 3.5) * 0.2

                    spacing = vol_w / (wcount + 1)
                    for wci in range(wcount):
                        wx = vol_cx - vol_w / 2 + spacing * (wci + 1)
                        # Cut opening
                        cutter = create_arch_cutter(f"sf_win_cut_{wci}_{bldg_id}",
                                                     ww, wh, wh * 0.7,
                                                     arch_type="segmental", depth=0.8)
                        cutter.location.x = wx
                        cutter.location.z += sill_z
                        cutter.location.y = 0.01
                        boolean_cut(outer, cutter)

                        # Glass
                        bpy.ops.mesh.primitive_plane_add(size=1)
                        gl = bpy.context.active_object
                        gl.name = f"hall_glass_{wci}_{bldg_id}"
                        gl.scale = (ww * 0.85, 1, wh * 0.85)
                        bpy.ops.object.transform_apply(scale=True)
                        gl.rotation_euler.x = math.pi / 2
                        gl.location = (wx, 0.02, sill_z + wh / 2)
                        assign_material(gl, create_glass_material())
                        all_objs.append(gl)

                        # Frame
                        trim_hex = get_trim_hex(params)
                        fr_mat = get_or_create_material(f"mat_hallframe_{trim_hex.lstrip('#')}",
                                                         colour_hex=trim_hex, roughness=0.5)
                        ft = 0.04
                        for fn, fs, fl in [
                            ("t", (ww + ft, 0.05, ft), (wx, 0.03, sill_z + wh)),
                            ("b", (ww + ft * 2, 0.07, ft), (wx, 0.04, sill_z)),
                            ("l", (ft, 0.05, wh), (wx - ww / 2, 0.03, sill_z + wh / 2)),
                            ("r", (ft, 0.05, wh), (wx + ww / 2, 0.03, sill_z + wh / 2)),
                        ]:
                            bpy.ops.mesh.primitive_cube_add(size=1)
                            f_obj = bpy.context.active_object
                            f_obj.name = f"hall_frame_{fn}_{wci}_{bldg_id}"
                            f_obj.scale = fs
                            bpy.ops.object.transform_apply(scale=True)
                            f_obj.location = fl
                            assign_material(f_obj, fr_mat)
                            all_objs.append(f_obj)
            log_volume_feature("Upper windows", second_floor_start)

            # Gable roof for heritage hall
            roof_type = str(vol.get("roof_type", "gable")).lower()
            if "gable" in roof_type:
                roof_start = len(all_objs)
                pitch = vol.get("roof_pitch_deg", 35)
                ridge_h = (vol_w / 2) * math.tan(math.radians(pitch))

                bm = bmesh.new()
                hw = vol_w / 2 + 0.15
                ov = 0.3
                y_f = ov
                y_b = -vol_d - ov

                v0 = bm.verts.new((vol_cx - hw, y_b, vol_h))
                v1 = bm.verts.new((vol_cx + hw, y_b, vol_h))
                v2 = bm.verts.new((vol_cx + hw, y_f, vol_h))
                v3 = bm.verts.new((vol_cx - hw, y_f, vol_h))
                v4 = bm.verts.new((vol_cx, y_b, vol_h + ridge_h))
                v5 = bm.verts.new((vol_cx, y_f, vol_h + ridge_h))

                bm.faces.new([v0, v3, v5, v4])
                bm.faces.new([v1, v4, v5, v2])
                bm.faces.new([v2, v5, v3])
                bm.faces.new([v0, v4, v1])

                rmesh = bpy.data.meshes.new(f"hall_roof_{bldg_id}")
                bm.to_mesh(rmesh)
                bm.free()

                robj = bpy.data.objects.new(f"hall_roof_{bldg_id}", rmesh)
                bpy.context.collection.objects.link(robj)
                mod = robj.modifiers.new("Solidify", 'SOLIDIFY')
                mod.thickness = 0.08
                mod.offset = -1
                bpy.context.view_layer.objects.active = robj
                bpy.ops.object.modifier_apply(modifier=mod.name)

                roof_hex = get_roof_hex(params)
                r_mat = create_roof_material(f"mat_hallroof_{roof_hex.lstrip('#')}", roof_hex)
                assign_material(robj, r_mat)
                all_objs.append(robj)
                log_volume_feature("Gable roof", roof_start)

                # Gable walls
                gable_start = len(all_objs)
                for y_pos in [0, -vol_d]:
                    gbm = bmesh.new()
                    gv0 = gbm.verts.new((vol_cx - vol_w / 2, 0, vol_h))
                    gv1 = gbm.verts.new((vol_cx + vol_w / 2, 0, vol_h))
                    gv2 = gbm.verts.new((vol_cx, 0, vol_h + ridge_h))
                    gbm.faces.new([gv0, gv1, gv2])

                    gm = bpy.data.meshes.new(f"hall_gable_{bldg_id}")
                    gbm.to_mesh(gm)
                    gbm.free()

                    gobj = bpy.data.objects.new(f"hall_gable_{bldg_id}", gm)
                    bpy.context.collection.objects.link(gobj)
                    gobj.location.y = y_pos
                    mod = gobj.modifiers.new("Solidify", 'SOLIDIFY')
                    mod.thickness = 0.3
                    mod.offset = 0
                    bpy.context.view_layer.objects.active = gobj
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                    assign_material(gobj, hall_mat)
                    all_objs.append(gobj)
                log_volume_feature("Gable walls", gable_start)

                # Heritage-hall corbel table at eave line if described in volume details
                hall_corbel_start = len(all_objs)
                vol_dec = vol.get("second_floor", {}).get("decorative_elements", {})
                if isinstance(vol_dec, dict):
                    corbel_data = vol_dec.get("corbelling", {})
                    if corbel_data:
                        hall_course_count = 4 if "4" in json.dumps(corbel_data).lower() else 3
                        all_objs.extend(_create_corbel_band(
                            f"hall_corbel_{bldg_id}",
                            vol_cx,
                            0.02,
                            vol_h - 0.30,
                            vol_w,
                            course_count=hall_course_count,
                            colour_hex=vol_hex,
                        ))
                log_volume_feature("Hall corbelling", hall_corbel_start)

                # Oculus window in front gable
                oculus_start = len(all_objs)
                rf = vol.get("roof_features", [])
                for feat in rf:
                    if isinstance(feat, dict) and "oculus" in str(feat.get("type", "")).lower():
                        oc_diam = feat.get("diameter_m", 0.6)
                        oc_z = vol_h + ridge_h * 0.55
                        bpy.ops.mesh.primitive_circle_add(
                            radius=oc_diam / 2, vertices=24, fill_type='NGON')
                        oc = bpy.context.active_object
                        oc.name = f"oculus_{bldg_id}"
                        oc.rotation_euler.x = math.pi / 2
                        oc.location = (vol_cx, 0.16, oc_z)
                        assign_material(oc, create_glass_material())
                        all_objs.append(oc)

                        # Stone surround
                        bpy.ops.mesh.primitive_torus_add(
                            major_radius=oc_diam / 2 + 0.05,
                            minor_radius=0.05, major_segments=24, minor_segments=8)
                        ring = bpy.context.active_object
                        ring.name = f"oculus_surround_{bldg_id}"
                        ring.rotation_euler.x = math.pi / 2
                        ring.location = (vol_cx, 0.16, oc_z)
                        stone_mat = create_stone_material("mat_stone_oculus", "#C8C0B0")
                        assign_material(ring, stone_mat)
                        all_objs.append(ring)
                log_volume_feature("Oculus", oculus_start)

        x_cursor += vol_w

    all_objs = [o for o in all_objs if _obj_valid(o)]
    pre_join_count = len(all_objs)

    all_objs = join_by_prefix("hall_frame_", all_objs)
    all_objs = join_by_prefix("hall_glass_", all_objs)
    all_objs = join_by_prefix("curtain_glass_", all_objs)
    all_objs = join_by_prefix("mullion_", all_objs)
    all_objs = join_by_prefix("tower_glass_", all_objs)
    all_objs = join_by_prefix("tower_corner_", all_objs)
    all_objs = join_by_prefix("tower_veg_", all_objs)
    all_objs = join_by_prefix("tower_corbel_", all_objs)
    all_objs = join_by_prefix("tower_sc_", all_objs)
    all_objs = join_by_prefix("engine_voussoir_", all_objs)
    all_objs = join_by_prefix("clock_", all_objs)
    all_objs = join_by_prefix("clock_surround_", all_objs)

    post_join_count = len(all_objs)
    if post_join_count < pre_join_count:
        print(f"  Joined objects: {pre_join_count} -> {post_join_count}")

    # Move all to collection with offset
    col = bpy.data.collections.new(f"building_{bldg_id}")
    bpy.context.scene.collection.children.link(col)

    ox, oy, oz = offset
    for obj in all_objs:
        if obj:
            obj.location.x += ox
            obj.location.y += oy
            obj.location.z += oz
            for c in obj.users_collection:
                c.objects.unlink(obj)
            col.objects.link(obj)

    print(f"  [OK] Multi-volume total objects: {len([o for o in all_objs if o])}")
    return col


def generate_building(params, offset=(0, 0, 0), rotation=0.0):
    """Generate a complete 3D building from JSON parameters."""
    params = apply_hcd_guide_defaults(params)

    # Check for multi-volume buildings
    volumes = params.get("volumes", [])
    if len(volumes) >= 2:
        return generate_multi_volume(params, offset)

    address = "unknown"
    meta = params.get("_meta", {})
    if isinstance(meta, dict):
        address = meta.get("address", "unknown")

    bldg_id = address.replace(" ", "_").replace(",", "").replace(".", "")
    print(f"[GENERATE] {address}")

    # HCD-derived defaults (used as fallbacks when params don't specify)
    era_defaults = get_era_defaults(params)
    typology_hints = get_typology_hints(params)

    depth = params.get("facade_depth_m", DEFAULT_DEPTH)

    # 1. Create walls
    wall_obj, wall_h, width, depth = create_walls(params, depth)
    print(f"  Walls: {width:.1f}m x {depth:.1f}m x {wall_h:.1f}m")

    # 2. Cut window openings
    windows = cut_windows(wall_obj, params, wall_h, width, bldg_id)
    print(f"  Windows: {len(windows)} elements")

    # 3. Cut door openings
    doors = cut_doors(wall_obj, params, width)
    if doors:
        print(f"  Doors: {len(doors)} elements")

    # 4. Create roof
    roof_type = str(params.get("roof_type", "gable")).lower()
    ridge_height = 0
    gable_objs = []

    if "flat" in roof_type:
        roof_obj, parapet_h = create_flat_roof(params, wall_h, width, depth)
        print(f"  Roof: flat with {parapet_h:.1f}m parapet")
    elif "hip" in roof_type:
        roof_obj, ridge_height = create_hip_roof(params, wall_h, width, depth)
        print(f"  Roof: hip, peak +{ridge_height:.1f}m")
    elif "cross" in roof_type or "bay-and-gable" in roof_type or "bay_and_gable" in roof_type:
        roof_obj, ridge_height = create_cross_gable_roof(params, wall_h, width, depth)
        gable_objs = create_gable_walls(params, wall_h, width, depth, bldg_id)
        print(f"  Roof: cross-gable, ridge +{ridge_height:.1f}m, +{len(gable_objs)} gable walls")
    elif "gable" in roof_type:
        roof_obj, ridge_height = create_gable_roof(params, wall_h, width, depth)
        gable_objs = create_gable_walls(params, wall_h, width, depth, bldg_id)
        print(f"  Roof: gable, ridge +{ridge_height:.1f}m, +{len(gable_objs)} gable walls")
    else:
        roof_obj, ridge_height = create_gable_roof(params, wall_h, width, depth)
        gable_objs = create_gable_walls(params, wall_h, width, depth, bldg_id)

    # 5. Porch
    porch_objs = create_porch(params, width)
    if porch_objs:
        print(f"  Porch: {len(porch_objs)} elements")

    # 6. Bay windows
    bay_objs = create_bay_window(params, wall_h, width)
    if bay_objs:
        print(f"  Bay window: {len(bay_objs)} elements")

    # 7. Chimneys
    chimney_objs = create_chimney(params, wall_h, ridge_height, width)
    if chimney_objs:
        print(f"  Chimneys: {len(chimney_objs)}")

    # 8. Storefront
    sf_objs = create_storefront(params, wall_obj, width)
    if sf_objs:
        print(f"  Storefront: {len(sf_objs)} elements")

    # 9. String courses
    sc_objs = create_string_courses(params, wall_h, width, depth, bldg_id)
    if sc_objs:
        print(f"  String courses: {len(sc_objs)}")

    # 10. Quoins
    quoin_objs = create_quoins(params, wall_h, width, depth, bldg_id)
    if quoin_objs:
        print(f"  Quoins: {len(quoin_objs)}")

    # 11. Tower (for fire station etc)
    tower_objs = create_tower(params, bldg_id)
    if tower_objs:
        print(f"  Tower: {len(tower_objs)} elements")

    # 12. Bargeboard (decorative rake boards on gable)
    bb_objs = []
    if "gable" in roof_type:
        bb_objs = create_bargeboard(params, wall_h, width, depth, bldg_id)
        if bb_objs:
            print(f"  Bargeboard: {len(bb_objs)} elements")

    # 13. Cornice band
    cornice_objs = create_cornice_band(params, wall_h, width, depth, bldg_id)
    if cornice_objs:
        print(f"  Cornice: {len(cornice_objs)} elements")

    # 13b. Corbel table / stepped brickwork
    corbel_objs = create_corbelling(params, wall_h, width, depth, bldg_id)
    if corbel_objs:
        print(f"  Corbelling: {len(corbel_objs)} elements")

    # 14. Window lintels and sills
    lintel_objs = create_window_lintels(params, wall_h, width, bldg_id)
    if lintel_objs:
        print(f"  Lintels/sills: {len(lintel_objs)} elements")

    # 14b. Stained-glass transoms
    transom_objs = create_stained_glass_transoms(params, width, bldg_id)
    if transom_objs:
        print(f"  Transoms: {len(transom_objs)} elements")

    # 15. Brackets (gable and porch)
    bracket_objs = create_brackets(params, wall_h, width, depth, bldg_id)
    if bracket_objs:
        print(f"  Brackets: {len(bracket_objs)} elements")

    # 16. Ridge finial
    finial_objs = []
    if "gable" in roof_type:
        finial_objs = create_ridge_finial(params, wall_h, width, depth, bldg_id)
        if finial_objs:
            print(f"  Finial: {len(finial_objs)} elements")

    # 17. Voussoirs (arch stones)
    voussoir_objs = create_voussoirs(params, wall_h, width, bldg_id)
    if voussoir_objs:
        print(f"  Voussoirs: {len(voussoir_objs)} elements")

    # 18. Gable fish-scale shingles
    shingle_objs = []
    if "gable" in roof_type:
        shingle_objs = create_gable_shingles(params, wall_h, width, depth, bldg_id)
        if shingle_objs:
            print(f"  Gable shingles: {len(shingle_objs)} elements")

    # 19. Dormer
    dormer_objs = create_dormer(params, wall_h, width, depth, bldg_id)
    if dormer_objs:
        print(f"  Dormer: {len(dormer_objs)} elements")

    # 20. Fascia and soffit boards
    fascia_objs = create_fascia_boards(params, wall_h, width, depth, bldg_id)
    if fascia_objs:
        print(f"  Fascia/soffit: {len(fascia_objs)} elements")

    # 21. Parapet coping (flat roofs)
    parapet_objs = create_parapet_coping(params, wall_h, width, depth, bldg_id)
    if parapet_objs:
        print(f"  Parapet/coping: {len(parapet_objs)} elements")

    # 21a. Small rooftop hip element / penthouse cap
    hip_rooflet_objs = create_hip_rooflet(params, wall_h, width, depth, bldg_id)
    if hip_rooflet_objs:
        print(f"  Hip rooflet: {len(hip_rooflet_objs)} elements")

    # 21b. Gabled parapet
    gp_objs = create_gabled_parapet(params, wall_h, width, depth, bldg_id)
    if gp_objs:
        print(f"  Gabled parapet: {len(gp_objs)} elements")

    # 22. Turned porch posts (replace cylinders with Victorian turned posts)
    porch_objs = create_turned_posts(porch_objs, params, width)

    # 23. Storefront awning and signage
    awning_objs = create_storefront_awning(params, width, bldg_id)
    if awning_objs:
        print(f"  Awning/sign: {len(awning_objs)} elements")

    # 24. Foundation/water table
    found_objs = create_foundation(params, width, depth, bldg_id)
    if found_objs:
        print(f"  Foundation: {len(found_objs)} elements")

    # 25. Gutters and downspouts
    gutter_objs = create_gutters(params, wall_h, width, depth, bldg_id)
    if gutter_objs:
        print(f"  Gutters: {len(gutter_objs)} elements")

    # 26. Chimney caps
    chimney_cap_objs = create_chimney_caps(params, wall_h, ridge_height, width, bldg_id)
    if chimney_cap_objs:
        print(f"  Chimney caps: {len(chimney_cap_objs)} elements")

    # 27. Porch lattice skirt
    lattice_objs = create_porch_lattice(params, width, bldg_id)
    if lattice_objs:
        print(f"  Lattice skirt: {len(lattice_objs)} elements")

    # 28. Step handrails
    handrail_objs = create_step_handrails(params, width, bldg_id)
    if handrail_objs:
        print(f"  Handrails: {len(handrail_objs)} elements")

    # Collect all objects
    all_objs = [wall_obj, roof_obj] + gable_objs + windows + doors + porch_objs + bay_objs + \
               chimney_objs + sf_objs + sc_objs + quoin_objs + tower_objs + corbel_objs + \
               bb_objs + cornice_objs + lintel_objs + transom_objs + bracket_objs + finial_objs + \
               voussoir_objs + shingle_objs + dormer_objs + fascia_objs + parapet_objs + \
               hip_rooflet_objs + awning_objs + found_objs + gutter_objs + chimney_cap_objs + \
               lattice_objs + handrail_objs + gp_objs

    # Join small objects by type to reduce clutter
    def _obj_valid(o):
        try:
            return o is not None and o.name is not None
        except ReferenceError:
            return False

    def join_by_prefix(prefix, objs_list):
        """Join all objects whose name starts with prefix into a single mesh."""
        targets = []
        for o in objs_list:
            try:
                if o and o.name.startswith(prefix):
                    targets.append(o)
            except ReferenceError:
                continue
        if len(targets) < 2:
            return objs_list
        bpy.ops.object.select_all(action='DESELECT')
        for o in targets:
            o.select_set(True)
        bpy.context.view_layer.objects.active = targets[0]
        bpy.ops.object.join()
        joined = bpy.context.active_object
        joined.name = f"{prefix}{bldg_id}"
        # Replace in list: keep joined, remove others
        new_list = [o for o in objs_list if _obj_valid(o) and o not in targets]
        new_list.append(joined)
        return new_list

    all_objs = [o for o in all_objs if _obj_valid(o)]
    pre_join_count = len(all_objs)

    all_objs = join_by_prefix("frame_", all_objs)
    all_objs = join_by_prefix("muntin_", all_objs)
    all_objs = join_by_prefix("glass_", all_objs)
    all_objs = join_by_prefix("baluster_", all_objs)
    all_objs = join_by_prefix("bay_glass_", all_objs)
    all_objs = join_by_prefix("step_", all_objs)
    all_objs = join_by_prefix("lintel_", all_objs)
    all_objs = join_by_prefix("sill_", all_objs)
    all_objs = join_by_prefix("bracket_", all_objs)
    all_objs = join_by_prefix("porch_bracket_", all_objs)
    all_objs = join_by_prefix("bargeboard_", all_objs)
    all_objs = join_by_prefix("voussoir_", all_objs)
    all_objs = join_by_prefix("shingle_", all_objs)
    all_objs = join_by_prefix("dormer_frame_", all_objs)
    all_objs = join_by_prefix("dormer_cheek_", all_objs)
    all_objs = join_by_prefix("fascia_", all_objs)
    all_objs = join_by_prefix("soffit_", all_objs)
    all_objs = join_by_prefix("parapet_", all_objs)
    all_objs = join_by_prefix("coping_", all_objs)
    all_objs = join_by_prefix("turned_seg_", all_objs)
    all_objs = join_by_prefix("lattice_", all_objs)
    all_objs = join_by_prefix("foundation_", all_objs)
    all_objs = join_by_prefix("gutter_", all_objs)
    all_objs = join_by_prefix("downspout_", all_objs)
    all_objs = join_by_prefix("chimcap_", all_objs)
    all_objs = join_by_prefix("handrail_", all_objs)
    all_objs = join_by_prefix("rail_post_", all_objs)
    all_objs = join_by_prefix("hall_frame_", all_objs)
    all_objs = join_by_prefix("hall_glass_", all_objs)
    all_objs = join_by_prefix("curtain_glass_", all_objs)
    all_objs = join_by_prefix("mullion_", all_objs)
    all_objs = join_by_prefix("tower_glass_", all_objs)
    all_objs = join_by_prefix("tower_corner_", all_objs)
    all_objs = join_by_prefix("tower_veg_", all_objs)
    all_objs = join_by_prefix("tower_corbel_", all_objs)
    all_objs = join_by_prefix("engine_voussoir_", all_objs)
    all_objs = join_by_prefix("transom_", all_objs)
    all_objs = join_by_prefix("quoin_", all_objs)
    all_objs = join_by_prefix("string_course_", all_objs)
    all_objs = join_by_prefix("cornice_", all_objs)

    post_join_count = len(all_objs)
    if post_join_count < pre_join_count:
        print(f"  Joined objects: {pre_join_count} -> {post_join_count}")

    # Move to building collection and apply offset directly (no parent empty = no clutter)
    col = bpy.data.collections.new(f"building_{bldg_id}")
    bpy.context.scene.collection.children.link(col)

    ox, oy, oz = offset
    for obj in all_objs:
        if _obj_valid(obj):
            # Apply rotation around origin (Z-axis) before offset
            if rotation != 0.0:
                cos_r = math.cos(rotation)
                sin_r = math.sin(rotation)
                x, y = obj.location.x, obj.location.y
                obj.location.x = x * cos_r - y * sin_r
                obj.location.y = x * sin_r + y * cos_r
                obj.rotation_euler.z += rotation
            obj.location.x += ox
            obj.location.y += oy
            obj.location.z += oz
            # Move to building collection
            for c in obj.users_collection:
                c.objects.unlink(obj)
            col.objects.link(obj)

    # Store HCD metadata as custom properties on the collection
    if 'hcd_data' in params:
        hcd = params['hcd_data']
        col['hcd_reference'] = hcd.get('hcd_reference_number', 0)
        col['hcd_typology'] = hcd.get('typology', '')
        col['hcd_construction_date'] = hcd.get('construction_date', '')
        col['hcd_character_sub_area'] = hcd.get('character_sub_area', '')
        col['hcd_statement'] = hcd.get('statement_of_contribution', '')

    print(f"  [OK] Total objects: {len([o for o in all_objs if o])}")
    return col


# ---------------------------------------------------------------------------
# Multi-building loader
# ---------------------------------------------------------------------------

def load_and_generate(params_path, spacing=15.0):
    """Load one or more JSON param files and generate buildings."""
    clear_scene()

    path = Path(params_path)

    # Load site coordinates from GIS export (SRID 2952, local metres)
    site_coords_path = Path(__file__).parent / "params" / "_site_coordinates.json"
    site_coords = None
    if site_coords_path.exists():
        with open(site_coords_path, encoding="utf-8") as gf:
            site_coords = json.load(gf)
        print(f"Loaded site coordinates: {len(site_coords)} buildings (from PostGIS)")

    # Legacy geocode fallback
    geocode_path = Path(__file__).parent / "archive" / "geocode.json"
    geocode = None
    if geocode_path.exists():
        with open(geocode_path) as gf:
            geocode = json.load(gf)
        print(f"Loaded geocode.json: {len(geocode)} entries (legacy fallback)")

    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = sorted(path.glob("*.json"))
        files = [f for f in files if not f.name.startswith("_")]
    else:
        print(f"[ERROR] Path not found: {params_path}")
        return

    print(f"=== Parametric Building Generator ===")
    print(f"Files: {len(files)}")

    buildings = []
    manifest_buildings = []
    for i, f in enumerate(files):
        print(f"\n--- [{i+1}/{len(files)}] {f.name} ---")
        with open(f) as fp:
            params = json.load(fp)

        if 'hcd_data' in params:
            hcd = params['hcd_data']
            print(f"  HCD #{hcd.get('hcd_reference_number', '?')}: {hcd.get('typology', 'Unknown')}, {hcd.get('construction_date', 'Unknown')}")
            if hcd.get('discrepancies'):
                print(f"  Discrepancies: {'; '.join(hcd['discrepancies'])}")

        # Determine building position:
        # 1. Site coordinates from PostGIS GIS export (preferred)
        # 2. Legacy geocode.json fallback
        # 3. Linear spacing as last resort
        address = params.get("building_name") or params.get("_meta", {}).get("address", "")
        geo_key = f.stem

        if site_coords and address and address in site_coords:
            sc = site_coords[address]
            offset = (sc["x"], sc["y"], 0)
            rotation = math.radians(sc.get("rotation_deg", 0))
        elif site_coords:
            # Try matching by filename stem (address with underscores)
            stem_addr = geo_key.replace("_", " ")
            if stem_addr in site_coords:
                sc = site_coords[stem_addr]
                offset = (sc["x"], sc["y"], 0)
                rotation = math.radians(sc.get("rotation_deg", 0))
            elif geocode and geo_key in geocode:
                gc = geocode[geo_key]
                offset = (gc["blender_x"], gc["blender_y"], 0)
                rotation = math.radians(gc.get("rotation_deg", 0))
            else:
                offset = (i * spacing, 0, 0)
                rotation = 0.0
        elif geocode and geo_key in geocode:
            gc = geocode[geo_key]
            offset = (gc["blender_x"], gc["blender_y"], 0)
            rotation = math.radians(gc.get("rotation_deg", 0))
        else:
            offset = (i * spacing, 0, 0)
            rotation = 0.0
        bldg = generate_building(params, offset=offset, rotation=rotation)
        buildings.append(bldg)
        hcd = params.get("hcd_data", {}) if isinstance(params.get("hcd_data"), dict) else {}
        manifest_buildings.append({
            "param_file": str(f.resolve()),
            "building_name": params.get("building_name") or params.get("_meta", {}).get("address", f.stem),
            "collection_name": bldg.name if bldg else None,
            "hcd_reference_number": hcd.get("hcd_reference_number"),
            "typology": hcd.get("typology"),
            "construction_date": hcd.get("construction_date"),
        })

    # Setup camera and lighting
    setup_scene(buildings, spacing)

    print(f"\n=== Done: {len(buildings)} buildings generated ===")
    return {
        "collections": buildings,
        "files": files,
        "buildings": manifest_buildings,
    }


def setup_scene(buildings, spacing):
    """Set up camera, sun, and render settings."""
    # Compute scene bounds from all building collections
    all_xs, all_ys = [], []
    for col in buildings:
        if col:
            for obj in col.objects:
                if obj.type == 'MESH':
                    all_xs.append(obj.location.x)
                    all_ys.append(obj.location.y)

    if all_xs:
        center_x = (min(all_xs) + max(all_xs)) / 2
        center_y = (min(all_ys) + max(all_ys)) / 2
        spread = max(max(all_xs) - min(all_xs), max(all_ys) - min(all_ys))
        # For neighbourhood-scale (many buildings), keep a wide view
        # For single/few buildings, frame tightly around the building(s)
        if spread > 50:
            extent = spread
        else:
            extent = max(spread, 30)
    else:
        n = len(buildings)
        center_x = (n - 1) * spacing / 2
        center_y = 0
        extent = n * spacing

    # Sun light
    bpy.ops.object.light_add(type='SUN', location=(center_x, center_y + 50, 50))
    sun = bpy.context.active_object
    sun.name = "Sun"
    sun.data.energy = 4.0
    sun.rotation_euler = (math.radians(55), math.radians(10), math.radians(200))

    # Camera — angled perspective view
    n_buildings = len([c for c in buildings if c])
    if n_buildings <= 3:
        # Close-up: eye-level 3/4 view for single/few buildings
        cam_dist = max(extent * 0.6, 20)
        cam_height = cam_dist * 0.5
        cam_x = center_x + cam_dist * 0.4
        cam_y = center_y - cam_dist * 0.5
        cam_pitch = math.degrees(math.atan2(cam_height, cam_dist * 0.5))
        bpy.ops.object.camera_add(location=(cam_x, cam_y, cam_height))
        cam = bpy.context.active_object
        cam.name = "Camera"
        cam.rotation_euler = (math.radians(cam_pitch), 0, math.radians(155))
    else:
        # Wide neighbourhood view
        cam_height = extent * 0.8
        bpy.ops.object.camera_add(location=(center_x, center_y - extent * 0.4, cam_height))
        cam = bpy.context.active_object
        cam.name = "Camera"
        cam.rotation_euler = (math.radians(60), 0, math.radians(180))
    bpy.context.scene.camera = cam

    # Render settings
    scene = bpy.context.scene
    try:
        scene.render.engine = 'BLENDER_EEVEE'
    except:
        try:
            scene.render.engine = 'BLENDER_EEVEE_NEXT'
        except:
            pass

    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080

    # Ground plane
    ground_size = max(extent * 2, 200)
    bpy.ops.mesh.primitive_plane_add(size=ground_size, location=(center_x, center_y, 0))
    ground = bpy.context.active_object
    ground.name = "ground"
    ground_mat = get_or_create_material("mat_ground", colour_hex="#505050", roughness=0.95)
    assign_material(ground, ground_mat)


def default_output_paths(params_path, output_blend=None, output_dir=None, render_path=None):
    """Compute default .blend and optional render output paths."""
    path = Path(params_path)
    if output_dir:
        out_dir = Path(output_dir)
    elif path.is_file():
        out_dir = path.parent.parent / "outputs"
    else:
        out_dir = path.parent / "outputs"

    if path.is_file():
        stem = path.stem
        blend_default = out_dir / f"{stem}.blend"
        render_default = out_dir / f"{stem}.png"
    else:
        blend_default = out_dir / "kensington_pilot.blend"
        render_default = out_dir / "kensington_pilot.png"

    blend_path = Path(output_blend) if output_blend else blend_default
    render_out = Path(render_path) if render_path else None
    return blend_path.resolve(), (render_out.resolve() if render_out else render_default.resolve())


def default_manifest_path(blend_path):
    """Place the run manifest next to the output .blend file."""
    return blend_path.with_suffix(".manifest.json")


def write_manifest(manifest_path, params_path, blend_path, render_path, do_render, run_data):
    """Write a machine-readable summary of the generation run."""
    run_data = run_data or {}
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "params_path": str(Path(params_path).resolve()),
        "blend_path": str(blend_path),
        "render_path": str(render_path) if do_render else None,
        "building_count": len(run_data.get("buildings", [])),
        "buildings": run_data.get("buildings", []),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print(f"Manifest: {manifest_path}")


def purge_orphans_safe():
    """Purge Blender orphan data with operator fallback for headless/context issues."""
    try:
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    except Exception:
        # Fallback: manually purge orphan meshes and materials
        for block in list(bpy.data.meshes):
            if block.users == 0:
                bpy.data.meshes.remove(block)
        for block in list(bpy.data.materials):
            if block.users == 0:
                bpy.data.materials.remove(block)


def resolve_batch_files(params_dir, output_dir=None, do_render=False,
                        skip_existing=False, match=None, limit=None):
    """Resolve which batch files would be processed and where outputs would go."""
    params_dir = Path(params_dir)
    files = sorted(f for f in params_dir.glob("*.json") if not f.name.startswith("_"))
    if match:
        needle = match.lower()
        files = [f for f in files if needle in f.stem.lower()]
    if isinstance(limit, int) and limit > 0:
        files = files[:limit]

    out_dir = Path(output_dir) if output_dir else params_dir.parent / "outputs"
    plans = []
    for f in files:
        # Skip param files marked as skipped (non-buildings, duplicates)
        try:
            with open(f, encoding="utf-8") as fh:
                pdata = json.load(fh)
            if pdata.get("skipped"):
                continue
        except Exception:
            pass
        blend_path, render_path = default_output_paths(str(f), output_dir=str(out_dir))
        manifest_path = default_manifest_path(blend_path)
        skipped = bool(skip_existing and blend_path.exists())
        plans.append({
            "param_file": str(f.resolve()),
            "blend_path": str(blend_path),
            "render_path": str(render_path) if do_render else None,
            "manifest_path": str(manifest_path),
            "skipped": skipped,
        })
    return plans


def generate_batch_individual(params_dir, output_dir=None, do_render=False,
                              skip_existing=False, match=None, limit=None):
    """Generate one .blend per param file plus a batch manifest."""
    params_dir = Path(params_dir)
    plans = resolve_batch_files(
        params_dir,
        output_dir=output_dir,
        do_render=do_render,
        skip_existing=skip_existing,
        match=match,
        limit=limit,
    )
    if not plans:
        print(f"[ERROR] No param files found in: {params_dir}")
        return None

    out_dir = Path(output_dir) if output_dir else params_dir.parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    batch_manifest = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "params_path": str(params_dir.resolve()),
        "mode": "batch_individual",
        "building_count": len(plans),
        "filters": {
            "match": match,
            "limit": limit,
            "skip_existing": skip_existing,
        },
        "counts": {
            "completed": 0,
            "skipped": 0,
            "failed": 0,
        },
        "buildings": [],
    }

    print(f"=== Parametric Building Generator ===")
    print(f"Files: {len(plans)}")
    print("Mode: batch individual")

    for i, plan in enumerate(plans, start=1):
        f = Path(plan["param_file"])
        blend_path = Path(plan["blend_path"])
        render_path = Path(plan["render_path"]) if plan["render_path"] else None
        manifest_path = Path(plan["manifest_path"])
        print(f"\n--- [{i}/{len(plans)}] {f.name} ---")

        if plan["skipped"]:
            print(f"  [SKIP] Existing output: {blend_path.name}")
            batch_manifest["counts"]["skipped"] += 1
            batch_manifest["buildings"].append({
                "param_file": str(f.resolve()),
                "blend_path": str(blend_path),
                "render_path": str(render_path) if do_render and render_path and render_path.exists() else None,
                "manifest_path": str(manifest_path) if manifest_path.exists() else None,
                "skipped": True,
                "status": "skipped",
            })
            continue

        try:
            run_data = load_and_generate(str(f), spacing=15.0)

            purge_orphans_safe()
            bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
            print(f"Saved: {blend_path}")

            rendered = None
            if do_render:
                bpy.context.scene.render.filepath = str(render_path)
                bpy.ops.render.render(write_still=True)
                rendered = str(render_path)
                print(f"Rendered: {render_path}")

            write_manifest(manifest_path, str(f), blend_path, render_path, do_render, run_data)
            batch_manifest["counts"]["completed"] += 1
            batch_manifest["buildings"].append({
                "param_file": str(f.resolve()),
                "blend_path": str(blend_path),
                "render_path": rendered,
                "manifest_path": str(manifest_path),
                "summary": run_data.get("buildings", [{}])[0] if run_data else {},
                "skipped": False,
                "status": "completed",
            })
        except Exception as e:
            print(f"  [FAIL] {f.name}: {e}")
            batch_manifest["counts"]["failed"] += 1
            batch_manifest["buildings"].append({
                "param_file": str(f.resolve()),
                "blend_path": str(blend_path),
                "render_path": None,
                "manifest_path": None,
                "skipped": False,
                "status": "failed",
                "error": str(e),
            })

    batch_manifest_path = out_dir / "batch.manifest.json"
    with open(batch_manifest_path, "w") as f:
        json.dump(batch_manifest, f, indent=2)
        f.write("\n")
    print(f"\nBatch manifest: {batch_manifest_path}")
    return batch_manifest


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Parse args after "--"
    argv = sys.argv
    params_path = str(PARAMS_DIR)
    output_blend = None
    output_dir = None
    render_output = None
    manifest_output = None
    do_render = False
    batch_individual = False
    skip_existing = False
    match_filter = None
    limit = None
    dry_run = False

    if "--" in argv:
        args = argv[argv.index("--") + 1:]

        def _get_value(idx):
            nxt = idx + 1
            if nxt >= len(args):
                return None
            value = args[nxt]
            if isinstance(value, str) and value.startswith("--"):
                return None
            return value

        i = 0
        while i < len(args):
            arg = args[i]
            if arg in ("--params", "--single"):
                value = _get_value(i)
                if value is None:
                    print(f"[WARN] Missing value for {arg}; keeping default params path")
                else:
                    params_path = value
                    i += 1
            elif arg == "--output-blend":
                value = _get_value(i)
                if value is None:
                    print("[WARN] Missing value for --output-blend; ignoring")
                else:
                    output_blend = value
                    i += 1
            elif arg == "--output-dir":
                value = _get_value(i)
                if value is None:
                    print("[WARN] Missing value for --output-dir; ignoring")
                else:
                    output_dir = value
                    i += 1
            elif arg == "--render":
                do_render = True
            elif arg == "--batch-individual":
                batch_individual = True
            elif arg == "--skip-existing":
                skip_existing = True
            elif arg == "--dry-run":
                dry_run = True
            elif arg == "--match":
                value = _get_value(i)
                if value is None:
                    print("[WARN] Missing value for --match; ignoring")
                else:
                    match_filter = value
                    i += 1
            elif arg == "--limit":
                value = _get_value(i)
                if value is None:
                    print("[WARN] Missing value for --limit; ignoring")
                else:
                    try:
                        limit = int(value)
                    except ValueError:
                        print(f"[WARN] Invalid --limit '{value}'; ignoring")
                        limit = None
                    i += 1
            elif arg == "--render-output":
                value = _get_value(i)
                if value is None:
                    print("[WARN] Missing value for --render-output; ignoring")
                else:
                    render_output = value
                    i += 1
            elif arg == "--manifest-output":
                value = _get_value(i)
                if value is None:
                    print("[WARN] Missing value for --manifest-output; ignoring")
                else:
                    manifest_output = value
                    i += 1
            elif isinstance(arg, str) and arg.startswith("--"):
                print(f"[WARN] Unknown option: {arg}")
            i += 1

    if dry_run:
        path = Path(params_path)
        if path.is_dir() and batch_individual:
            plans = resolve_batch_files(
                path,
                output_dir=output_dir,
                do_render=do_render,
                skip_existing=skip_existing,
                match=match_filter,
                limit=limit,
            )
            print("=== Dry Run ===")
            print(f"Mode: batch individual")
            print(f"Files: {len(plans)}")
            for plan in plans:
                status = "SKIP" if plan["skipped"] else "RUN"
                print(f"[{status}] {Path(plan['param_file']).name} -> {Path(plan['blend_path']).name}")
                if plan["render_path"]:
                    print(f"       render: {Path(plan['render_path']).name}")
                print(f"       manifest: {Path(plan['manifest_path']).name}")
        else:
            blend_path, render_path = default_output_paths(
                params_path,
                output_blend=output_blend,
                output_dir=output_dir,
                render_path=render_output,
            )
            manifest_path = Path(manifest_output).resolve() if manifest_output else default_manifest_path(blend_path)
            print("=== Dry Run ===")
            print(f"Params: {Path(params_path).resolve()}")
            print(f"Blend: {blend_path}")
            if do_render:
                print(f"Render: {render_path}")
            print(f"Manifest: {manifest_path}")
        sys.exit(0)

    if Path(params_path).is_dir() and batch_individual:
        try:
            generate_batch_individual(
                params_path,
                output_dir=output_dir,
                do_render=do_render,
                skip_existing=skip_existing,
                match=match_filter,
                limit=limit,
            )
        except Exception as e:
            print(f"Batch generation failed: {e}")
        sys.exit(0)

    # Generate buildings
    run_data = load_and_generate(params_path)
    if run_data is None:
        print("[ERROR] Generation aborted due to invalid input path.")
        sys.exit(1)

    blend_path, render_path = default_output_paths(
        params_path,
        output_blend=output_blend,
        output_dir=output_dir,
        render_path=render_output,
    )
    manifest_path = Path(manifest_output).resolve() if manifest_output else default_manifest_path(blend_path)
    blend_path.parent.mkdir(parents=True, exist_ok=True)

    # Purge orphan data to reduce file size
    purge_orphans_safe()
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        print(f"Saved: {blend_path}")
    except Exception as e:
        print(f"Could not save .blend file: {e}")

    if do_render:
        render_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.context.scene.render.filepath = str(render_path)
        try:
            bpy.ops.render.render(write_still=True)
            print(f"Rendered: {render_path}")
        except Exception as e:
            print(f"Could not render snapshot: {e}")

    try:
        write_manifest(manifest_path, params_path, blend_path, render_path, do_render, run_data)
    except Exception as e:
        print(f"Could not write manifest: {e}")
