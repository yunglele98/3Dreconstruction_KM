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
import addon_utils
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


def _safe_tan(degrees, lo=5.0, hi=85.0):
    """Return tan(degrees) with the angle clamped to [lo, hi] to avoid infinity.

    Roof pitches of 0° produce zero ridge height (harmless but wrong) and 90°
    makes tan() explode.  Clamping to 5-85° keeps geometry sane for the full
    param dataset.
    """
    clamped = max(lo, min(hi, float(degrees)))
    return math.tan(math.radians(clamped))


def _clamp_positive(value, default, minimum=0.5):
    """Return *value* if it is a positive number >= *minimum*, else *default*.

    Prevents zero-width / zero-depth / zero-height geometry that would crash
    bmesh boolean or produce degenerate cubes.
    """
    try:
        v = float(value)
        return v if v >= minimum else default
    except (TypeError, ValueError):
        return default


def _get_bsdf(mat):
    """Safely retrieve the Principled BSDF node from a material.

    Returns the node, or None if the material has no node tree or no
    Principled BSDF.  All procedural material functions should use this
    instead of raw ``nodes.get("Principled BSDF")`` to avoid
    AttributeError on shader-less materials.
    """
    if not mat or not mat.node_tree:
        return None
    return mat.node_tree.nodes.get("Principled BSDF")


def get_or_create_material(name, colour_hex=None, colour_rgb=None, roughness=0.8,
                           metallic=0.0):
    """Get existing material or create a new Principled BSDF material.

    Args:
        metallic: Metallic value (0.0 = dielectric, 1.0 = full metal).
            Used for storefront mullions, railings, and other metal trim.
    """
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
        if metallic > 0.0 and "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = metallic
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


def create_brick_material(name, brick_hex, mortar_hex="#B0A898", scale=8.0,
                          bond_pattern="running", polychrome_hex=None):
    """Create a procedural brick material with mortar lines, colour variation, and bump.

    Args:
        name: Blender material name.
        brick_hex: Primary brick colour hex.
        mortar_hex: Mortar colour hex.
        scale: UV tiling scale.
        bond_pattern: "running" (default stretcher bond), "flemish" (alternating
                      header/stretcher widths), or "stack" (no offset).
        polychrome_hex: Optional secondary brick colour hex for polychromatic
                        brickwork. When set, replaces the darkened Color2 with
                        the accent colour, creating visible decorative bands
                        (common in Victorian-era Kensington Market buildings).
    """
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    bsdf = _get_bsdf(mat)
    output = nodes.get("Material Output")
    if not bsdf:
        return mat
    bsdf.inputs["Roughness"].default_value = 0.85

    # Bond pattern presets — controls brick node offset and dimensions
    bond = (bond_pattern or "running").lower().strip()
    if "flemish" in bond:
        # Flemish: alternating header/stretcher per row, narrower bricks,
        # offset every other row by a different amount
        brick_width = 0.35
        row_height = 0.25
        offset_val = 0.5
        offset_freq = 1  # alternates every row
    elif "stack" in bond:
        # Stack bond: bricks aligned vertically, no offset
        brick_width = 0.5
        row_height = 0.25
        offset_val = 0.0
        offset_freq = 1
    else:
        # Running bond (default stretcher): half-brick offset every row
        brick_width = 0.5
        row_height = 0.25
        offset_val = 0.5
        offset_freq = 2

    # Brick texture
    brick = nodes.new('ShaderNodeTexBrick')
    brick.location = (0, 0)
    r, g, b = hex_to_rgb(brick_hex)
    brick.inputs["Color1"].default_value = (r, g, b, 1.0)
    if polychrome_hex and polychrome_hex.startswith("#"):
        # Polychromatic brickwork: accent colour for alternating brick courses
        pr, pg, pb = hex_to_rgb(polychrome_hex)
        brick.inputs["Color2"].default_value = (pr, pg, pb, 1.0)
    else:
        # Colour variation: Color2 is slightly darker + warmer for natural brick look
        brick.inputs["Color2"].default_value = (
            min(1.0, r * 0.82 + 0.02),
            g * 0.80,
            b * 0.78,
            1.0
        )
    mr, mg, mb = hex_to_rgb(mortar_hex)
    brick.inputs["Mortar"].default_value = (mr, mg, mb, 1.0)
    brick.inputs["Scale"].default_value = 1.0
    brick.inputs["Mortar Size"].default_value = 0.015
    brick.inputs["Mortar Smooth"].default_value = 0.1
    brick.inputs["Brick Width"].default_value = brick_width
    brick.inputs["Row Height"].default_value = row_height
    brick.offset = offset_val
    brick.offset_frequency = offset_freq

    # Box-projection wall coordinates
    _add_wall_coords(nodes, links, brick.inputs["Vector"], scale_val=scale)

    # Noise overlay for per-brick colour variation (weathering/age)
    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (-200, 200)
    noise.inputs["Scale"].default_value = 25.0
    noise.inputs["Detail"].default_value = 3.0
    noise.inputs["Roughness"].default_value = 0.6

    # Mix brick colour with noise for subtle variation
    mix_colour = nodes.new('ShaderNodeMixRGB')
    mix_colour.location = (200, 0)
    mix_colour.blend_type = 'OVERLAY'
    mix_colour.inputs["Fac"].default_value = 0.08  # subtle 8% overlay
    links.new(brick.outputs["Color"], mix_colour.inputs["Color1"])
    links.new(noise.outputs["Color"], mix_colour.inputs["Color2"])

    # Bump from brick pattern — stronger mortar groove depth
    bump = nodes.new('ShaderNodeBump')
    bump.location = (200, -200)
    bump.inputs["Strength"].default_value = 0.4
    bump.inputs["Distance"].default_value = 0.012

    links.new(mix_colour.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(brick.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # Roughness variation — mortar is smoother than brick faces
    rough_mix = nodes.new('ShaderNodeMixRGB')
    rough_mix.location = (200, -350)
    rough_mix.inputs["Color1"].default_value = (0.85, 0.85, 0.85, 1.0)  # brick roughness
    rough_mix.inputs["Color2"].default_value = (0.6, 0.6, 0.6, 1.0)    # mortar roughness
    links.new(brick.outputs["Fac"], rough_mix.inputs["Fac"])
    links.new(rough_mix.outputs["Color"], bsdf.inputs["Roughness"])

    return mat


def create_wood_material(name, wood_hex):
    """Create a procedural wood grain material with knots and weathering."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = _get_bsdf(mat)
    if not bsdf:
        return mat
    bsdf.inputs["Roughness"].default_value = 0.65

    r, g, b = hex_to_rgb(wood_hex)

    # Wood grain via wave texture
    wave = nodes.new('ShaderNodeTexWave')
    wave.location = (0, 0)
    wave.wave_type = 'RINGS'
    wave.inputs["Scale"].default_value = 3.0
    wave.inputs["Distortion"].default_value = 8.0
    wave.inputs["Detail"].default_value = 4.0
    wave.inputs["Detail Scale"].default_value = 2.0

    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.location = (200, 0)
    ramp.color_ramp.elements[0].color = (r * 0.65, g * 0.65, b * 0.65, 1.0)
    ramp.color_ramp.elements[1].color = (r, g, b, 1.0)

    _add_wall_coords(nodes, links, wave.inputs["Vector"], scale_val=1.0)

    # Knot pattern — scattered dark spots
    voronoi = nodes.new('ShaderNodeTexVoronoi')
    voronoi.location = (-200, 200)
    voronoi.inputs["Scale"].default_value = 8.0
    voronoi.distance = 'EUCLIDEAN'

    # Mix grain with knots
    knot_mix = nodes.new('ShaderNodeMixRGB')
    knot_mix.location = (400, 0)
    knot_mix.blend_type = 'DARKEN'
    knot_mix.inputs["Fac"].default_value = 0.05
    links.new(ramp.outputs["Color"], knot_mix.inputs["Color1"])
    links.new(voronoi.outputs["Distance"], knot_mix.inputs["Color2"])

    # Bump — wood grain ridges
    bump = nodes.new('ShaderNodeBump')
    bump.location = (200, -200)
    bump.inputs["Strength"].default_value = 0.2
    bump.inputs["Distance"].default_value = 0.005

    links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    links.new(knot_mix.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(wave.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # Roughness variation — grain ridges are smoother than flat wood
    rough_mix = nodes.new('ShaderNodeMixRGB')
    rough_mix.location = (200, -350)
    rough_mix.inputs["Color1"].default_value = (0.65, 0.65, 0.65, 1.0)  # flat grain
    rough_mix.inputs["Color2"].default_value = (0.45, 0.45, 0.45, 1.0)  # ridge polish
    links.new(wave.outputs["Fac"], rough_mix.inputs["Fac"])
    links.new(rough_mix.outputs["Color"], bsdf.inputs["Roughness"])

    return mat


def create_roof_material(name, roof_hex, condition="fair"):
    """Create a procedural roof shingle material with weathering streaks and edge wear.

    Args:
        condition: Building condition ("good"/"fair"/"poor") — affects moss and
                   weathering intensity.
    """
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = _get_bsdf(mat)
    if not bsdf:
        return mat
    bsdf.inputs["Roughness"].default_value = 0.92

    r, g, b = hex_to_rgb(roof_hex)

    # Shingle pattern via brick texture
    shingle = nodes.new('ShaderNodeTexBrick')
    shingle.location = (0, 0)
    shingle.inputs["Color1"].default_value = (
        min(1.0, r * 1.15), min(1.0, g * 1.15), min(1.0, b * 1.15), 1.0)
    shingle.inputs["Color2"].default_value = (r * 0.75, g * 0.75, b * 0.75, 1.0)
    shingle.inputs["Mortar"].default_value = (r * 0.4, g * 0.4, b * 0.4, 1.0)
    shingle.inputs["Scale"].default_value = 1.0
    shingle.inputs["Mortar Size"].default_value = 0.02
    shingle.inputs["Brick Width"].default_value = 0.25
    shingle.inputs["Row Height"].default_value = 0.12

    _add_wall_coords(nodes, links, shingle.inputs["Vector"], scale_val=15.0)

    # Weathering streaks — vertical dark bands from water runoff
    streak = nodes.new('ShaderNodeTexNoise')
    streak.location = (-200, 300)
    streak.inputs["Scale"].default_value = 2.0
    streak.inputs["Detail"].default_value = 1.0
    streak.inputs["Roughness"].default_value = 0.3
    streak.inputs["Distortion"].default_value = 3.0  # stretched vertically

    streak_mix = nodes.new('ShaderNodeMixRGB')
    streak_mix.location = (300, 0)
    streak_mix.blend_type = 'DARKEN'
    streak_mix.inputs["Fac"].default_value = 0.1
    links.new(shingle.outputs["Color"], streak_mix.inputs["Color1"])
    links.new(streak.outputs["Color"], streak_mix.inputs["Color2"])

    # Moss/algae patches on north-facing slopes (subtle green tint)
    moss = nodes.new('ShaderNodeTexNoise')
    moss.location = (-200, 500)
    moss.inputs["Scale"].default_value = 5.0
    moss.inputs["Detail"].default_value = 4.0

    moss_colour = nodes.new('ShaderNodeMixRGB')
    moss_colour.location = (500, 0)
    moss_colour.blend_type = 'MIX'
    # Condition-scaled moss: poor→15%, fair→4%, good→1%
    moss_pct = {"good": 0.01, "fair": 0.04, "poor": 0.15}.get(
        str(condition).lower(), 0.04
    )
    moss_colour.inputs["Fac"].default_value = moss_pct
    moss_colour.inputs["Color2"].default_value = (0.2, 0.3, 0.15, 1.0)
    links.new(streak_mix.outputs["Color"], moss_colour.inputs["Color1"])

    links.new(moss_colour.outputs["Color"], bsdf.inputs["Base Color"])

    # Bump — shingle edges
    bump = nodes.new('ShaderNodeBump')
    bump.location = (200, -200)
    bump.inputs["Strength"].default_value = 0.5
    bump.inputs["Distance"].default_value = 0.008
    links.new(shingle.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    return mat


def create_metal_roof_material(name, roof_hex):
    """Create a procedural standing-seam metal roof material with subtle panel lines.

    Used for metal, copper, tin, and galvanised roofing instead of the shingle
    brick-texture approach.
    """
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = _get_bsdf(mat)
    if not bsdf:
        return mat
    r, g, b = hex_to_rgb(roof_hex)

    bsdf.inputs["Roughness"].default_value = 0.35
    bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    # Metal roofs are reflective
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.75

    # Standing seam pattern — vertical ridges via wave texture
    wave = nodes.new('ShaderNodeTexWave')
    wave.location = (0, 0)
    wave.wave_type = 'BANDS'
    wave.bands_direction = 'X'
    wave.inputs["Scale"].default_value = 12.0
    wave.inputs["Distortion"].default_value = 0.0
    wave.inputs["Detail"].default_value = 0.0

    _add_wall_coords(nodes, links, wave.inputs["Vector"], scale_val=4.0)

    # Colour variation across panels — subtle shift per panel
    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.location = (200, 0)
    ramp.color_ramp.elements[0].color = (r * 0.90, g * 0.90, b * 0.90, 1.0)
    ramp.color_ramp.elements[1].color = (
        min(1.0, r * 1.05), min(1.0, g * 1.05), min(1.0, b * 1.05), 1.0
    )
    links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    # Weathering noise — subtle oxidation variation
    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (-200, 300)
    noise.inputs["Scale"].default_value = 8.0
    noise.inputs["Detail"].default_value = 3.0

    weather_mix = nodes.new('ShaderNodeMixRGB')
    weather_mix.location = (400, 0)
    weather_mix.blend_type = 'DARKEN'
    weather_mix.inputs["Fac"].default_value = 0.06
    links.new(ramp.outputs["Color"], weather_mix.inputs["Color1"])
    links.new(noise.outputs["Color"], weather_mix.inputs["Color2"])
    links.new(weather_mix.outputs["Color"], bsdf.inputs["Base Color"])

    # Bump — seam ridge profile
    bump = nodes.new('ShaderNodeBump')
    bump.location = (200, -200)
    bump.inputs["Strength"].default_value = 0.3
    bump.inputs["Distance"].default_value = 0.015
    links.new(wave.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # Roughness variation — seam ridges smoother, panels slightly rougher
    rough_mix = nodes.new('ShaderNodeMixRGB')
    rough_mix.location = (200, -350)
    rough_mix.inputs["Color1"].default_value = (0.38, 0.38, 0.38, 1.0)  # panel
    rough_mix.inputs["Color2"].default_value = (0.25, 0.25, 0.25, 1.0)  # seam
    links.new(wave.outputs["Fac"], rough_mix.inputs["Fac"])
    links.new(rough_mix.outputs["Color"], bsdf.inputs["Roughness"])

    return mat


def create_copper_patina_material(name, roof_hex):
    """Create a copper roof material with verdigris patina weathering.

    Aged copper develops a green-brown oxide layer (verdigris) that is
    visually distinct from galvanised steel or painted metal.  The shader
    blends the original copper tone with patina green, uses lower metallic
    (oxidised surface is mostly dielectric), rougher finish, and stronger
    weathering noise than the generic standing-seam shader.
    """
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = _get_bsdf(mat)
    if not bsdf:
        return mat

    # Base copper colour from param (usually brownish-orange)
    r, g, b = hex_to_rgb(roof_hex)

    # Verdigris patina tones — green-blue oxide
    patina_r, patina_g, patina_b = 0.30, 0.52, 0.42

    # Oxidised copper is mostly dielectric with residual metallic gleam
    bsdf.inputs["Roughness"].default_value = 0.55
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.45

    # Standing seam pattern (same panel geometry as generic metal)
    wave = nodes.new('ShaderNodeTexWave')
    wave.location = (0, 0)
    wave.wave_type = 'BANDS'
    wave.bands_direction = 'X'
    wave.inputs["Scale"].default_value = 12.0
    wave.inputs["Distortion"].default_value = 0.0
    wave.inputs["Detail"].default_value = 0.0

    _add_wall_coords(nodes, links, wave.inputs["Vector"], scale_val=4.0)

    # Noise mask — drives patina distribution (crevices/exposed areas)
    patina_noise = nodes.new('ShaderNodeTexNoise')
    patina_noise.location = (-400, 200)
    patina_noise.inputs["Scale"].default_value = 5.0
    patina_noise.inputs["Detail"].default_value = 6.0
    patina_noise.inputs["Roughness"].default_value = 0.7

    # Colour ramp to sharpen patina boundaries
    patina_ramp = nodes.new('ShaderNodeValToRGB')
    patina_ramp.location = (-200, 200)
    patina_ramp.color_ramp.elements[0].position = 0.35
    patina_ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
    patina_ramp.color_ramp.elements[1].position = 0.65
    patina_ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    links.new(patina_noise.outputs["Fac"], patina_ramp.inputs["Fac"])

    # Panel colour variation on the copper base
    panel_ramp = nodes.new('ShaderNodeValToRGB')
    panel_ramp.location = (200, 0)
    panel_ramp.color_ramp.elements[0].color = (r * 0.85, g * 0.85, b * 0.85, 1.0)
    panel_ramp.color_ramp.elements[1].color = (
        min(1.0, r * 1.08), min(1.0, g * 1.08), min(1.0, b * 1.08), 1.0
    )
    links.new(wave.outputs["Fac"], panel_ramp.inputs["Fac"])

    # Mix copper base with patina green, driven by noise mask
    patina_mix = nodes.new('ShaderNodeMixRGB')
    patina_mix.location = (400, 100)
    patina_mix.blend_type = 'MIX'
    patina_mix.inputs["Fac"].default_value = 0.0  # driven by ramp
    links.new(patina_ramp.outputs["Color"], patina_mix.inputs["Fac"])
    links.new(panel_ramp.outputs["Color"], patina_mix.inputs["Color1"])
    patina_mix.inputs["Color2"].default_value = (patina_r, patina_g, patina_b, 1.0)
    links.new(patina_mix.outputs["Color"], bsdf.inputs["Base Color"])

    # Weathering overlay — extra grime in crevices
    weather_noise = nodes.new('ShaderNodeTexNoise')
    weather_noise.location = (-200, -100)
    weather_noise.inputs["Scale"].default_value = 14.0
    weather_noise.inputs["Detail"].default_value = 4.0

    weather_mix = nodes.new('ShaderNodeMixRGB')
    weather_mix.location = (600, 100)
    weather_mix.blend_type = 'DARKEN'
    weather_mix.inputs["Fac"].default_value = 0.12
    links.new(patina_mix.outputs["Color"], weather_mix.inputs["Color1"])
    links.new(weather_noise.outputs["Color"], weather_mix.inputs["Color2"])
    links.new(weather_mix.outputs["Color"], bsdf.inputs["Base Color"])

    # Bump — seam ridges plus patina surface irregularity
    bump = nodes.new('ShaderNodeBump')
    bump.location = (400, -200)
    bump.inputs["Strength"].default_value = 0.35
    bump.inputs["Distance"].default_value = 0.018

    # Combine seam bump with patina texture bump
    bump_add = nodes.new('ShaderNodeMath')
    bump_add.location = (200, -200)
    bump_add.operation = 'ADD'
    links.new(wave.outputs["Fac"], bump_add.inputs[0])
    # Patina surface roughness adds micro-bump
    patina_bump_noise = nodes.new('ShaderNodeTexNoise')
    patina_bump_noise.location = (0, -300)
    patina_bump_noise.inputs["Scale"].default_value = 30.0
    patina_bump_noise.inputs["Detail"].default_value = 5.0
    bump_scale = nodes.new('ShaderNodeMath')
    bump_scale.location = (100, -300)
    bump_scale.operation = 'MULTIPLY'
    bump_scale.inputs[1].default_value = 0.3
    links.new(patina_bump_noise.outputs["Fac"], bump_scale.inputs[0])
    links.new(bump_scale.outputs["Value"], bump_add.inputs[1])
    links.new(bump_add.outputs["Value"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # Roughness — patina areas rougher than exposed copper
    rough_mix = nodes.new('ShaderNodeMixRGB')
    rough_mix.location = (400, -350)
    rough_mix.inputs["Color1"].default_value = (0.45, 0.45, 0.45, 1.0)  # copper panel
    rough_mix.inputs["Color2"].default_value = (0.70, 0.70, 0.70, 1.0)  # patina area
    links.new(patina_ramp.outputs["Color"], rough_mix.inputs["Fac"])
    links.new(rough_mix.outputs["Color"], bsdf.inputs["Roughness"])

    # Metallic — patina areas less metallic than exposed copper
    metal_mix = nodes.new('ShaderNodeMixRGB')
    metal_mix.location = (400, -500)
    metal_mix.inputs["Color1"].default_value = (0.65, 0.65, 0.65, 1.0)  # copper
    metal_mix.inputs["Color2"].default_value = (0.15, 0.15, 0.15, 1.0)  # patina
    links.new(patina_ramp.outputs["Color"], metal_mix.inputs["Fac"])
    if "Metallic" in bsdf.inputs:
        links.new(metal_mix.outputs["Color"], bsdf.inputs["Metallic"])

    return mat


def select_roof_material(name, roof_hex, params=None):
    """Choose shingle, metal, or copper patina roof material.

    Copper/verdigris materials use the patina shader with oxidised green-brown
    tones.  Other metal keywords (tin, galvanised, steel, standing seam) use
    the generic standing-seam metal shader.  Everything else (asphalt, shingle,
    slate, tile, or unspecified) uses the shingle/brick pattern.
    """
    rm = ""
    condition = "fair"
    if params:
        rm = str(params.get("roof_material", "")).lower()
        condition = (params.get("condition") or "fair").lower()
    # Copper-specific keywords → patina shader
    copper_keywords = ("copper", "verdigris", "patina")
    if any(kw in rm for kw in copper_keywords):
        return create_copper_patina_material(name, roof_hex)
    # Other metals → standing-seam shader
    metal_keywords = ("metal", "tin", "galvanised", "galvanized",
                      "standing seam", "steel", "aluminum", "aluminium")
    if any(kw in rm for kw in metal_keywords):
        return create_metal_roof_material(name, roof_hex)
    return create_roof_material(name, roof_hex, condition=condition)


def create_glass_material(name="mat_glass", glass_type="residential"):
    """Create a realistic glass material with sky reflection tint and dark interior.

    Args:
        name: Material name for Blender cache.
        glass_type: "residential" (darker, less transparent) or "storefront"
                    (larger panes, more transparent, warmer interior tint).
    """
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = _get_bsdf(mat)
    if not bsdf:
        return mat

    # Glass type presets — storefront vs residential
    glass_type = (glass_type or "residential").lower()
    if glass_type == "storefront":
        # Storefront: larger clear panes, warmer interior from merchandise/lighting
        interior_colour = (0.20, 0.22, 0.20, 1.0)  # warm grey-green
        reflection_colour = (0.50, 0.58, 0.65, 1.0)  # slightly warmer sky
        alpha = 0.20
        roughness = 0.02
        transmission = 0.75
        specular = 0.85
        fresnel_blend = 0.25
    else:
        # Residential: darker interior, smaller panes, more reflection
        interior_colour = (0.15, 0.18, 0.22, 1.0)  # cool blue-grey
        reflection_colour = (0.55, 0.65, 0.75, 1.0)  # sky reflection
        alpha = 0.35
        roughness = 0.03
        transmission = 0.6
        specular = 0.8
        fresnel_blend = 0.3

    bsdf.inputs["Base Color"].default_value = interior_colour
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Alpha"].default_value = alpha
    # Specular/reflection for sky bounce
    for key in ["Specular IOR Level", "Specular"]:
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = specular
            break
    # Transmission for see-through
    for key in ["Transmission Weight", "Transmission"]:
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = transmission
            break

    # Fresnel-like variation — more reflective at glancing angles
    layer_weight = nodes.new('ShaderNodeLayerWeight')
    layer_weight.location = (-200, 0)
    layer_weight.inputs["Blend"].default_value = fresnel_blend

    # Mix dark interior with sky reflection colour at edges
    mix = nodes.new('ShaderNodeMixRGB')
    mix.location = (0, 0)
    mix.inputs["Color1"].default_value = interior_colour
    mix.inputs["Color2"].default_value = reflection_colour
    links.new(layer_weight.outputs["Facing"], mix.inputs["Fac"])
    links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])

    try:
        mat.blend_method = 'BLEND'
    except (AttributeError, TypeError):
        pass
    return mat


def create_stone_material(name, stone_hex, condition="fair"):
    """Create a procedural stone/concrete material with veining and weathering.

    Args:
        name: Material name for Blender cache.
        stone_hex: Base stone colour as hex string.
        condition: Building condition — "good", "fair", or "poor".
            Controls staining/algae overlay intensity.
    """
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    condition = (condition or "fair").lower()
    stain_fac = {"good": 0.02, "fair": 0.05, "poor": 0.14}.get(condition, 0.05)
    bump_strength = {"good": 0.18, "fair": 0.25, "poor": 0.35}.get(condition, 0.25)
    base_roughness = {"good": 0.78, "fair": 0.85, "poor": 0.92}.get(condition, 0.85)

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = _get_bsdf(mat)
    if not bsdf:
        return mat
    bsdf.inputs["Roughness"].default_value = base_roughness

    r, g, b = hex_to_rgb(stone_hex)

    # Fine grain noise — stone surface texture
    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (0, 0)
    noise.inputs["Scale"].default_value = 25.0
    noise.inputs["Detail"].default_value = 6.0
    noise.inputs["Roughness"].default_value = 0.6

    # Larger scale noise — natural stone veining/colour bands
    vein = nodes.new('ShaderNodeTexNoise')
    vein.location = (0, 200)
    vein.inputs["Scale"].default_value = 3.0
    vein.inputs["Detail"].default_value = 2.0
    vein.inputs["Roughness"].default_value = 0.4
    vein.inputs["Distortion"].default_value = 1.5

    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.location = (200, 0)
    ramp.color_ramp.elements[0].color = (r * 0.82, g * 0.82, b * 0.82, 1.0)
    ramp.color_ramp.elements[1].color = (r, g, b, 1.0)

    # Mix fine + vein noise
    mix_noise = nodes.new('ShaderNodeMixRGB')
    mix_noise.location = (100, 100)
    mix_noise.blend_type = 'MIX'
    mix_noise.inputs["Fac"].default_value = 0.3
    links.new(noise.outputs["Fac"], mix_noise.inputs["Color1"])
    links.new(vein.outputs["Fac"], mix_noise.inputs["Color2"])

    _add_wall_coords(nodes, links, noise.inputs["Vector"], scale_val=1.0)

    # Staining/algae overlay — condition-driven darkening
    stain_noise = nodes.new('ShaderNodeTexNoise')
    stain_noise.location = (-200, 400)
    stain_noise.inputs["Scale"].default_value = 6.0
    stain_noise.inputs["Detail"].default_value = 3.0
    stain_noise.inputs["Roughness"].default_value = 0.8

    stain_mix = nodes.new('ShaderNodeMixRGB')
    stain_mix.location = (400, 0)
    stain_mix.blend_type = 'DARKEN'
    stain_mix.inputs["Fac"].default_value = stain_fac

    links.new(mix_noise.outputs["Color"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], stain_mix.inputs["Color1"])
    links.new(stain_noise.outputs["Color"], stain_mix.inputs["Color2"])
    links.new(stain_mix.outputs["Color"], bsdf.inputs["Base Color"])

    bump = nodes.new('ShaderNodeBump')
    bump.location = (200, -200)
    bump.inputs["Strength"].default_value = bump_strength
    bump.inputs["Distance"].default_value = 0.008
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # Roughness variation — polished veining vs rough grain
    rough_mix = nodes.new('ShaderNodeMixRGB')
    rough_mix.location = (200, -350)
    rough_grain = min(1.0, base_roughness + 0.02)
    rough_polish = max(0.0, base_roughness - 0.20)
    rough_mix.inputs["Color1"].default_value = (rough_grain, rough_grain, rough_grain, 1.0)
    rough_mix.inputs["Color2"].default_value = (rough_polish, rough_polish, rough_polish, 1.0)
    links.new(vein.outputs["Fac"], rough_mix.inputs["Fac"])
    links.new(rough_mix.outputs["Color"], bsdf.inputs["Roughness"])

    return mat


def create_painted_material(name, paint_hex, condition="fair"):
    """Create a painted surface material with wear/aging, edge chipping, and bump.

    Args:
        name: Material name for Blender cache.
        paint_hex: Base paint colour as hex string.
        condition: Building condition — "good", "fair", or "poor".
            Controls weathering intensity: good=2%, fair=6%, poor=18%.
    """
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    condition = (condition or "fair").lower()
    # Condition-driven weathering parameters
    weather_fac = {"good": 0.02, "fair": 0.06, "poor": 0.18}.get(condition, 0.06)
    bump_strength = {"good": 0.06, "fair": 0.10, "poor": 0.20}.get(condition, 0.10)
    base_roughness = {"good": 0.68, "fair": 0.75, "poor": 0.85}.get(condition, 0.75)
    colour_fade = {"good": 0.96, "fair": 0.92, "poor": 0.82}.get(condition, 0.92)

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = _get_bsdf(mat)
    if not bsdf:
        return mat
    bsdf.inputs["Roughness"].default_value = base_roughness

    r, g, b = hex_to_rgb(paint_hex)

    # Fine surface noise — paint texture
    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (0, 0)
    noise.inputs["Scale"].default_value = 40.0
    noise.inputs["Detail"].default_value = 3.0

    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.location = (200, 0)
    ramp.color_ramp.elements[0].color = (r * colour_fade, g * colour_fade, b * colour_fade, 1.0)
    ramp.color_ramp.elements[1].color = (r, g, b, 1.0)

    _add_wall_coords(nodes, links, noise.inputs["Vector"], scale_val=1.0)

    # Weathering overlay — larger patches of discolouration near edges
    weather = nodes.new('ShaderNodeTexNoise')
    weather.location = (-200, 300)
    weather.inputs["Scale"].default_value = 4.0
    weather.inputs["Detail"].default_value = 2.0
    weather.inputs["Roughness"].default_value = 0.7

    # Darken paint slightly in weathered areas (condition-scaled)
    weather_mix = nodes.new('ShaderNodeMixRGB')
    weather_mix.location = (400, 0)
    weather_mix.blend_type = 'DARKEN'
    weather_mix.inputs["Fac"].default_value = weather_fac

    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], weather_mix.inputs["Color1"])
    links.new(weather.outputs["Color"], weather_mix.inputs["Color2"])
    links.new(weather_mix.outputs["Color"], bsdf.inputs["Base Color"])

    # Bump — paint surface texture (stronger on poor condition)
    bump = nodes.new('ShaderNodeBump')
    bump.location = (200, -200)
    bump.inputs["Strength"].default_value = bump_strength
    bump.inputs["Distance"].default_value = 0.003
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # Roughness variation — weathered patches are rougher than fresh paint
    rough_mix = nodes.new('ShaderNodeMixRGB')
    rough_mix.location = (400, -200)
    rough_fresh = max(0.0, base_roughness - 0.05)
    rough_worn = min(1.0, base_roughness + 0.13)
    rough_mix.inputs["Color1"].default_value = (rough_fresh, rough_fresh, rough_fresh, 1.0)
    rough_mix.inputs["Color2"].default_value = (rough_worn, rough_worn, rough_worn, 1.0)
    links.new(weather.outputs["Fac"], rough_mix.inputs["Fac"])
    links.new(rough_mix.outputs["Color"], bsdf.inputs["Roughness"])

    return mat


def create_canvas_material(name, canvas_hex):
    """Create a woven canvas/fabric material for awnings and canopies.

    Features a fine weave pattern via wave texture, subtle fold creasing,
    and higher roughness than painted surfaces (matte fabric finish).
    """
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = _get_bsdf(mat)
    if not bsdf:
        return mat
    bsdf.inputs["Roughness"].default_value = 0.82

    r, g, b = hex_to_rgb(canvas_hex)

    # Woven fabric pattern — crossed wave textures for warp/weft
    warp = nodes.new('ShaderNodeTexWave')
    warp.location = (0, 0)
    warp.wave_type = 'BANDS'
    warp.bands_direction = 'X'
    warp.inputs["Scale"].default_value = 80.0
    warp.inputs["Distortion"].default_value = 0.2
    warp.inputs["Detail"].default_value = 1.0

    weft = nodes.new('ShaderNodeTexWave')
    weft.location = (0, 200)
    weft.wave_type = 'BANDS'
    weft.bands_direction = 'Z'
    weft.inputs["Scale"].default_value = 80.0
    weft.inputs["Distortion"].default_value = 0.2
    weft.inputs["Detail"].default_value = 1.0

    _add_wall_coords(nodes, links, warp.inputs["Vector"], scale_val=1.0)

    # Combine warp + weft into crosshatch weave pattern
    weave_add = nodes.new('ShaderNodeMath')
    weave_add.location = (200, 100)
    weave_add.operation = 'ADD'
    links.new(warp.outputs["Fac"], weave_add.inputs[0])
    links.new(weft.outputs["Fac"], weave_add.inputs[1])

    # Colour variation across fabric — slight thread colour shift
    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.location = (400, 100)
    ramp.color_ramp.elements[0].color = (r * 0.88, g * 0.88, b * 0.88, 1.0)
    ramp.color_ramp.elements[1].color = (
        min(1.0, r * 1.04), min(1.0, g * 1.04), min(1.0, b * 1.04), 1.0
    )
    links.new(weave_add.outputs["Value"], ramp.inputs["Fac"])

    # Fold/crease noise — larger scale folds from gravity
    fold = nodes.new('ShaderNodeTexNoise')
    fold.location = (-200, 300)
    fold.inputs["Scale"].default_value = 3.0
    fold.inputs["Detail"].default_value = 2.0
    fold.inputs["Roughness"].default_value = 0.6

    weather_mix = nodes.new('ShaderNodeMixRGB')
    weather_mix.location = (600, 100)
    weather_mix.blend_type = 'DARKEN'
    weather_mix.inputs["Fac"].default_value = 0.08
    links.new(ramp.outputs["Color"], weather_mix.inputs["Color1"])
    links.new(fold.outputs["Color"], weather_mix.inputs["Color2"])
    links.new(weather_mix.outputs["Color"], bsdf.inputs["Base Color"])

    # Bump — weave texture gives micro-surface relief
    bump = nodes.new('ShaderNodeBump')
    bump.location = (400, -200)
    bump.inputs["Strength"].default_value = 0.12
    bump.inputs["Distance"].default_value = 0.002
    links.new(weave_add.outputs["Value"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # Roughness variation — fold creases are slightly smoother from wear
    rough_mix = nodes.new('ShaderNodeMixRGB')
    rough_mix.location = (600, -200)
    rough_mix.inputs["Color1"].default_value = (0.85, 0.85, 0.85, 1.0)  # fabric
    rough_mix.inputs["Color2"].default_value = (0.72, 0.72, 0.72, 1.0)  # crease
    links.new(fold.outputs["Fac"], rough_mix.inputs["Fac"])
    links.new(rough_mix.outputs["Color"], bsdf.inputs["Roughness"])

    return mat


def get_utility_anchor_height(params):
    """Calculate realistic utility wire anchor height (mid-facade spaghetti)."""
    total_h = params.get("total_height_m", 9.0)
    # Urban Realism: Anchor at ~70% height for classic Kensington grit
    return params.get("utility_anchor_height_m", total_h * 0.7)


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
        "brick": "#B85A3A",
        "red_brick": "#B85A3A",
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
    result = colour_name_to_hex(merged)
    if result == "#808080" and default != "#808080":
        return default
    return result


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


def _clean_mesh(obj):
    """Remove doubles, dissolve degenerates, recalculate normals on *obj*."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    try:
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
    except Exception:
        pass
    try:
        bpy.ops.mesh.dissolve_degenerate(threshold=0.0001)
    except Exception:
        pass
    try:
        bpy.ops.mesh.normals_make_consistent(inside=False)
    except Exception:
        pass
    bpy.ops.object.mode_set(mode='OBJECT')


def boolean_cut(target, cutter, remove_cutter=True):
    """Apply a boolean difference operation with retry and mesh-cleanup."""
    if target is None or cutter is None:
        if remove_cutter and cutter is not None:
            try:
                bpy.data.objects.remove(cutter, do_unlink=True)
            except Exception:
                pass
        return

    # Triangulate cutter for reliable booleans with curved geometry
    try:
        bpy.context.view_layer.objects.active = cutter
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.quads_convert_to_tris(quad_method='BEAUTY', ngon_method='BEAUTY')
        bpy.ops.object.mode_set(mode='OBJECT')
    except Exception as exc:
        print(f"    [WARN] Cutter triangulation failed ({exc}), proceeding anyway")
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

    # Try boolean with up to 3 attempts: raw → clean-target → clean-both
    solvers = ['EXACT', 'FAST', 'FLOAT']
    succeeded = False

    for attempt in range(3):
        if attempt == 1:
            # Second attempt: clean target mesh before retry
            _clean_mesh(target)
        elif attempt == 2:
            # Third attempt: clean both meshes
            _clean_mesh(target)
            if cutter is not None:
                _clean_mesh(cutter)

        for solver in solvers:
            mod = target.modifiers.new(name="Bool", type='BOOLEAN')
            mod.operation = 'DIFFERENCE'
            mod.object = cutter
            try:
                mod.solver = solver
            except TypeError:
                target.modifiers.remove(mod)
                continue

            bpy.context.view_layer.objects.active = target
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
                succeeded = True
                break
            except RuntimeError as exc:
                # Modifier apply failed — remove it and try next solver
                print(f"    [WARN] Boolean {solver} attempt {attempt + 1} failed: {exc}")
                try:
                    target.modifiers.remove(mod)
                except Exception:
                    pass
                continue

        if succeeded:
            break

    if not succeeded:
        # All attempts exhausted — log and clean up without crashing
        name = getattr(target, "name", "?")
        cutter_name = getattr(cutter, "name", "?")
        print(f"    [ERROR] Boolean cut failed after 3 attempts: target={name}, cutter={cutter_name}")

    if remove_cutter and cutter is not None:
        try:
            bpy.data.objects.remove(cutter, do_unlink=True)
        except Exception:
            pass

    # Fix normals after boolean
    try:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass


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
    except (ValueError, IndexError):
        pass  # Duplicate face or degenerate verts
    # Back face
    try:
        bm.faces.new(list(reversed(back_verts)))
    except (ValueError, IndexError):
        pass  # Duplicate face or degenerate verts
    # Side faces
    for i in range(n):
        j = (i + 1) % n
        try:
            bm.faces.new([front_verts[i], front_verts[j], back_verts[j], back_verts[i]])
        except (ValueError, IndexError):
            pass  # Duplicate face or degenerate verts

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


def get_accent_hex(params):
    """Get accent colour hex from colour_palette, falling back to stone default."""
    cp = params.get("colour_palette", {})
    if isinstance(cp, dict):
        accent = cp.get("accent", {})
        if isinstance(accent, dict):
            h = accent.get("hex_approx", "")
            if h and h.startswith("#"):
                return h
    return "#D4C9A8"


def get_stone_element_hex(params, element_dict=None, default="#D4C9A8"):
    """Resolve colour for stone decorative elements (voussoirs, string courses, etc.).

    Priority: element dict → colour_palette.accent → hardcoded default.
    """
    if isinstance(element_dict, dict):
        h = element_dict.get("colour_hex", "")
        if h and h.startswith("#"):
            return h
    return get_accent_hex(params)


def get_condition_roughness_bias(params):
    """Return roughness bias based on building condition.

    poor → +0.08 (more weathered), good → -0.04 (cleaner surfaces).
    """
    condition = (params.get("condition") or "fair").lower()
    rating = params.get("assessment", {})
    if isinstance(rating, dict):
        cr = rating.get("condition_rating")
        if isinstance(cr, (int, float)):
            if cr <= 2:
                condition = "poor"
            elif cr >= 4:
                condition = "good"
    return {"good": -0.04, "fair": 0.0, "poor": 0.08}.get(condition, 0.0)


def get_condition_saturation_shift(params):
    """Return saturation multiplier based on building condition.

    poor → 0.85 (desaturated/faded), good → 1.0.
    """
    condition = (params.get("condition") or "fair").lower()
    return {"good": 1.0, "fair": 0.95, "poor": 0.85}.get(condition, 0.95)


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

    # Resolve stone decorative element colour from colour_palette.accent
    stone_hex = get_accent_hex(params)

    if has("string course", "string courses") and "string_courses" not in decorative:
        decorative["string_courses"] = {
            "present": True,
            "width_mm": 140,
            "projection_mm": 25,
            "colour_hex": stone_hex,
        }

    if has("quoin", "quoining") and "quoins" not in decorative:
        decorative["quoins"] = {
            "present": True,
            "strip_width_mm": 220,
            "projection_mm": 18,
            "colour_hex": stone_hex,
        }

    if has("voussoir", "voussoirs") and "stone_voussoirs" not in decorative and "voussoirs" not in decorative:
        decorative["stone_voussoirs"] = {
            "present": True,
            "colour_hex": stone_hex,
        }

    if has("stone lintel", "stone lintels", "stone sills") and "stone_lintels" not in decorative:
        decorative["stone_lintels"] = {
            "present": True,
            "colour_hex": stone_hex,
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
            "colour_hex": stone_hex,
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
    """Create the main building walls as a hollow box with water table and party wall blanking."""
    width = _clamp_positive(params.get("facade_width_m"), 6.0, minimum=1.0)
    if depth is None:
        depth = _clamp_positive(params.get("facade_depth_m"), DEFAULT_DEPTH, minimum=1.0)
    else:
        depth = _clamp_positive(depth, DEFAULT_DEPTH, minimum=1.0)
    total_h = _clamp_positive(params.get("total_height_m"), 9.0, minimum=2.0)

    # Get wall height (up to eave, not gable peak)
    floor_heights = params.get("floor_heights_m", [3.0])
    if not floor_heights or not isinstance(floor_heights, list):
        floor_heights = [3.0]
    wall_h = sum(max(0.5, float(fh)) for fh in floor_heights)

    wall_thickness = params.get("wall_thickness_m", 0.3)

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
        elif isinstance(mc, str) and mc.startswith("#"):
            mortar_hex = mc

    # Bond pattern from facade_detail or deep_facade_analysis
    bond_pattern = "running"
    if isinstance(fd, dict):
        bp = (fd.get("bond_pattern") or "").lower()
        if bp:
            bond_pattern = bp
    dfa = params.get("deep_facade_analysis", {})
    if isinstance(dfa, dict):
        bp_dfa = (dfa.get("brick_bond_observed") or "").lower()
        if bp_dfa:
            bond_pattern = bp_dfa

    # Polychromatic brick accent colour (Victorian decorative banding)
    polychrome_hex = None
    if isinstance(dfa, dict):
        poly = dfa.get("polychromatic_brick")
        if isinstance(poly, dict):
            ph = poly.get("accent_hex", "")
            if ph and ph.startswith("#"):
                polychrome_hex = ph
    de = params.get("decorative_elements", {})
    if isinstance(de, dict) and not polychrome_hex:
        poly_de = de.get("polychromatic_brick")
        if isinstance(poly_de, dict):
            ph = poly_de.get("colour_hex", "")
            if ph and ph.startswith("#"):
                polychrome_hex = ph

    condition = (params.get("condition") or "fair").lower()

    if "brick" in mat_type:
        mat = create_brick_material(f"mat_brick_{hex_id}", facade_hex, mortar_hex,
                                    bond_pattern=bond_pattern,
                                    polychrome_hex=polychrome_hex)
    elif "stone" in mat_type or "concrete" in mat_type:
        mat = create_stone_material(f"mat_stone_{hex_id}", facade_hex,
                                    condition=condition)
    elif "clapboard" in mat_type or "wood siding" in mat_type:
        mat = create_wood_material(f"mat_wood_{hex_id}", facade_hex)
    elif (
        "paint" in mat_type
        or "stucco" in mat_type
        or "wood" in mat_type
        or "vinyl" in mat_type
        or "siding" in mat_type
    ):
        mat = create_painted_material(f"mat_painted_{hex_id}", facade_hex,
                                      condition=condition)
    else:
        mat = create_brick_material(f"mat_facade_{hex_id}", facade_hex, mortar_hex,
                                    bond_pattern=bond_pattern,
                                    polychrome_hex=polychrome_hex)

    # Condition-based weathering: bias base roughness by building condition
    roughness_bias = get_condition_roughness_bias(params)
    if roughness_bias != 0.0:
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            base_r = bsdf.inputs["Roughness"].default_value
            if isinstance(base_r, float):
                bsdf.inputs["Roughness"].default_value = max(0.1, min(1.0, base_r + roughness_bias))

    assign_material(outer, mat)

    # Water table — subtle stone band at base of facade (above foundation)
    foundation_h = params.get("foundation_height_m", 0.3)
    wt_h = 0.08  # water table height
    wt_proj = 0.02  # slight projection
    trim_hex = get_trim_hex(params)
    wt_mat = create_stone_material(f"mat_watertable_{trim_hex.lstrip('#')}",
                                    trim_hex, condition=condition)
    bpy.ops.mesh.primitive_cube_add(size=1)
    wt = bpy.context.active_object
    wt.name = "water_table"
    wt.scale = (width + wt_proj * 2, wt_proj * 2, wt_h)
    bpy.ops.object.transform_apply(scale=True)
    wt.location = (0, wt_proj, foundation_h + wt_h / 2)
    assign_material(wt, wt_mat)

    # Party wall blanking — close off exposed side walls with flat material
    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)
    pw_mat = get_or_create_material("mat_party_wall", colour_hex="#6A6A6A", roughness=0.95)
    hw = width / 2

    if party_left:
        bpy.ops.mesh.primitive_plane_add(size=1)
        pw = bpy.context.active_object
        pw.name = "party_wall_left"
        pw.scale = (1, depth, wall_h)
        bpy.ops.object.transform_apply(scale=True)
        pw.rotation_euler.y = math.pi / 2
        pw.location = (-hw - 0.005, -depth / 2, wall_h / 2)
        assign_material(pw, pw_mat)

    if party_right:
        bpy.ops.mesh.primitive_plane_add(size=1)
        pw = bpy.context.active_object
        pw.name = "party_wall_right"
        pw.scale = (1, depth, wall_h)
        bpy.ops.object.transform_apply(scale=True)
        pw.rotation_euler.y = math.pi / 2
        pw.location = (hw + 0.005, -depth / 2, wall_h / 2)
        assign_material(pw, pw_mat)

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
                ridge_h = (facade_width / 2) * _safe_tan(pitch)
                gable_center_z = wall_h + ridge_h * 0.45  # slightly below center
                sill_h = gable_center_z - h / 2
            else:
                # Resolve sill height — above_grade is absolute, sill_height_m is
                # relative to this floor's base
                sill_above_grade = (
                    win_spec.get("sill_height_above_grade_m")
                    or floor_data.get("sill_height_above_grade_m")
                )
                sill_relative = win_spec.get("sill_height_m")
                if sill_above_grade is not None:
                    # Absolute from ground level — do NOT add z_base
                    sill_h = float(sill_above_grade)
                elif sill_relative is not None:
                    # Relative to this floor's base
                    sill_h = z_base + float(sill_relative)
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
                # Clamp total window span to facade width so windows stay inside the wall
                if total_win_width > facade_width:
                    total_win_width = facade_width
                start_x = -total_win_width / 2 + w / 2
                spacing = (total_win_width - w) / max(1, count - 1) if count > 1 else 0
                x_positions = [start_x + i * spacing if count > 1 else 0 for i in range(count)]

            # Clamp all window x-positions to stay within facade bounds
            hw_limit = facade_width / 2 - w / 2 - 0.05
            x_positions = [max(-hw_limit, min(hw_limit, xp)) for xp in x_positions]

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
                frame_is_metal = False
                wf_colour = win_spec.get("frame_colour", win_spec.get("frame_colour_hex", ""))
                if isinstance(wf_colour, str) and wf_colour.startswith("#"):
                    frame_hex = wf_colour
                elif isinstance(wf_colour, str) and "bronze" in wf_colour.lower():
                    frame_hex = "#4A3A2A"
                    frame_is_metal = True
                elif isinstance(wf_colour, str) and "dark" in wf_colour.lower():
                    frame_hex = "#3A3A3A"
                elif isinstance(wf_colour, str) and any(
                    kw in wf_colour.lower() for kw in ("metal", "aluminum", "steel")
                ):
                    frame_is_metal = True
                if frame_is_metal:
                    frame_mat = get_or_create_material(
                        f"mat_frame_metal_{frame_hex.lstrip('#')}",
                        colour_hex=frame_hex, roughness=0.3, metallic=0.7)
                else:
                    frame_mat = create_wood_material(
                        f"mat_frame_wood_{frame_hex.lstrip('#')}", frame_hex)

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
            aw_mat = create_canvas_material(f"mat_awning_{aw_hex.lstrip('#')}", aw_hex)
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
    ridge_height = (width / 2) * _safe_tan(pitch)

    facade_hex = get_facade_hex(params)
    hex_id = facade_hex.lstrip('#')
    mat_type = str(params.get("facade_material", "brick")).lower()
    # Resolve bond pattern for gable walls (same as main facade)
    fd_gw = params.get("facade_detail", {})
    bond_gw = "running"
    if isinstance(fd_gw, dict):
        bp_gw = (fd_gw.get("bond_pattern") or "").lower()
        if bp_gw:
            bond_gw = bp_gw
    dfa_gw = params.get("deep_facade_analysis", {})
    if isinstance(dfa_gw, dict):
        bp_dfa_gw = (dfa_gw.get("brick_bond_observed") or "").lower()
        if bp_dfa_gw:
            bond_gw = bp_dfa_gw

    if "brick" in mat_type:
        mat = create_brick_material(f"mat_brick_{hex_id}", facade_hex,
                                    bond_pattern=bond_gw)
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
        mat = create_brick_material(f"mat_facade_{hex_id}", facade_hex,
                                    bond_pattern=bond_gw)

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

    ridge_height = (width / 2) * _safe_tan(pitch)

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

    mat = select_roof_material(f"mat_roof_{roof_hex.lstrip('#')}", roof_hex, params)
    assign_material(obj, mat)

    # Ridge cap — contrasting strip along the roof peak
    trim_hex = get_trim_hex(params)
    ridge_mat = get_or_create_material(f"mat_ridge_{trim_hex.lstrip('#')}",
                                        colour_hex=trim_hex, roughness=0.5)
    ridge_len = abs(y_front - y_back)
    bpy.ops.mesh.primitive_cube_add(size=1)
    ridge_cap = bpy.context.active_object
    ridge_cap.name = "ridge_cap"
    ridge_cap.scale = (0.08, ridge_len, 0.04)
    bpy.ops.object.transform_apply(scale=True)
    ridge_cap.location = (0, (y_front + y_back) / 2, wall_h + ridge_height + 0.02)
    assign_material(ridge_cap, ridge_mat)

    return obj, ridge_height


def create_cross_gable_roof(params, wall_h, width, depth):
    """Create a cross-gable roof for bay-and-gable buildings.

    Main roof: side gable (ridge runs left-right, parallel to facade).
    Secondary: front-facing cross-gable projecting forward from main roof.
    """
    pitch = params.get("roof_pitch_deg", 35)

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
    main_ridge_height = (width / 2) * _safe_tan(pitch)
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

    mat = select_roof_material(f"mat_roof_{roof_hex.lstrip('#')}", roof_hex, params)
    assign_material(obj_main, mat)

    # --- Secondary cross-gable (front-facing, projects forward) ---
    cross_w = width * 0.5  # roughly half facade width
    cross_ridge_height = (cross_w / 2) * _safe_tan(pitch)
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

    hip_height = min(width, depth) / 2 * _safe_tan(pitch)
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

    mat = select_roof_material(f"mat_roof_{roof_hex.lstrip('#')}", roof_hex, params)
    assign_material(obj, mat)

    return obj, hip_height


def create_flat_roof(params, wall_h, width, depth):
    """Create a flat roof with parapet walls, coping cap, and roof surface."""
    parapet_h = 0.3
    cornice = params.get("cornice", {})
    if isinstance(cornice, dict):
        parapet_h = cornice.get("height_mm", 300) / 1000
    parapet_h = max(0.2, min(parapet_h, 0.8))

    parapet_thickness = 0.15
    coping_proj = 0.03  # coping overhang beyond parapet

    roof_hex = get_roof_hex(params)
    roof_mat = select_roof_material(f"mat_roof_{roof_hex.lstrip('#')}", roof_hex, params)
    trim_hex = get_trim_hex(params)
    parapet_mat = get_or_create_material("mat_parapet", colour_hex=get_facade_hex(params), roughness=0.85)
    coping_mat = create_stone_material(f"mat_coping_{trim_hex.lstrip('#')}", trim_hex)

    hw = width / 2
    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)

    # Roof surface plane
    bpy.ops.mesh.primitive_plane_add(size=1)
    roof = bpy.context.active_object
    roof.name = "roof_flat"
    roof.scale = (width + 0.1, depth + 0.1, 1)
    bpy.ops.object.transform_apply(scale=True)
    roof.location = (0, -depth / 2, wall_h + 0.01)
    assign_material(roof, roof_mat)

    # Front parapet wall
    bpy.ops.mesh.primitive_cube_add(size=1)
    pf = bpy.context.active_object
    pf.name = "parapet_front"
    pf.scale = (width + 0.02, parapet_thickness, parapet_h)
    bpy.ops.object.transform_apply(scale=True)
    pf.location = (0, parapet_thickness / 2, wall_h + parapet_h / 2)
    assign_material(pf, parapet_mat)

    # Front coping cap
    bpy.ops.mesh.primitive_cube_add(size=1)
    cf = bpy.context.active_object
    cf.name = "coping_front"
    cf.scale = (width + coping_proj * 2 + 0.02, parapet_thickness + coping_proj * 2, 0.04)
    bpy.ops.object.transform_apply(scale=True)
    cf.location = (0, parapet_thickness / 2, wall_h + parapet_h + 0.02)
    assign_material(cf, coping_mat)

    # Side parapets (skip party wall sides)
    # Side parapet ratio — heritage buildings typically have side parapets at
    # 75-85% of front height, tapering toward the back.  Allow override from
    # roof_detail.side_parapet_ratio (0.0-1.0).
    rd = params.get("roof_detail", {})
    side_ratio = 0.80  # default
    if isinstance(rd, dict):
        sr = rd.get("side_parapet_ratio")
        if isinstance(sr, (int, float)) and 0.0 < sr <= 1.0:
            side_ratio = float(sr)
    side_parapet_h = parapet_h * side_ratio

    if not party_left:
        bpy.ops.mesh.primitive_cube_add(size=1)
        pl = bpy.context.active_object
        pl.name = "parapet_left"
        pl.scale = (parapet_thickness, depth, side_parapet_h)
        bpy.ops.object.transform_apply(scale=True)
        pl.location = (-hw, -depth / 2, wall_h + side_parapet_h / 2)
        assign_material(pl, parapet_mat)

    if not party_right:
        bpy.ops.mesh.primitive_cube_add(size=1)
        pr = bpy.context.active_object
        pr.name = "parapet_right"
        pr.scale = (parapet_thickness, depth, side_parapet_h)
        bpy.ops.object.transform_apply(scale=True)
        pr.location = (hw, -depth / 2, wall_h + side_parapet_h / 2)
        assign_material(pr, parapet_mat)

    return roof, parapet_h


def create_porch(params, facade_width):
    """Create a front porch with posts and optional roof."""
    porch_data = params.get("porch", {})
    if not isinstance(porch_data, dict):
        return []
    if not porch_data.get("present", porch_data.get("type")):
        return []

    porch_w = min(porch_data.get("width_m", facade_width), facade_width)
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

    post_mat = create_wood_material(f"mat_post_{post_colour.lstrip('#')}", post_colour)

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
            step_mat = create_stone_material("mat_porch_step", "#9A9A9A")
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
    """Create chimneys with corbelled cap and flue pot."""
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
            # Check top-level chimneys field
            ch_top = params.get("chimneys", {})
            if isinstance(ch_top, dict) and ch_top.get("count", 0) > 0:
                chimney_data = ch_top
            elif isinstance(ch_top, int) and ch_top > 0:
                chimney_data = {"count": ch_top}
            else:
                return []

    count = chimney_data.get("count", 0)
    if count == 0:
        return []

    objects = []
    facade_hex = get_facade_hex(params)
    brick_mat = create_brick_material(f"mat_chimney_brick_{facade_hex.lstrip('#')}",
                                       facade_hex, "#8A8A8A", scale=12.0)
    cap_mat = create_stone_material("mat_chimney_cap", "#6A6A6A")

    hw = width / 2
    depth = params.get("facade_depth_m", DEFAULT_DEPTH)

    # Build chimney positions from data or defaults
    chimney_specs = []
    for key in ["left_chimney", "right_chimney"]:
        ch = chimney_data.get(key, {})
        if isinstance(ch, dict) and ch:
            chimney_specs.append((key, ch))

    # If no explicit left/right but count > 0, create defaults
    if not chimney_specs and count > 0:
        if count >= 2:
            chimney_specs.append(("left_chimney", {"position": "left", "width_m": 0.5, "depth_m": 0.4}))
            chimney_specs.append(("right_chimney", {"position": "right", "width_m": 0.5, "depth_m": 0.4}))
        else:
            chimney_specs.append(("right_chimney", {"position": "right", "width_m": 0.5, "depth_m": 0.4}))

    for key, ch in chimney_specs:
        ch_w = min(ch.get("width_m", 0.5), width * 0.4)  # cap at 40% of facade
        ch_d = min(ch.get("depth_m", 0.4), depth * 0.3)   # cap at 30% of depth
        above = ch.get("height_above_ridge_m", 1.0)
        above = min(above, 1.5)

        pos = str(ch.get("position", key)).lower()
        if "left" in pos:
            x = -hw + ch_w / 2
        elif "right" in pos:
            x = hw - ch_w / 2
        else:
            x = 0

        ch_bottom = wall_h * 0.6
        ch_top = wall_h + ridge_height + above
        ch_h = ch_top - ch_bottom
        ch_y = -depth * 0.3

        # Main chimney shaft
        bpy.ops.mesh.primitive_cube_add(size=1)
        chimney = bpy.context.active_object
        chimney.name = f"chimney_{key}"
        chimney.scale = (ch_w, ch_d, ch_h)
        bpy.ops.object.transform_apply(scale=True)
        chimney.location = (x, ch_y, ch_bottom + ch_h / 2)
        assign_material(chimney, brick_mat)
        objects.append(chimney)

        # Corbelled cap — wider band at top
        cap_proj = 0.04
        cap_h = 0.08
        bpy.ops.mesh.primitive_cube_add(size=1)
        corbel = bpy.context.active_object
        corbel.name = f"chimney_corbel_{key}"
        corbel.scale = (ch_w + cap_proj * 2, ch_d + cap_proj * 2, cap_h)
        bpy.ops.object.transform_apply(scale=True)
        corbel.location = (x, ch_y, ch_top - cap_h / 2)
        assign_material(corbel, brick_mat)
        objects.append(corbel)

        # Concrete cap slab
        bpy.ops.mesh.primitive_cube_add(size=1)
        slab = bpy.context.active_object
        slab.name = f"chimney_cap_{key}"
        slab.scale = (ch_w + cap_proj * 3, ch_d + cap_proj * 3, 0.04)
        bpy.ops.object.transform_apply(scale=True)
        slab.location = (x, ch_y, ch_top + 0.02)
        assign_material(slab, cap_mat)
        objects.append(slab)

        # Flue pot — small cylinder on top
        bpy.ops.mesh.primitive_cylinder_add(radius=0.08, depth=0.15, vertices=8)
        flue = bpy.context.active_object
        flue.name = f"chimney_flue_{key}"
        flue.location = (x, ch_y, ch_top + 0.04 + 0.075)
        assign_material(flue, cap_mat)
        objects.append(flue)

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

    facade_depth = params.get("facade_depth_m", 10.0)
    for bay, floor_idx in bay_specs:
        proj = bay.get("projection_m", 0.4)
        # Clamp projection to 20% of facade depth (prevents geometry beyond footprint)
        proj = min(proj, facade_depth * 0.2, 1.5)
        bay_w = min(bay.get("width_m", 2.5), facade_width - 0.2)  # leave 0.1m each side
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

        # Cap bay height so it doesn't extend above wall_h (into gable zone)
        max_bay_h = wall_h - z_base - sill_offset
        if max_bay_h > 0 and bay_h > max_bay_h:
            bay_h = max_bay_h

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

        # --- Determine bay type: canted (3-sided), oriel, or box ---
        bay_type = bay.get("type", "")
        sides = bay.get("sides", 0)
        bay_type_lower = str(bay_type).lower()
        is_canted = (
            sides == 3
            or "three_sided" in bay_type_lower
            or "canted" in bay_type_lower
        )
        is_oriel = "oriel" in bay_type_lower

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

        # Oriel bays: add corbel brackets underneath (cantilevered, not ground-supported)
        if is_oriel:
            corbel_z = z_base + sill_offset
            corbel_depth = proj * 0.9
            corbel_h = min(0.4, sill_offset * 0.6) if sill_offset > 0.3 else 0.25
            stone_hex = get_trim_hex(params)
            corbel_mat = create_stone_material(
                f"mat_corbel_{stone_hex.lstrip('#')}", stone_hex)
            # Two corbels — left and right thirds of bay width
            for ci, cx in enumerate([x_offset - bay_w / 3, x_offset + bay_w / 3]):
                bpy.ops.mesh.primitive_cube_add(size=1)
                corbel = bpy.context.active_object
                corbel.name = f"bay_corbel_{ci}"
                corbel.scale = (0.15, corbel_depth * 0.5, corbel_h)
                bpy.ops.object.transform_apply(scale=True)
                corbel.location = (cx, corbel_depth * 0.25, corbel_z - corbel_h / 2)
                assign_material(corbel, corbel_mat)
                objects.append(corbel)
            # Decorative angled bracket faces (triangular profile)
            for ci, cx in enumerate([x_offset - bay_w / 3, x_offset + bay_w / 3]):
                bm = bmesh.new()
                v0 = bm.verts.new((cx - 0.06, 0.01, corbel_z))
                v1 = bm.verts.new((cx + 0.06, 0.01, corbel_z))
                v2 = bm.verts.new((cx + 0.06, corbel_depth * 0.4, corbel_z))
                v3 = bm.verts.new((cx - 0.06, corbel_depth * 0.4, corbel_z))
                v4 = bm.verts.new((cx - 0.06, 0.01, corbel_z - corbel_h))
                v5 = bm.verts.new((cx + 0.06, 0.01, corbel_z - corbel_h))
                bm.faces.new([v0, v1, v2, v3])  # top
                bm.faces.new([v4, v5, v1, v0])  # front
                bm.faces.new([v0, v3, v4])       # left triangle
                bm.faces.new([v1, v5, v2])       # right triangle
                bracket_mesh = bpy.data.meshes.new(f"bay_bracket_{ci}")
                bm.to_mesh(bracket_mesh)
                bm.free()
                bracket_obj = bpy.data.objects.new(f"bay_bracket_{ci}", bracket_mesh)
                bpy.context.collection.objects.link(bracket_obj)
                assign_material(bracket_obj, corbel_mat)
                objects.append(bracket_obj)

    return objects


def _create_box_bay(bay, proj, bay_w, bay_h, z_base, sill_offset, x_offset,
                    facade_mat, glass_mat, trim_mat):
    """Create a rectangular (flat-front) box bay window with sill, frames, and side windows."""
    objects = []
    z_bot = z_base + sill_offset
    z_top = z_bot + bay_h

    # Main bay box
    bpy.ops.mesh.primitive_cube_add(size=1)
    bay_obj = bpy.context.active_object
    bay_obj.name = "bay_window"
    bay_obj.scale = (bay_w, proj, bay_h)
    bpy.ops.object.transform_apply(scale=True)
    bay_obj.location = (x_offset, proj / 2, z_bot + bay_h / 2)
    assign_material(bay_obj, facade_mat)
    objects.append(bay_obj)

    # Glass panes on front face
    win_count = bay.get("window_count_in_bay", 3)
    win_w = bay.get("individual_window_width_m", bay_w / win_count * 0.8)
    win_h = bay.get("individual_window_height_m", bay_h * 0.7)

    frame_mat = get_or_create_material("mat_frame_2A2A2A", colour_hex="#2A2A2A", roughness=0.4)

    for i in range(win_count):
        x = x_offset - bay_w / 2 + bay_w / win_count * (i + 0.5)
        # Glass pane
        bpy.ops.mesh.primitive_plane_add(size=1)
        g = bpy.context.active_object
        g.name = f"bay_glass_{i}"
        g.scale = (win_w * 0.85, 1, win_h * 0.85)
        bpy.ops.object.transform_apply(scale=True)
        g.rotation_euler.x = math.pi / 2
        g.location = (x, proj + 0.01, z_bot + bay_h / 2)
        assign_material(g, glass_mat)
        objects.append(g)

        # Window frame surround
        for fx, fw, fh, fn in [
            (x, win_w + 0.04, 0.03, "frame_top"),       # top
            (x, win_w + 0.04, 0.03, "frame_bot"),       # bottom
            (x - win_w / 2 - 0.015, 0.03, win_h, "frame_left"),  # left
            (x + win_w / 2 + 0.015, 0.03, win_h, "frame_right"), # right
        ]:
            bpy.ops.mesh.primitive_cube_add(size=1)
            fr = bpy.context.active_object
            fr.name = f"bay_{fn}_{i}"
            if "top" in fn or "bot" in fn:
                fr.scale = (fw, 0.03, fh)
                z_fr = z_bot + bay_h / 2 + (win_h / 2 + 0.015 if "top" in fn else -win_h / 2 - 0.015)
                fr.location = (fx, proj + 0.02, z_fr)
            else:
                fr.scale = (fw, 0.03, fh)
                fr.location = (fx, proj + 0.02, z_bot + bay_h / 2)
            bpy.ops.object.transform_apply(scale=True)
            assign_material(fr, frame_mat)
            objects.append(fr)

    # Side windows (one on each side of the bay)
    side_win_h = win_h * 0.8
    side_win_w = proj * 0.6
    for side, sx in [("L", x_offset - bay_w / 2), ("R", x_offset + bay_w / 2)]:
        bpy.ops.mesh.primitive_plane_add(size=1)
        sg = bpy.context.active_object
        sg.name = f"bay_side_glass_{side}"
        sg.scale = (1, side_win_w, side_win_h)
        bpy.ops.object.transform_apply(scale=True)
        sg.rotation_euler.z = math.pi / 2
        sg.location = (sx + (0.01 if side == "R" else -0.01), proj / 2, z_bot + bay_h / 2)
        assign_material(sg, glass_mat)
        objects.append(sg)

    # Sill — projecting stone ledge at bottom
    bpy.ops.mesh.primitive_cube_add(size=1)
    bay_sill = bpy.context.active_object
    bay_sill.name = "bay_sill"
    bay_sill.scale = (bay_w + 0.08, proj + 0.1, 0.05)
    bpy.ops.object.transform_apply(scale=True)
    bay_sill.location = (x_offset, proj / 2, z_bot - 0.025)
    assign_material(bay_sill, trim_mat)
    objects.append(bay_sill)

    # Cornice cap
    bpy.ops.mesh.primitive_cube_add(size=1)
    bay_cap = bpy.context.active_object
    bay_cap.name = "bay_cornice"
    bay_cap.scale = (bay_w + 0.1, proj + 0.15, 0.08)
    bpy.ops.object.transform_apply(scale=True)
    bay_cap.location = (x_offset, proj / 2, z_top + 0.04)
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
    # Clamp storefront width to facade width
    sf_w = min(sf_w, facade_width - 0.1)
    sf_h = sf.get("height_m", 2.5)
    bulkhead_h = 0.0
    bulkhead = sf.get("bulkhead", {})
    if isinstance(bulkhead, dict) and bulkhead.get("present", True):
        bulkhead_h = bulkhead.get("height_m", sf.get("bulkhead_height_m", 0.4))

    # Cap storefront top to ground floor height so it doesn't cut into second floor
    floor_heights = params.get("floor_heights_m", [3.5])
    ground_floor_h = float(floor_heights[0]) if floor_heights else 3.5
    if bulkhead_h + sf_h > ground_floor_h - 0.15:
        sf_h = max(1.5, ground_floor_h - bulkhead_h - 0.15)

    # Cut the storefront opening from the wall
    cutter = create_rect_cutter("sf_cut", sf_w, sf_h, depth=0.8)
    cutter.location.x = 0
    cutter.location.y = 0.01
    cutter.location.z = bulkhead_h + sf_h / 2
    boolean_cut(wall_obj, cutter)

    # Glass panel (full storefront)
    glass_mat = create_glass_material("mat_sf_glass", glass_type="storefront")
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

    mullion_mat = get_or_create_material("mat_sf_mullion", colour_hex=mullion_hex,
                                         roughness=0.3, metallic=0.85)

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

    # Transom bar — horizontal divider between storefront glass and upper facade
    transom_z = bulkhead_h + sf_h
    bpy.ops.mesh.primitive_cube_add(size=1)
    tb = bpy.context.active_object
    tb.name = "sf_transom_bar"
    tb.scale = (sf_w + 0.15, 0.08, 0.06)
    bpy.ops.object.transform_apply(scale=True)
    tb.location = (0, 0.03, transom_z)
    assign_material(tb, mullion_mat)
    objects.append(tb)

    # Signage band — above transom bar for commercial buildings
    signage = sf.get("signage", {})
    if isinstance(signage, dict) and signage.get("text"):
        sign_h = signage.get("height_m", 0.5)
        sign_w = signage.get("width_m", sf_w * 0.8)
        sign_hex = signage.get("colour_hex", "#F0EDE8")
        sign_mat = get_or_create_material("mat_signage", colour_hex=sign_hex, roughness=0.4)
        bpy.ops.mesh.primitive_cube_add(size=1)
        sign_obj = bpy.context.active_object
        sign_obj.name = "sf_signage"
        sign_obj.scale = (sign_w, 0.03, sign_h)
        bpy.ops.object.transform_apply(scale=True)
        sign_obj.location = (0, 0.04, transom_z + 0.03 + sign_h / 2)
        assign_material(sign_obj, sign_mat)
        objects.append(sign_obj)

    # Recessed entrance — if entrance data exists, cut a deeper recess
    entrance = sf.get("entrance", {})
    if isinstance(entrance, dict) and entrance.get("width_m"):
        ent_w = entrance.get("width_m", 1.2)
        ent_h = entrance.get("height_m", 2.4)
        ent_pos = str(entrance.get("position", "center")).lower()
        if "left" in ent_pos:
            ent_x = -sf_w / 2 + ent_w / 2 + 0.3
        elif "right" in ent_pos:
            ent_x = sf_w / 2 - ent_w / 2 - 0.3
        else:
            ent_x = 0

        # Recess floor — darker threshold
        threshold_mat = get_or_create_material("mat_threshold", colour_hex="#4A4A4A", roughness=0.7)
        bpy.ops.mesh.primitive_cube_add(size=1)
        recess = bpy.context.active_object
        recess.name = "sf_recess_floor"
        recess.scale = (ent_w + 0.1, 0.3, 0.02)
        bpy.ops.object.transform_apply(scale=True)
        recess.location = (ent_x, -0.15, 0.01)
        assign_material(recess, threshold_mat)
        objects.append(recess)

    # Security grille — rolling shutter track
    grille = sf.get("security_grille", {})
    if isinstance(grille, dict) and grille.get("present"):
        grille_mat = get_or_create_material("mat_grille_track", colour_hex="#5A5A5A", roughness=0.3)
        _bsdf = grille_mat.node_tree.nodes.get("Principled BSDF")
        if _bsdf and "Metallic" in _bsdf.inputs:
            _bsdf.inputs["Metallic"].default_value = 0.85
        # Track channels on each side
        for gx in [-sf_w / 2 - 0.02, sf_w / 2 + 0.02]:
            bpy.ops.mesh.primitive_cube_add(size=1)
            track = bpy.context.active_object
            track.name = f"sf_grille_track"
            track.scale = (0.03, 0.05, sf_h)
            bpy.ops.object.transform_apply(scale=True)
            track.location = (gx, 0.03, bulkhead_h + sf_h / 2)
            assign_material(track, grille_mat)
            objects.append(track)
        # Housing box at top
        bpy.ops.mesh.primitive_cube_add(size=1)
        housing = bpy.context.active_object
        housing.name = "sf_grille_housing"
        housing.scale = (sf_w + 0.1, 0.12, 0.1)
        bpy.ops.object.transform_apply(scale=True)
        housing.location = (0, 0.06, transom_z + 0.05)
        assign_material(housing, grille_mat)
        objects.append(housing)

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

        aw_mat = create_canvas_material(f"mat_awning_{aw_hex.lstrip('#')}", aw_hex)
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
    sc_hex = sc.get("colour_hex", get_accent_hex(params))
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

    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)
    hw = width / 2

    seen = set()
    for i, z in enumerate(sorted(z_positions)):
        z_key = round(z, 4)
        if z_key in seen:
            continue
        seen.add(z_key)

        # Front band
        bpy.ops.mesh.primitive_cube_add(size=1)
        band = bpy.context.active_object
        band.name = f"string_course_{i}_{bldg_id}"
        band.scale = (width + sc_proj * 2, sc_proj, sc_h)
        bpy.ops.object.transform_apply(scale=True)
        band.location = (0, sc_proj / 2, z)
        assign_material(band, sc_mat)
        objects.append(band)

        # Side return bands (wrap around corners, skip party walls)
        return_depth = min(0.3, depth * 0.05)  # short return, not full depth
        if not party_left:
            bpy.ops.mesh.primitive_cube_add(size=1)
            lr = bpy.context.active_object
            lr.name = f"string_course_{i}_left_{bldg_id}"
            lr.scale = (sc_proj, return_depth, sc_h)
            bpy.ops.object.transform_apply(scale=True)
            lr.location = (-hw - sc_proj / 2, -return_depth / 2, z)
            assign_material(lr, sc_mat)
            objects.append(lr)

        if not party_right:
            bpy.ops.mesh.primitive_cube_add(size=1)
            rr = bpy.context.active_object
            rr.name = f"string_course_{i}_right_{bldg_id}"
            rr.scale = (sc_proj, return_depth, sc_h)
            bpy.ops.object.transform_apply(scale=True)
            rr.location = (hw + sc_proj / 2, -return_depth / 2, z)
            assign_material(rr, sc_mat)
            objects.append(rr)

    return objects


def _create_corbel_band(name_prefix, cx, y_face, z_base, width, course_count=3,
                        brick_w=0.22, brick_h=0.075, base_proj=0.035,
                        step_proj=0.02, colour_hex="#B85A3A"):
    """Create a simple stepped corbel table along a front-facing wall."""
    if width < 0.1:
        return []
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
    """Create corbel tables on front and exposed sides."""
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
    objects = _create_corbel_band(f"corbel_front_{bldg_id}", 0, 0.02, z_base, width,
                                  course_count=course_count, colour_hex=facade_hex)

    # Side corbelling on exposed (non-party-wall) sides
    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)
    hw = width / 2

    if not party_left:
        side_objs = _create_corbel_band(f"corbel_left_{bldg_id}", -hw - 0.02, -depth * 0.15,
                                         z_base, depth * 0.3,
                                         course_count=course_count, colour_hex=facade_hex)
        objects.extend(side_objs)

    if not party_right:
        side_objs = _create_corbel_band(f"corbel_right_{bldg_id}", hw + 0.02, -depth * 0.15,
                                         z_base, depth * 0.3,
                                         course_count=course_count, colour_hex=facade_hex)
        objects.extend(side_objs)

    return objects


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
    sc_mat = get_or_create_material(f"mat_tower_sc_{bldg_id}", colour_hex=get_accent_hex(params), roughness=0.6)
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
    q_hex = quoins.get("colour_hex", get_accent_hex(params))
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

    # Create alternating block pattern (long/short stones stacked)
    block_h_long = 0.25
    block_h_short = 0.18
    block_w_long = q_w
    block_w_short = q_w * 0.65

    for x, name in positions:
        z = 0
        block_idx = 0
        while z < wall_h - 0.1:
            is_long = (block_idx % 2 == 0)
            bh = block_h_long if is_long else block_h_short
            bw = block_w_long if is_long else block_w_short

            bpy.ops.mesh.primitive_cube_add(size=1)
            q = bpy.context.active_object
            q.name = f"{name}_{block_idx}"
            q.scale = (bw, q_proj, bh - 0.005)  # small gap between blocks
            bpy.ops.object.transform_apply(scale=True)
            q.location = (x, q_proj / 2, z + bh / 2)
            assign_material(q, q_mat)
            objects.append(q)

            z += bh
            block_idx += 1

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
    ridge_height = (width / 2) * _safe_tan(pitch)

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

    bb_mat = create_wood_material(f"mat_bargeboard_{bb_hex.lstrip('#')}", bb_hex)

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

    # Cornice colour — usually matches trim or accent stone
    cornice_hex = cornice.get("colour_hex", "")
    if not isinstance(cornice_hex, str) or not cornice_hex.startswith("#"):
        colour_palette = params.get("colour_palette", {})
        trim = colour_palette.get("trim", {})
        cornice_hex = get_accent_hex(params)
        if isinstance(trim, dict):
            cornice_hex = trim.get("hex_approx", cornice_hex)
        else:
            cornice_hex = get_trim_hex(params)

    mat = create_stone_material(f"mat_cornice_{cornice_hex.lstrip('#')}", cornice_hex)

    objects = []

    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)

    # Front cornice — main band
    bpy.ops.mesh.primitive_cube_add(size=1)
    c = bpy.context.active_object
    c.name = f"cornice_front_{bldg_id}"
    c.scale = (width + proj * 2, proj, height)
    bpy.ops.object.transform_apply(scale=True)
    c.location = (0, proj / 2, wall_h + height / 2)
    assign_material(c, mat)
    objects.append(c)

    # Soffit — sheltered underside, smoother than exposed cornice top
    soffit_mat = get_or_create_material("mat_soffit", colour_hex=cornice_hex, roughness=0.45)
    bpy.ops.mesh.primitive_cube_add(size=1)
    soffit = bpy.context.active_object
    soffit.name = f"cornice_soffit_{bldg_id}"
    soffit.scale = (width + proj * 2, proj, 0.015)
    bpy.ops.object.transform_apply(scale=True)
    soffit.location = (0, proj / 2, wall_h + 0.008)
    assign_material(soffit, soffit_mat)
    objects.append(soffit)

    # Dentil course — small repeating blocks below main band (Pre-1889 and ornate styles)
    cornice_type = str(cornice.get("type", "simple")).lower()
    era = str(params.get("hcd_data", {}).get("construction_date", "")).lower() if isinstance(params.get("hcd_data"), dict) else ""
    if cornice_type in ("dentil", "decorative", "bracketed") or "pre-1889" in era:
        dentil_w = 0.04
        dentil_h = 0.04
        dentil_spacing = 0.08
        dentil_z = wall_h + 0.01
        num_dentils = int(width / dentil_spacing)
        for di in range(num_dentils):
            dx = -width / 2 + dentil_spacing / 2 + di * dentil_spacing
            bpy.ops.mesh.primitive_cube_add(size=1)
            d = bpy.context.active_object
            d.name = f"dentil_{bldg_id}_{di}"
            d.scale = (dentil_w, proj * 0.6, dentil_h)
            bpy.ops.object.transform_apply(scale=True)
            d.location = (dx, proj * 0.3, dentil_z)
            assign_material(d, mat)
            objects.append(d)

    # Side cornices (skip party wall sides)
    if not party_left:
        bpy.ops.mesh.primitive_cube_add(size=1)
        sc = bpy.context.active_object
        sc.name = f"cornice_left_{bldg_id}"
        sc.scale = (proj, depth, height)
        bpy.ops.object.transform_apply(scale=True)
        sc.location = (-width / 2 - proj / 2, -depth / 2, wall_h + height / 2)
        assign_material(sc, mat)
        objects.append(sc)

    if not party_right:
        bpy.ops.mesh.primitive_cube_add(size=1)
        sc = bpy.context.active_object
        sc.name = f"cornice_right_{bldg_id}"
        sc.scale = (proj, depth, height)
        bpy.ops.object.transform_apply(scale=True)
        sc.location = (width / 2 + proj / 2, -depth / 2, wall_h + height / 2)
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
    rise = min(base_w, base_d) * 0.35 * _safe_tan(pitch)
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

    # Lintel material — usually stone/cream, uses colour_palette.accent as fallback
    lintel_hex = get_accent_hex(params)
    if isinstance(dec, dict):
        lint = dec.get("lintels", dec.get("stone_lintels", {}))
        if isinstance(lint, dict):
            lintel_hex = lint.get("colour_hex", lint.get("colour", lintel_hex))
            if not lintel_hex.startswith("#"):
                lintel_hex = colour_name_to_hex(str(lintel_hex))

    mat = create_stone_material(f"mat_lintel_{lintel_hex.lstrip('#')}", lintel_hex)
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

            # Check arch type for lintel shape
            arch_type = str(win_spec.get("arch_type", win_spec.get("head_shape", "flat"))).lower()

            for i in range(count):
                x = start_x + i * spacing if count > 1 else 0

                # Lintel (above window)
                bpy.ops.mesh.primitive_cube_add(size=1)
                lt = bpy.context.active_object
                lt.name = f"lintel_{floor_idx}_{i}_{bldg_id}"
                lt.scale = (w + 0.08, 0.06, 0.07)
                bpy.ops.object.transform_apply(scale=True)
                lt.location = (x, 0.03, sill_h + h + 0.035)
                assign_material(lt, mat)
                objects.append(lt)

                # Keystone for segmental/arched lintels
                if "segmental" in arch_type or "arch" in arch_type or "round" in arch_type:
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    ks = bpy.context.active_object
                    ks.name = f"keystone_{floor_idx}_{i}_{bldg_id}"
                    ks.scale = (0.08, 0.07, 0.12)
                    bpy.ops.object.transform_apply(scale=True)
                    ks.location = (x, 0.035, sill_h + h + 0.06)
                    assign_material(ks, mat)
                    objects.append(ks)

                # Drip mould — small shelf above lintel to shed water
                bpy.ops.mesh.primitive_cube_add(size=1)
                dm = bpy.context.active_object
                dm.name = f"drip_mould_{floor_idx}_{i}_{bldg_id}"
                dm.scale = (w + 0.12, 0.03, 0.015)
                bpy.ops.object.transform_apply(scale=True)
                dm.location = (x, 0.05, sill_h + h + 0.075)
                assign_material(dm, mat)
                objects.append(dm)

                # Sill (below window) — slightly wider, more projecting, with nose
                bpy.ops.mesh.primitive_cube_add(size=1)
                sl = bpy.context.active_object
                sl.name = f"sill_{floor_idx}_{i}_{bldg_id}"
                sl.scale = (w + 0.1, 0.08, 0.04)
                bpy.ops.object.transform_apply(scale=True)
                sl.location = (x, 0.04, sill_h - 0.02)
                assign_material(sl, mat)
                objects.append(sl)

                # Sill nose — projecting front edge
                bpy.ops.mesh.primitive_cube_add(size=1)
                sn = bpy.context.active_object
                sn.name = f"sill_nose_{floor_idx}_{i}_{bldg_id}"
                sn.scale = (w + 0.12, 0.02, 0.02)
                bpy.ops.object.transform_apply(scale=True)
                sn.location = (x, 0.09, sill_h - 0.03)
                assign_material(sn, mat)
                objects.append(sn)

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
    ridge_height = (width / 2) * _safe_tan(pitch)

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

            count = w.get("count", 1)
            win_w = w.get("width_m", 0.8)
            win_h = w.get("height_m", 1.3)
            sill_h = w.get("sill_height_m", 0.8)
            arch_type = str(w.get("arch_type", w.get("head_shape", "flat"))).lower()

            spacing = facade_width / (count + 1)
            for ci in range(count):
                cx = -facade_width / 2 + spacing * (ci + 1)
                win_top_z = z_base + sill_h + win_h

                if "segmental" in arch_type or "round" in arch_type or "semi" in arch_type:
                    # Full arched voussoir ring
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
                        stone.name = f"voussoir_{bldg_id}_{floor_idx}_{ci}_{si}"
                        stone.scale = (stone_w, stone_d, 0.06)
                        stone.location = (sx, 0.16, sz)
                        stone.rotation_euler.y = -(angle - math.pi / 2)
                        assign_material(stone, mat)
                        objects.append(stone)
                else:
                    # Flat brick voussoirs — row of angled bricks above window
                    num_bricks = max(5, int(win_w / 0.08))
                    brick_w = win_w / num_bricks
                    brick_h = 0.10
                    for bi in range(num_bricks):
                        bx = cx - win_w / 2 + brick_w / 2 + bi * brick_w
                        # Fan angle: bricks angle from center outward
                        fan_angle = (bi - num_bricks / 2) / num_bricks * 0.3

                        bpy.ops.mesh.primitive_cube_add(size=1)
                        brick = bpy.context.active_object
                        brick.name = f"voussoir_flat_{bldg_id}_{floor_idx}_{ci}_{bi}"
                        brick.scale = (brick_w - 0.003, 0.06, brick_h)
                        bpy.ops.object.transform_apply(scale=True)
                        brick.location = (bx, 0.03, win_top_z + brick_h / 2 + 0.01)
                        brick.rotation_euler.y = fan_angle
                        assign_material(brick, mat)
                        objects.append(brick)

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
    ridge_h = half_w * _safe_tan(pitch)

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
            dz_base = wall_h + (width / 2) * _safe_tan(pitch) * 0.3

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
        elif "shed" in d_type:
            # Shed dormer — single slope from front (high) to back (low)
            shed_rise = d_depth * _safe_tan(min(d_pitch, 25))
            bm = bmesh.new()
            hw = d_w / 2 + 0.05
            y_f = dy + d_depth / 2 + 0.05
            y_b = dy - d_depth / 2 - 0.05

            # Front edge is higher, back edge meets main roof
            v0 = bm.verts.new((-hw + dx, y_b, top_z))
            v1 = bm.verts.new((hw + dx, y_b, top_z))
            v2 = bm.verts.new((hw + dx, y_f, top_z + shed_rise))
            v3 = bm.verts.new((-hw + dx, y_f, top_z + shed_rise))

            bm.faces.new([v0, v1, v2, v3])  # single slope

            d_mesh = bpy.data.meshes.new(f"dormer_shed_roof_{di}")
            bm.to_mesh(d_mesh)
            bm.free()

            d_roof_obj = bpy.data.objects.new(f"dormer_shed_roof_{bldg_id}_{di}", d_mesh)
            bpy.context.collection.objects.link(d_roof_obj)

            mod = d_roof_obj.modifiers.new("Solidify", 'SOLIDIFY')
            mod.thickness = 0.05
            mod.offset = -1
            bpy.context.view_layer.objects.active = d_roof_obj
            bpy.ops.object.modifier_apply(modifier=mod.name)

            d_roof_mat = create_roof_material(f"mat_droof_{d_roof_hex.lstrip('#')}", d_roof_hex)
            assign_material(d_roof_obj, d_roof_mat)
            objects.append(d_roof_obj)
        elif "hip" in d_type:
            # Hipped dormer — four-sided roof with ridgeline shorter than base
            d_ridge = (d_w / 2) * _safe_tan(d_pitch) * 0.7
            bm = bmesh.new()
            hw = d_w / 2 + 0.05
            y_f = dy + d_depth / 2 + 0.05
            y_b = dy - d_depth / 2 - 0.05
            ridge_inset = d_depth * 0.3  # hip ridgeline shorter than base

            v0 = bm.verts.new((-hw + dx, y_b, top_z))
            v1 = bm.verts.new((hw + dx, y_b, top_z))
            v2 = bm.verts.new((hw + dx, y_f, top_z))
            v3 = bm.verts.new((-hw + dx, y_f, top_z))
            # Ridge endpoints inset from front/back
            v4 = bm.verts.new((dx, y_b + ridge_inset, top_z + d_ridge))
            v5 = bm.verts.new((dx, y_f - ridge_inset, top_z + d_ridge))

            bm.faces.new([v0, v3, v5, v4])  # left slope
            bm.faces.new([v1, v4, v5, v2])  # right slope
            bm.faces.new([v2, v5, v3])      # front hip triangle
            bm.faces.new([v0, v4, v1])      # back hip triangle

            d_mesh = bpy.data.meshes.new(f"dormer_hip_roof_{di}")
            bm.to_mesh(d_mesh)
            bm.free()

            d_roof_obj = bpy.data.objects.new(f"dormer_hip_roof_{bldg_id}_{di}", d_mesh)
            bpy.context.collection.objects.link(d_roof_obj)

            mod = d_roof_obj.modifiers.new("Solidify", 'SOLIDIFY')
            mod.thickness = 0.05
            mod.offset = -1
            bpy.context.view_layer.objects.active = d_roof_obj
            bpy.ops.object.modifier_apply(modifier=mod.name)

            d_roof_mat = create_roof_material(f"mat_droof_{d_roof_hex.lstrip('#')}", d_roof_hex)
            assign_material(d_roof_obj, d_roof_mat)
            objects.append(d_roof_obj)
        else:
            # Standard gable roof (default)
            d_ridge = (d_w / 2) * _safe_tan(d_pitch)
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

    mat = create_wood_material(f"mat_fascia_{fascia_hex.lstrip('#')}", fascia_hex)

    pitch = params.get("roof_pitch_deg", 35)
    ridge_h = (width / 2) * _safe_tan(pitch)

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
    post_mat = create_wood_material(f"mat_turned_post_{post_colour.lstrip('#')}",
                                    post_colour)

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

    aw_mat = create_canvas_material(f"mat_awning_{aw_hex.lstrip('#')}", aw_hex)

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
    """Create visible foundation/water table at ground level with stone coursing."""
    foundation_h = params.get("foundation_height_m", 0.3)
    if not isinstance(foundation_h, (int, float)) or foundation_h <= 0:
        foundation_h = 0.3
    foundation_proj = 0.04  # projection from wall face

    # Foundation colour — typically grey limestone or rubble stone
    dfa = params.get("deep_facade_analysis", {})
    depth_notes = dfa.get("depth_notes", {}) if isinstance(dfa, dict) else {}
    if isinstance(depth_notes, dict) and depth_notes.get("foundation_height_m_est"):
        est_h = depth_notes["foundation_height_m_est"]
        if isinstance(est_h, (int, float)) and est_h > 0:
            foundation_h = est_h

    # Foundation colour based on construction era
    construction_date = params.get("hcd_data", {}).get("construction_date", "")
    if isinstance(construction_date, str):
        construction_date = construction_date.strip()

    # Select foundation colour by era
    if any(x in construction_date for x in ["Pre-1889", "pre-1889", "1889-1903"]):
        foundation_colour = "#7A7570"  # rubble stone
    elif any(x in construction_date for x in ["1904-1913"]):
        foundation_colour = "#7A7A78"  # dressed stone (current default)
    elif any(x in construction_date for x in ["1914-1930"]):
        foundation_colour = "#9A9690"  # concrete-like
    else:
        foundation_colour = "#7A7A78"  # default fallback

    stone_mat = create_stone_material(f"mat_foundation_{bldg_id}", foundation_colour)

    objects = []
    hw = width / 2
    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)

    # Front foundation wall
    bpy.ops.mesh.primitive_cube_add(size=1)
    ff = bpy.context.active_object
    ff.name = f"foundation_front_{bldg_id}"
    ff.scale = (width + foundation_proj * 2, foundation_proj * 2, foundation_h)
    bpy.ops.object.transform_apply(scale=True)
    ff.location = (0, foundation_proj, foundation_h / 2)
    assign_material(ff, stone_mat)
    objects.append(ff)

    # Back foundation wall
    bpy.ops.mesh.primitive_cube_add(size=1)
    fb = bpy.context.active_object
    fb.name = f"foundation_back_{bldg_id}"
    fb.scale = (width + foundation_proj * 2, foundation_proj * 2, foundation_h)
    bpy.ops.object.transform_apply(scale=True)
    fb.location = (0, -depth - foundation_proj, foundation_h / 2)
    assign_material(fb, stone_mat)
    objects.append(fb)

    # Left side (skip if party wall — neighbour's foundation is flush)
    if not party_left:
        bpy.ops.mesh.primitive_cube_add(size=1)
        fl = bpy.context.active_object
        fl.name = f"foundation_left_{bldg_id}"
        fl.scale = (foundation_proj * 2, depth + foundation_proj * 2, foundation_h)
        bpy.ops.object.transform_apply(scale=True)
        fl.location = (-hw - foundation_proj, -depth / 2, foundation_h / 2)
        assign_material(fl, stone_mat)
        objects.append(fl)

    # Right side (skip if party wall)
    if not party_right:
        bpy.ops.mesh.primitive_cube_add(size=1)
        fr = bpy.context.active_object
        fr.name = f"foundation_right_{bldg_id}"
        fr.scale = (foundation_proj * 2, depth + foundation_proj * 2, foundation_h)
        bpy.ops.object.transform_apply(scale=True)
        fr.location = (hw + foundation_proj, -depth / 2, foundation_h / 2)
        assign_material(fr, stone_mat)
        objects.append(fr)

    # Stone coursing lines on front face — horizontal grooves every ~0.15m
    groove_mat = get_or_create_material("mat_foundation_groove", colour_hex="#606060", roughness=0.95)
    course_h = 0.15
    z = course_h
    while z < foundation_h - 0.05:
        bpy.ops.mesh.primitive_cube_add(size=1)
        groove = bpy.context.active_object
        groove.name = f"foundation_course_{bldg_id}_{int(z*100)}"
        groove.scale = (width + foundation_proj * 2.5, 0.005, 0.01)
        bpy.ops.object.transform_apply(scale=True)
        groove.location = (0, foundation_proj + 0.005, z)
        assign_material(groove, groove_mat)
        objects.append(groove)
        z += course_h

    return objects


def create_gutters(params, wall_h, width, depth, bldg_id=""):
    """Create gutters along eaves, downspouts at corners, and elbow connectors."""
    roof_type = str(params.get("roof_type", "gable")).lower()
    if "flat" in roof_type:
        return []  # flat roofs have internal drainage

    # Copper gutters on buildings with copper roofing use the patina shader
    rm = str(params.get("roof_material", "")).lower()
    if any(kw in rm for kw in ("copper", "verdigris", "patina")):
        gutter_mat = create_copper_patina_material("mat_gutter_copper", "#B87333")
    else:
        gutter_mat = get_or_create_material("mat_gutter", colour_hex="#4A4A4A", roughness=0.35)
        # Metal gutters/downspouts: set metallic for PBR realism
        bsdf = gutter_mat.node_tree.nodes.get("Principled BSDF")
        if bsdf and "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.85

    objects = []
    gutter_r = 0.04
    downspout_r = 0.025

    rd = params.get("roof_detail", {})
    eave_mm = 300
    if isinstance(rd, dict):
        eave_mm = rd.get("eave_overhang_mm", 300)
    else:
        eave_mm = params.get("eave_overhang_mm", 300)
    overhang = eave_mm / 1000.0

    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)
    hw = width / 2

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

    # Downspouts at front corners (skip party wall sides)
    downspout_positions = []
    if not party_left:
        downspout_positions.append(("L", -hw - 0.02))
    if not party_right:
        downspout_positions.append(("R", hw + 0.02))

    for side, sx in downspout_positions:
        # Vertical downspout pipe
        bpy.ops.mesh.primitive_cylinder_add(radius=downspout_r, depth=wall_h - 0.3, vertices=6)
        ds = bpy.context.active_object
        ds.name = f"downspout_{side}_{bldg_id}"
        ds.location = (sx, overhang + 0.02, (wall_h - 0.3) / 2)
        assign_material(ds, gutter_mat)
        objects.append(ds)

        # Upper elbow — connects gutter to downspout
        bpy.ops.mesh.primitive_uv_sphere_add(radius=downspout_r * 1.3, segments=6, ring_count=4)
        elbow_top = bpy.context.active_object
        elbow_top.name = f"gutter_elbow_top_{side}_{bldg_id}"
        elbow_top.location = (sx, overhang + 0.02, wall_h - 0.05)
        assign_material(elbow_top, gutter_mat)
        objects.append(elbow_top)

        # Lower elbow — downspout to ground discharge
        bpy.ops.mesh.primitive_uv_sphere_add(radius=downspout_r * 1.3, segments=6, ring_count=4)
        elbow_bot = bpy.context.active_object
        elbow_bot.name = f"gutter_elbow_bot_{side}_{bldg_id}"
        elbow_bot.location = (sx, overhang + 0.02, 0.15)
        assign_material(elbow_bot, gutter_mat)
        objects.append(elbow_bot)

        # Ground discharge — short horizontal pipe
        bpy.ops.mesh.primitive_cylinder_add(radius=downspout_r, depth=0.2, vertices=6)
        discharge = bpy.context.active_object
        discharge.name = f"gutter_discharge_{side}_{bldg_id}"
        discharge.rotation_euler.x = math.pi / 2
        discharge.location = (sx, overhang + 0.12, 0.08)
        assign_material(discharge, gutter_mat)
        objects.append(discharge)

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
    lattice_mat = create_wood_material(f"mat_lattice_{trim_hex.lstrip('#')}", trim_hex)

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
    frame_mat = create_wood_material(f"mat_lattice_frame_{trim_hex.lstrip('#')}", trim_hex)
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

    rail_mat = get_or_create_material("mat_handrail", colour_hex="#2A2A2A", roughness=0.25)
    # Wrought iron handrails: set metallic
    bsdf = rail_mat.node_tree.nodes.get("Principled BSDF")
    if bsdf and "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.90
    objects = []

    total_run = step_count * run
    rail_len = math.sqrt(total_run ** 2 + floor_h ** 2)
    rail_angle = math.atan2(floor_h, total_run)

    for side, sx in [("L", step_x - step_w / 2 - 0.04), ("R", step_x + step_w / 2 + 0.04)]:
        # Sloped top rail
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=rail_len, vertices=8)
        rail = bpy.context.active_object
        rail.name = f"handrail_{side}_{bldg_id}"
        rail.rotation_euler.x = math.pi / 2 - rail_angle
        rail.location = (sx, porch_d + total_run / 2, floor_h / 2 + 0.4)
        assign_material(rail, rail_mat)
        objects.append(rail)

        # Bottom newel post — thicker, decorative
        bot_post_h = 0.95
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=bot_post_h, vertices=8)
        bp = bpy.context.active_object
        bp.name = f"rail_post_bot_{side}_{bldg_id}"
        bp.location = (sx, porch_d + total_run, bot_post_h / 2)
        assign_material(bp, rail_mat)
        objects.append(bp)

        # Newel cap ball
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.03, segments=8, ring_count=6)
        bc = bpy.context.active_object
        bc.name = f"rail_newel_bot_{side}_{bldg_id}"
        bc.location = (sx, porch_d + total_run, bot_post_h + 0.01)
        assign_material(bc, rail_mat)
        objects.append(bc)

        # Top newel post
        top_post_h = 0.95
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=top_post_h, vertices=8)
        tp = bpy.context.active_object
        tp.name = f"rail_post_top_{side}_{bldg_id}"
        tp.location = (sx, porch_d, floor_h + top_post_h / 2)
        assign_material(tp, rail_mat)
        objects.append(tp)

        # Top newel cap
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.03, segments=8, ring_count=6)
        tc = bpy.context.active_object
        tc.name = f"rail_newel_top_{side}_{bldg_id}"
        tc.location = (sx, porch_d, floor_h + top_post_h + 0.01)
        assign_material(tc, rail_mat)
        objects.append(tc)

        # Intermediate balusters along stair slope
        baluster_spacing = 0.15
        num_balusters = max(1, int(total_run / baluster_spacing))
        for bi in range(1, num_balusters):
            frac = bi / num_balusters
            by = porch_d + total_run * (1 - frac)
            bz_base = floor_h * frac
            bz_top = bz_base + 0.85
            bal_h = bz_top - bz_base
            bpy.ops.mesh.primitive_cylinder_add(radius=0.008, depth=bal_h, vertices=6)
            bal = bpy.context.active_object
            bal.name = f"rail_baluster_{side}_{bi}_{bldg_id}"
            bal.location = (sx, by, bz_base + bal_h / 2)
            assign_material(bal, rail_mat)
            objects.append(bal)

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
# Additional architectural detail generators
# ---------------------------------------------------------------------------


def create_window_shutters(params, wall_h, facade_width, bldg_id=""):
    """Create decorative shutters flanking windows (common Pre-1889 houses)."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []
    shutters = dec.get("shutters", {})
    if not isinstance(shutters, dict) or not shutters.get("present", False):
        return []

    shutter_hex = shutters.get("colour_hex", get_trim_hex(params))
    shutter_mat = get_or_create_material(f"mat_shutter_{shutter_hex.lstrip('#')}",
                                          colour_hex=shutter_hex, roughness=0.6)
    objects = []
    floor_heights = params.get("floor_heights_m", [3.0])
    windows_detail = get_effective_windows_detail(params)

    for fd in windows_detail:
        if not isinstance(fd, dict):
            continue
        floor_idx = int(_normalize_floor_index(fd.get("floor", 1), floor_heights))
        z_base = sum(floor_heights[:max(0, floor_idx - 1)])
        for w in fd.get("windows", []):
            if not isinstance(w, dict):
                continue
            count = w.get("count", 1)
            win_w = w.get("width_m", 0.85)
            win_h = w.get("height_m", 1.3)
            fi = max(0, min(floor_idx - 1, len(floor_heights) - 1))
            floor_h = floor_heights[fi] if floor_heights else 3.0
            sill_h = z_base + max(0.8, (floor_h - win_h) / 2)
            spacing = facade_width / (count + 1)
            for ci in range(count):
                cx = -facade_width / 2 + spacing * (ci + 1)
                # Left shutter
                for side, sx in [("L", cx - win_w / 2 - 0.06), ("R", cx + win_w / 2 + 0.06)]:
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    sh = bpy.context.active_object
                    sh.name = f"shutter_{side}_{floor_idx}_{ci}_{bldg_id}"
                    sh.scale = (0.05, 0.02, win_h * 0.95)
                    bpy.ops.object.transform_apply(scale=True)
                    sh.location = (sx, 0.01, sill_h + win_h / 2)
                    assign_material(sh, shutter_mat)
                    objects.append(sh)
                    # Louver lines on shutter face
                    louver_count = int(win_h / 0.08)
                    for li in range(louver_count):
                        lz = sill_h + 0.04 + li * 0.08
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        lv = bpy.context.active_object
                        lv.name = f"louver_{side}_{floor_idx}_{ci}_{li}"
                        lv.scale = (0.045, 0.005, 0.003)
                        bpy.ops.object.transform_apply(scale=True)
                        lv.location = (sx, 0.025, lz)
                        assign_material(lv, shutter_mat)
                        objects.append(lv)
    return objects


def create_address_plaque(params, facade_width, bldg_id=""):
    """Create a small address number plaque near the front door."""
    building_name = params.get("building_name", "")
    if not building_name:
        return []

    # Extract house number
    import re as _re
    m = _re.match(r"(\d+[A-Za-z]?)", building_name)
    if not m:
        return []

    objects = []
    plaque_mat = get_or_create_material("mat_plaque", colour_hex="#2A2A2A", roughness=0.3)

    # Position near the door — right side, at eye height
    plaque_x = min(facade_width / 4, 1.0)
    plaque_z = 2.0  # eye height

    # Plaque backing
    bpy.ops.mesh.primitive_cube_add(size=1)
    plaque = bpy.context.active_object
    plaque.name = f"address_plaque_{bldg_id}"
    plaque.scale = (0.2, 0.015, 0.12)
    bpy.ops.object.transform_apply(scale=True)
    plaque.location = (plaque_x, 0.015, plaque_z)
    assign_material(plaque, plaque_mat)
    objects.append(plaque)

    return objects


def create_utility_box(params, facade_width, bldg_id=""):
    """Create a utility meter box on the facade — ubiquitous in Kensington."""
    objects = []
    # Only add on residential buildings
    ctx = params.get("context", {})
    if ctx.get("building_type") == "institutional":
        return []

    box_mat = get_or_create_material("mat_utility_box", colour_hex="#8A8A8A", roughness=0.4)
    _bsdf = box_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.70

    # Position: low on facade, to one side
    box_x = facade_width / 3
    box_z = 1.2

    bpy.ops.mesh.primitive_cube_add(size=1)
    box = bpy.context.active_object
    box.name = f"utility_meter_{bldg_id}"
    box.scale = (0.3, 0.12, 0.4)
    bpy.ops.object.transform_apply(scale=True)
    box.location = (box_x, 0.06, box_z)
    assign_material(box, box_mat)
    objects.append(box)

    # Conduit pipe running up from box
    pipe_mat = get_or_create_material("mat_conduit", colour_hex="#6A6A6A", roughness=0.3)
    _bsdf = pipe_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.80
    bpy.ops.mesh.primitive_cylinder_add(radius=0.015, depth=1.5, vertices=6)
    pipe = bpy.context.active_object
    pipe.name = f"utility_conduit_{bldg_id}"
    pipe.location = (box_x + 0.1, 0.03, box_z + 0.2 + 0.75)
    assign_material(pipe, pipe_mat)
    objects.append(pipe)

    return objects


def create_window_frames(params, wall_h, facade_width, bldg_id=""):
    """Create visible window frame surrounds (trim boards) around each window opening."""
    windows_detail = get_effective_windows_detail(params)
    floor_heights = params.get("floor_heights_m", [3.0])
    if not windows_detail:
        return []

    trim_hex = get_trim_hex(params)
    frame_mat = get_or_create_material(f"mat_window_frame_{trim_hex.lstrip('#')}",
                                        colour_hex=trim_hex, roughness=0.5)
    objects = []
    frame_w = 0.05  # frame width
    frame_d = 0.03  # frame depth/projection

    for fd in windows_detail:
        if not isinstance(fd, dict):
            continue
        floor_idx = int(_normalize_floor_index(fd.get("floor", 1), floor_heights))
        z_base = sum(floor_heights[:max(0, floor_idx - 1)])

        for w in fd.get("windows", []):
            if not isinstance(w, dict):
                continue
            count = w.get("count", 1)
            if count == 0:
                continue
            win_w = w.get("width_m", 0.85)
            win_h = w.get("height_m", 1.3)
            fi = max(0, min(floor_idx - 1, len(floor_heights) - 1))
            floor_h = floor_heights[fi] if floor_heights else 3.0
            sill_h = z_base + max(0.8, (floor_h - win_h) / 2)

            spacing = facade_width / (count + 1)
            for ci in range(count):
                cx = -facade_width / 2 + spacing * (ci + 1)
                z_mid = sill_h + win_h / 2

                # Top frame (header)
                bpy.ops.mesh.primitive_cube_add(size=1)
                top = bpy.context.active_object
                top.name = f"frame_top_{floor_idx}_{ci}_{bldg_id}"
                top.scale = (win_w + frame_w * 2, frame_d, frame_w)
                bpy.ops.object.transform_apply(scale=True)
                top.location = (cx, frame_d / 2, sill_h + win_h + frame_w / 2)
                assign_material(top, frame_mat)
                objects.append(top)

                # Bottom frame
                bpy.ops.mesh.primitive_cube_add(size=1)
                bot = bpy.context.active_object
                bot.name = f"frame_bot_{floor_idx}_{ci}_{bldg_id}"
                bot.scale = (win_w + frame_w * 2, frame_d, frame_w)
                bpy.ops.object.transform_apply(scale=True)
                bot.location = (cx, frame_d / 2, sill_h - frame_w / 2)
                assign_material(bot, frame_mat)
                objects.append(bot)

                # Left side frame
                bpy.ops.mesh.primitive_cube_add(size=1)
                left = bpy.context.active_object
                left.name = f"frame_left_{floor_idx}_{ci}_{bldg_id}"
                left.scale = (frame_w, frame_d, win_h)
                bpy.ops.object.transform_apply(scale=True)
                left.location = (cx - win_w / 2 - frame_w / 2, frame_d / 2, z_mid)
                assign_material(left, frame_mat)
                objects.append(left)

                # Right side frame
                bpy.ops.mesh.primitive_cube_add(size=1)
                right = bpy.context.active_object
                right.name = f"frame_right_{floor_idx}_{ci}_{bldg_id}"
                right.scale = (frame_w, frame_d, win_h)
                bpy.ops.object.transform_apply(scale=True)
                right.location = (cx + win_w / 2 + frame_w / 2, frame_d / 2, z_mid)
                assign_material(right, frame_mat)
                objects.append(right)

                # Meeting rail — horizontal bar at mid-height (double-hung windows)
                win_type = str(w.get("type", "double_hung")).lower()
                if "double" in win_type or "hung" in win_type:
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    rail = bpy.context.active_object
                    rail.name = f"frame_meeting_{floor_idx}_{ci}_{bldg_id}"
                    rail.scale = (win_w, frame_d, 0.025)
                    bpy.ops.object.transform_apply(scale=True)
                    rail.location = (cx, frame_d / 2 + 0.005, z_mid)
                    assign_material(rail, frame_mat)
                    objects.append(rail)

    return objects


def create_downpipe_brackets(params, wall_h, width, bldg_id=""):
    """Create small wall brackets holding downspout pipes."""
    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)
    roof_type = str(params.get("roof_type", "gable")).lower()
    if "flat" in roof_type:
        return []

    bracket_mat = get_or_create_material("mat_pipe_bracket", colour_hex="#4A4A4A", roughness=0.4)
    _bsdf = bracket_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.75
    objects = []
    hw = width / 2

    rd = params.get("roof_detail", {})
    overhang = (rd.get("eave_overhang_mm", 300) if isinstance(rd, dict) else 300) / 1000.0

    positions = []
    if not party_left:
        positions.append(-hw - 0.02)
    if not party_right:
        positions.append(hw + 0.02)

    for sx in positions:
        # Brackets at regular intervals up the wall
        bracket_z = 0.5
        while bracket_z < wall_h - 0.3:
            bpy.ops.mesh.primitive_cube_add(size=1)
            br = bpy.context.active_object
            br.name = f"pipe_bracket_{bldg_id}_{int(bracket_z*10)}"
            br.scale = (0.06, 0.04, 0.02)
            bpy.ops.object.transform_apply(scale=True)
            br.location = (sx, overhang + 0.02, bracket_z)
            assign_material(br, bracket_mat)
            objects.append(br)
            bracket_z += 1.5

    return objects


def create_balconies(params, wall_h, facade_width, bldg_id=""):
    """Create balconies — projecting platforms with railings on upper floors."""
    balcony_type = str(params.get("balcony_type", "")).lower()
    balcony_count = params.get("balconies", 0)
    if isinstance(balcony_count, dict):
        balcony_count = balcony_count.get("count", 0)
    if not balcony_type and not balcony_count:
        return []
    if isinstance(balcony_count, bool):
        balcony_count = 1 if balcony_count else 0
    if not balcony_count or balcony_count < 1:
        balcony_count = 1

    floor_heights = params.get("floor_heights_m", [3.0, 3.0])
    if len(floor_heights) < 2:
        return []  # balconies need at least 2 floors

    objects = []
    trim_hex = get_trim_hex(params)
    rail_mat = get_or_create_material("mat_balcony_rail", colour_hex="#2A2A2A", roughness=0.3)
    _bsdf = rail_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.90
    deck_mat = get_or_create_material(f"mat_balcony_deck_{trim_hex.lstrip('#')}",
                                       colour_hex="#6A6A6A", roughness=0.7)

    # Balcony at second floor level
    z_base = floor_heights[0]
    bal_w = min(facade_width * 0.5, 3.0)
    bal_proj = 1.0
    bal_thick = 0.08
    rail_h = 1.0

    for bi in range(min(balcony_count, 3)):
        if balcony_count == 1:
            bx = 0
        else:
            bx = -facade_width / 4 + (facade_width / 2) * bi / max(1, balcony_count - 1)

        # Deck slab
        bpy.ops.mesh.primitive_cube_add(size=1)
        deck = bpy.context.active_object
        deck.name = f"balcony_deck_{bi}_{bldg_id}"
        deck.scale = (bal_w, bal_proj, bal_thick)
        bpy.ops.object.transform_apply(scale=True)
        deck.location = (bx, bal_proj / 2, z_base - bal_thick / 2)
        assign_material(deck, deck_mat)
        objects.append(deck)

        # Underside bracket supports (two triangular brackets)
        bracket_mat = get_or_create_material("mat_balcony_bracket", colour_hex="#4A4A4A", roughness=0.5)
        for side, sx in [("L", bx - bal_w / 3), ("R", bx + bal_w / 3)]:
            bm = bmesh.new()
            v0 = bm.verts.new((sx - 0.03, 0, z_base - bal_thick))
            v1 = bm.verts.new((sx + 0.03, 0, z_base - bal_thick))
            v2 = bm.verts.new((sx + 0.03, bal_proj * 0.7, z_base - bal_thick))
            v3 = bm.verts.new((sx - 0.03, 0, z_base - bal_thick - 0.4))
            v4 = bm.verts.new((sx + 0.03, 0, z_base - bal_thick - 0.4))
            bm.faces.new([v0, v1, v2])
            bm.faces.new([v0, v3, v4, v1])
            bm.faces.new([v3, v0, v2])
            bm.faces.new([v1, v4, v2])
            bm.faces.new([v3, v2, v4])
            mesh = bpy.data.meshes.new(f"bal_bracket_{side}_{bi}")
            bm.to_mesh(mesh)
            bm.free()
            br_obj = bpy.data.objects.new(f"bal_bracket_{side}_{bi}_{bldg_id}", mesh)
            bpy.context.collection.objects.link(br_obj)
            assign_material(br_obj, bracket_mat)
            objects.append(br_obj)

        # Railing — front and sides
        # Front rail
        bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=bal_w, vertices=8)
        fr = bpy.context.active_object
        fr.name = f"balcony_rail_front_{bi}_{bldg_id}"
        fr.rotation_euler.y = math.pi / 2
        fr.location = (bx, bal_proj, z_base + rail_h)
        assign_material(fr, rail_mat)
        objects.append(fr)

        # Side rails
        for side, sx in [("L", bx - bal_w / 2), ("R", bx + bal_w / 2)]:
            bpy.ops.mesh.primitive_cylinder_add(radius=0.02, depth=bal_proj, vertices=8)
            sr = bpy.context.active_object
            sr.name = f"balcony_rail_{side}_{bi}_{bldg_id}"
            sr.rotation_euler.x = math.pi / 2
            sr.location = (sx, bal_proj / 2, z_base + rail_h)
            assign_material(sr, rail_mat)
            objects.append(sr)

        # Vertical balusters on front
        num_bal = max(3, int(bal_w / 0.12))
        for vi in range(num_bal + 1):
            vx = bx - bal_w / 2 + (bal_w / num_bal) * vi
            bpy.ops.mesh.primitive_cylinder_add(radius=0.01, depth=rail_h, vertices=6)
            vb = bpy.context.active_object
            vb.name = f"balcony_baluster_{bi}_{vi}_{bldg_id}"
            vb.location = (vx, bal_proj, z_base + rail_h / 2)
            assign_material(vb, rail_mat)
            objects.append(vb)

    return objects


def create_decorative_brickwork(params, wall_h, width, depth, bldg_id=""):
    """Create decorative brick patterns — raised bands, diamond inserts, header courses."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []
    db = dec.get("decorative_brickwork", {})
    if not db:
        return []
    if isinstance(db, dict) and db.get("present") is False:
        return []

    objects = []
    facade_hex = get_facade_hex(params)
    # Decorative brick is same material but slightly darker/contrasting
    r, g, b = hex_to_rgb(facade_hex)
    contrast_hex = "#{:02X}{:02X}{:02X}".format(
        max(0, int(r * 0.7 * 255)), max(0, int(g * 0.65 * 255)), max(0, int(b * 0.6 * 255)))
    brick_mat = get_or_create_material(f"mat_dec_brick_{bldg_id}", colour_hex=contrast_hex, roughness=0.85)

    floor_heights = params.get("floor_heights_m", [3.0])

    # Decorative band between floors — soldier course (bricks turned on end)
    band_h = 0.065  # one brick height turned on end
    band_proj = 0.015
    z = 0
    for i, fh in enumerate(floor_heights[:-1]):
        z += fh
        bpy.ops.mesh.primitive_cube_add(size=1)
        band = bpy.context.active_object
        band.name = f"dec_brick_band_{i}_{bldg_id}"
        band.scale = (width + band_proj, band_proj * 2, band_h)
        bpy.ops.object.transform_apply(scale=True)
        band.location = (0, band_proj, z)
        assign_material(band, brick_mat)
        objects.append(band)

    # Diamond brick pattern in gable (if gable roof)
    roof_type = str(params.get("roof_type", "")).lower()
    diamond_count = 0
    if isinstance(db, dict):
        diamond_count = db.get("diamond_brick_count", 0)
        if not diamond_count and db.get("diamond_pattern"):
            diamond_count = 1
    if "gable" in roof_type and diamond_count > 0:
        pitch = params.get("roof_pitch_deg", 35)
        ridge_h = (width / 2) * _safe_tan(pitch)
        gable_center_z = wall_h + ridge_h * 0.4
        bpy.ops.mesh.primitive_cube_add(size=1)
        diamond = bpy.context.active_object
        diamond.name = f"dec_diamond_{bldg_id}"
        diamond.scale = (0.15, 0.02, 0.15)
        bpy.ops.object.transform_apply(scale=True)
        diamond.rotation_euler.y = math.pi / 4  # rotate 45 degrees
        diamond.location = (0, 0.02, gable_center_z)
        assign_material(diamond, brick_mat)
        objects.append(diamond)

    return objects


def create_pilasters(params, wall_h, width, depth, bldg_id=""):
    """Create pilasters — flat columns projecting from the facade."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []
    pil = dec.get("pilasters", {})
    if not isinstance(pil, dict) or not pil:
        return []

    objects = []
    pil_w = pil.get("width_mm", 200) / 1000
    pil_proj = pil.get("projection_mm", 40) / 1000
    pil_hex = pil.get("colour_hex", get_facade_hex(params))
    pil_mat = get_or_create_material(f"mat_pilaster_{pil_hex.lstrip('#')}", colour_hex=pil_hex, roughness=0.8)

    # Default: pilasters flanking the facade
    count = pil.get("count", 2)
    hw = width / 2

    if count == 2:
        positions = [(-hw + pil_w / 2, "pilaster_left"), (hw - pil_w / 2, "pilaster_right")]
    elif count == 4:
        third = width / 3
        positions = [
            (-hw + pil_w / 2, "pilaster_far_left"),
            (-third / 2, "pilaster_inner_left"),
            (third / 2, "pilaster_inner_right"),
            (hw - pil_w / 2, "pilaster_far_right"),
        ]
    else:
        spacing = width / max(1, count - 1)
        positions = [(-hw + spacing * i, f"pilaster_{i}") for i in range(count)]

    for x, name in positions:
        # Main shaft
        bpy.ops.mesh.primitive_cube_add(size=1)
        shaft = bpy.context.active_object
        shaft.name = f"{name}_{bldg_id}"
        shaft.scale = (pil_w, pil_proj, wall_h - 0.2)
        bpy.ops.object.transform_apply(scale=True)
        shaft.location = (x, pil_proj / 2, wall_h / 2)
        assign_material(shaft, pil_mat)
        objects.append(shaft)

        # Capital (top detail) — wider flared top
        bpy.ops.mesh.primitive_cube_add(size=1)
        cap = bpy.context.active_object
        cap.name = f"{name}_cap_{bldg_id}"
        cap.scale = (pil_w + 0.04, pil_proj + 0.02, 0.08)
        bpy.ops.object.transform_apply(scale=True)
        cap.location = (x, pil_proj / 2, wall_h - 0.04)
        assign_material(cap, pil_mat)
        objects.append(cap)

        # Base (bottom plinth)
        bpy.ops.mesh.primitive_cube_add(size=1)
        base = bpy.context.active_object
        base.name = f"{name}_base_{bldg_id}"
        base.scale = (pil_w + 0.03, pil_proj + 0.015, 0.1)
        bpy.ops.object.transform_apply(scale=True)
        base.location = (x, pil_proj / 2, 0.05)
        assign_material(base, pil_mat)
        objects.append(base)

    return objects


def create_window_hoods(params, wall_h, facade_width, bldg_id=""):
    """Create projecting window hoods / label moulds above windows."""
    dec = params.get("decorative_elements", {})
    if not isinstance(dec, dict):
        return []
    hoods = dec.get("window_hoods", {})
    if not hoods:
        return []
    if isinstance(hoods, dict) and hoods.get("present") is False:
        return []

    hood_hex = get_accent_hex(params)
    if isinstance(hoods, dict):
        hood_hex = hoods.get("colour_hex", get_trim_hex(params))
    hood_mat = get_or_create_material(f"mat_hood_{hood_hex.lstrip('#')}", colour_hex=hood_hex, roughness=0.5)

    objects = []
    floor_heights = params.get("floor_heights_m", [3.0])
    windows_detail = get_effective_windows_detail(params)

    for fd in windows_detail:
        if not isinstance(fd, dict):
            continue
        floor_idx = int(_normalize_floor_index(fd.get("floor", 1), floor_heights))
        z_base = sum(floor_heights[:max(0, floor_idx - 1)])
        for w in fd.get("windows", []):
            if not isinstance(w, dict):
                continue
            count = w.get("count", 1)
            win_w = w.get("width_m", 0.85)
            win_h = w.get("height_m", 1.3)
            fi = max(0, min(floor_idx - 1, len(floor_heights) - 1))
            floor_h = floor_heights[fi] if floor_heights else 3.0
            sill_h = z_base + max(0.8, (floor_h - win_h) / 2)
            spacing = facade_width / (count + 1)

            for ci in range(count):
                cx = -facade_width / 2 + spacing * (ci + 1)
                hood_z = sill_h + win_h + 0.02

                # Hood shelf — projecting ledge above window
                bpy.ops.mesh.primitive_cube_add(size=1)
                shelf = bpy.context.active_object
                shelf.name = f"hood_shelf_{floor_idx}_{ci}_{bldg_id}"
                shelf.scale = (win_w + 0.15, 0.08, 0.04)
                bpy.ops.object.transform_apply(scale=True)
                shelf.location = (cx, 0.06, hood_z + 0.02)
                assign_material(shelf, hood_mat)
                objects.append(shelf)

                # Hood back plate — vertical face above window
                bpy.ops.mesh.primitive_cube_add(size=1)
                back = bpy.context.active_object
                back.name = f"hood_back_{floor_idx}_{ci}_{bldg_id}"
                back.scale = (win_w + 0.12, 0.02, 0.1)
                bpy.ops.object.transform_apply(scale=True)
                back.location = (cx, 0.01, hood_z + 0.07)
                assign_material(back, hood_mat)
                objects.append(back)

                # Small end brackets (corbels supporting the hood)
                for side, sx in [("L", cx - win_w / 2 - 0.04), ("R", cx + win_w / 2 + 0.04)]:
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    cb = bpy.context.active_object
                    cb.name = f"hood_corbel_{side}_{floor_idx}_{ci}_{bldg_id}"
                    cb.scale = (0.04, 0.06, 0.08)
                    bpy.ops.object.transform_apply(scale=True)
                    cb.location = (sx, 0.04, hood_z)
                    assign_material(cb, hood_mat)
                    objects.append(cb)

    return objects


def create_sign_band(params, wall_h, width, bldg_id=""):
    """Create a sign band / signage fascia at parapet level (31 commercial buildings)."""
    rf = params.get("roof_features", [])
    has_sign_band = any("sign_band" in str(f).lower() or "sign band" in str(f).lower()
                        for f in (rf if isinstance(rf, list) else []))
    if not has_sign_band:
        return []

    objects = []
    sign_hex = "#E8E0D0"
    sign_mat = get_or_create_material(f"mat_sign_band_{bldg_id}", colour_hex=sign_hex, roughness=0.4)
    frame_mat = get_or_create_material("mat_sign_frame", colour_hex="#3A3A3A", roughness=0.5)
    _bsdf = frame_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.70

    sign_h = 0.6
    sign_proj = 0.03

    # Sign panel
    bpy.ops.mesh.primitive_cube_add(size=1)
    panel = bpy.context.active_object
    panel.name = f"sign_band_panel_{bldg_id}"
    panel.scale = (width * 0.9, sign_proj, sign_h)
    bpy.ops.object.transform_apply(scale=True)
    panel.location = (0, sign_proj / 2, wall_h + sign_h / 2 + 0.05)
    assign_material(panel, sign_mat)
    objects.append(panel)

    # Frame border around sign
    border_w = 0.03
    for part, sx, sy, sw, sh in [
        ("top", 0, sign_proj / 2, width * 0.9 + border_w * 2, border_w),
        ("bot", 0, sign_proj / 2, width * 0.9 + border_w * 2, border_w),
    ]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        fr = bpy.context.active_object
        fr.name = f"sign_band_frame_{part}_{bldg_id}"
        fr.scale = (sw, sign_proj + 0.01, sh)
        bpy.ops.object.transform_apply(scale=True)
        z_fr = wall_h + sign_h + 0.05 + border_w / 2 if part == "top" else wall_h + 0.05 - border_w / 2
        fr.location = (sx, sy, z_fr)
        assign_material(fr, frame_mat)
        objects.append(fr)

    return objects


def create_sill_noses(params, wall_h, facade_width, bldg_id=""):
    """Create projecting drip edges on all window sills (prevents water damage)."""
    windows_detail = get_effective_windows_detail(params)
    floor_heights = params.get("floor_heights_m", [3.0])
    if not windows_detail:
        return []

    trim_hex = get_trim_hex(params)
    sill_mat = get_or_create_material(f"mat_sill_{trim_hex.lstrip('#')}", colour_hex=trim_hex, roughness=0.5)
    objects = []

    for fd in windows_detail:
        if not isinstance(fd, dict):
            continue
        floor_idx = int(_normalize_floor_index(fd.get("floor", 1), floor_heights))
        z_base = sum(floor_heights[:max(0, floor_idx - 1)])
        for w in fd.get("windows", []):
            if not isinstance(w, dict):
                continue
            count = w.get("count", 1)
            if count == 0:
                continue
            win_w = w.get("width_m", 0.85)
            win_h = w.get("height_m", 1.3)
            fi = max(0, min(floor_idx - 1, len(floor_heights) - 1))
            floor_h = floor_heights[fi] if floor_heights else 3.0
            sill_h = z_base + max(0.8, (floor_h - win_h) / 2)
            spacing = facade_width / (count + 1)

            for ci in range(count):
                cx = -facade_width / 2 + spacing * (ci + 1)
                # Projecting stone sill with drip groove
                bpy.ops.mesh.primitive_cube_add(size=1)
                sill = bpy.context.active_object
                sill.name = f"sill_proj_{floor_idx}_{ci}_{bldg_id}"
                sill.scale = (win_w + 0.08, 0.07, 0.035)
                bpy.ops.object.transform_apply(scale=True)
                sill.location = (cx, 0.05, sill_h - 0.018)
                assign_material(sill, sill_mat)
                objects.append(sill)

    return objects


def create_door_transoms(params, facade_width, bldg_id=""):
    """Create glazed transom windows above doors (1,311 doors have transom data)."""
    doors = params.get("doors_detail", [])
    if not doors:
        return []
    glass_mat = create_glass_material("mat_glass")
    trim_hex = get_trim_hex(params)
    frame_mat = get_or_create_material(f"mat_transom_frame_{trim_hex.lstrip('#')}",
                                        colour_hex=trim_hex, roughness=0.5)
    objects = []
    for di, door in enumerate(doors):
        if not isinstance(door, dict):
            continue
        transom = door.get("transom", {})
        if not isinstance(transom, dict) or not transom.get("present", False):
            continue
        t_h = transom.get("height_m", 0.4)
        door_w = door.get("width_m", 1.0)
        door_h = door.get("height_m", 2.2)
        pos = str(door.get("position", "center")).lower()
        dx = -facade_width / 4 if "left" in pos else facade_width / 4 if "right" in pos else 0
        transom_z = door_h + t_h / 2
        bpy.ops.mesh.primitive_plane_add(size=1)
        tg = bpy.context.active_object
        tg.name = f"transom_glass_{di}_{bldg_id}"
        tg.scale = (door_w * 0.9, 1, t_h * 0.8)
        bpy.ops.object.transform_apply(scale=True)
        tg.rotation_euler.x = math.pi / 2
        tg.location = (dx, -0.02, transom_z)
        assign_material(tg, glass_mat)
        objects.append(tg)
        bpy.ops.mesh.primitive_cube_add(size=1)
        tf = bpy.context.active_object
        tf.name = f"transom_frame_{di}_{bldg_id}"
        tf.scale = (door_w + 0.04, 0.04, t_h + 0.03)
        bpy.ops.object.transform_apply(scale=True)
        tf.location = (dx, 0.01, transom_z)
        assign_material(tf, frame_mat)
        objects.append(tf)
        # Center mullion
        bpy.ops.mesh.primitive_cube_add(size=1)
        mul = bpy.context.active_object
        mul.name = f"transom_mul_{di}_{bldg_id}"
        mul.scale = (0.015, 0.02, t_h * 0.75)
        bpy.ops.object.transform_apply(scale=True)
        mul.location = (dx, -0.01, transom_z)
        assign_material(mul, frame_mat)
        objects.append(mul)
    return objects


def create_ground_floor_arches(params, wall_h, facade_width, bldg_id=""):
    """Create arched openings at ground floor (328 buildings)."""
    gfa = params.get("ground_floor_arches", {})
    arch_type = str(params.get("ground_floor_arch_type", "none")).lower()
    if arch_type == "none" and not gfa:
        return []
    if not isinstance(gfa, dict):
        gfa = {}
    objects = []
    trim_hex = get_trim_hex(params)
    arch_mat = create_stone_material(f"mat_arch_{trim_hex.lstrip('#')}", trim_hex)
    for key in ["left_arch", "centre_arch", "right_arch"]:
        arch = gfa.get(key, {})
        if not isinstance(arch, dict) or not arch:
            continue
        a_w = arch.get("total_width_m", 2.0)
        a_h = arch.get("total_height_m", 2.5)
        a_type = str(arch.get("type", arch_type)).lower()
        ax = -facade_width / 3 if "left" in key else facade_width / 3 if "right" in key else 0
        for side, sx in [("L", ax - a_w / 2 - 0.05), ("R", ax + a_w / 2 + 0.05)]:
            bpy.ops.mesh.primitive_cube_add(size=1)
            j = bpy.context.active_object
            j.name = f"arch_jamb_{side}_{key}_{bldg_id}"
            j.scale = (0.1, 0.06, a_h)
            bpy.ops.object.transform_apply(scale=True)
            j.location = (sx, 0.03, a_h / 2)
            assign_material(j, arch_mat)
            objects.append(j)
        if "round" in a_type or "segmental" in a_type:
            num_stones = 11
            radius = a_w / 2 + 0.06
            for si in range(num_stones):
                angle = math.pi * si / (num_stones - 1)
                sx = ax + radius * math.cos(angle)
                sz = a_h - a_w / 2 + radius * math.sin(angle)
                bpy.ops.mesh.primitive_cube_add(size=1)
                stone = bpy.context.active_object
                stone.name = f"arch_stone_{key}_{si}_{bldg_id}"
                stone.scale = (0.1, 0.07, 0.08)
                bpy.ops.object.transform_apply(scale=True)
                stone.location = (sx, 0.04, sz)
                stone.rotation_euler.y = -(angle - math.pi / 2)
                assign_material(stone, arch_mat)
                objects.append(stone)
            bpy.ops.mesh.primitive_cube_add(size=1)
            ks = bpy.context.active_object
            ks.name = f"arch_keystone_{key}_{bldg_id}"
            ks.scale = (0.12, 0.08, 0.15)
            bpy.ops.object.transform_apply(scale=True)
            ks.location = (ax, 0.04, a_h + 0.05)
            assign_material(ks, arch_mat)
            objects.append(ks)
        else:
            bpy.ops.mesh.primitive_cube_add(size=1)
            lt = bpy.context.active_object
            lt.name = f"arch_lintel_{key}_{bldg_id}"
            lt.scale = (a_w + 0.2, 0.06, 0.1)
            bpy.ops.object.transform_apply(scale=True)
            lt.location = (ax, 0.03, a_h + 0.05)
            assign_material(lt, arch_mat)
            objects.append(lt)
    return objects


def create_eave_returns(params, wall_h, width, depth, bldg_id=""):
    """Create eave returns at gable ends."""
    roof_type = str(params.get("roof_type", "")).lower()
    if "gable" not in roof_type:
        return []
    party_left = params.get("party_wall_left", False)
    party_right = params.get("party_wall_right", False)
    trim_hex = get_trim_hex(params)
    mat = get_or_create_material(f"mat_eave_return_{trim_hex.lstrip('#')}",
                                  colour_hex=trim_hex, roughness=0.5)
    objects = []
    hw = width / 2
    rd = params.get("roof_detail", {})
    overhang = (rd.get("eave_overhang_mm", 300) if isinstance(rd, dict) else 300) / 1000.0
    for side, sx, skip in [("L", -hw - overhang * 0.5, party_left),
                            ("R", hw + overhang * 0.5, party_right)]:
        if skip:
            continue
        bpy.ops.mesh.primitive_cube_add(size=1)
        ret = bpy.context.active_object
        ret.name = f"eave_return_{side}_{bldg_id}"
        ret.scale = (overhang, 0.25, 0.1)
        bpy.ops.object.transform_apply(scale=True)
        ret.location = (sx, overhang - 0.125, wall_h + 0.05)
        assign_material(ret, mat)
        objects.append(ret)
    return objects


def create_drip_edge(params, wall_h, width, bldg_id=""):
    """Create metal drip edge along eave line."""
    if "flat" in str(params.get("roof_type", "")).lower():
        return []
    objects = []
    drip_mat = get_or_create_material("mat_drip_edge", colour_hex="#5A5A5A", roughness=0.3)
    # Galvanised metal flashing
    _bsdf = drip_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.80
    rd = params.get("roof_detail", {})
    overhang = (rd.get("eave_overhang_mm", 300) if isinstance(rd, dict) else 300) / 1000.0
    depth = params.get("facade_depth_m", 10.0)
    for name, y in [("front", overhang + 0.008), ("back", -depth - overhang - 0.008)]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        de = bpy.context.active_object
        de.name = f"drip_edge_{name}_{bldg_id}"
        de.scale = (width + overhang * 2, 0.015, 0.025)
        bpy.ops.object.transform_apply(scale=True)
        de.location = (0, y, wall_h - 0.01)
        assign_material(de, drip_mat)
        objects.append(de)
    return objects


def create_door_surround(params, facade_width, bldg_id=""):
    """Create decorative door surround with pilasters and entablature."""
    doors = params.get("doors_detail", [])
    if not doors:
        return []
    era = str((params.get("hcd_data") or {}).get("construction_date", "")).lower()
    if "1914" in era or "1930" in era or "post" in era:
        return []
    objects = []
    trim_hex = get_trim_hex(params)
    mat = get_or_create_material(f"mat_door_surround_{trim_hex.lstrip('#')}",
                                  colour_hex=trim_hex, roughness=0.5)
    door = doors[0] if isinstance(doors[0], dict) else {}
    door_w = door.get("width_m", 1.0)
    door_h = door.get("height_m", 2.2)
    pos = str(door.get("position", "center")).lower()
    dx = -facade_width / 4 if "left" in pos else facade_width / 4 if "right" in pos else 0
    pil_w, pil_proj = 0.08, 0.04
    for side, sx in [("L", dx - door_w / 2 - pil_w / 2 - 0.02),
                     ("R", dx + door_w / 2 + pil_w / 2 + 0.02)]:
        bpy.ops.mesh.primitive_cube_add(size=1)
        pil = bpy.context.active_object
        pil.name = f"door_pil_{side}_{bldg_id}"
        pil.scale = (pil_w, pil_proj, door_h)
        bpy.ops.object.transform_apply(scale=True)
        pil.location = (sx, pil_proj / 2, door_h / 2)
        assign_material(pil, mat)
        objects.append(pil)
    ent_w = door_w + pil_w * 2 + 0.12
    bpy.ops.mesh.primitive_cube_add(size=1)
    ent = bpy.context.active_object
    ent.name = f"door_ent_{bldg_id}"
    ent.scale = (ent_w, pil_proj + 0.02, 0.08)
    bpy.ops.object.transform_apply(scale=True)
    ent.location = (dx, pil_proj / 2, door_h + 0.04)
    assign_material(ent, mat)
    objects.append(ent)
    bpy.ops.mesh.primitive_cube_add(size=1)
    cap = bpy.context.active_object
    cap.name = f"door_cap_{bldg_id}"
    cap.scale = (ent_w + 0.06, pil_proj + 0.04, 0.03)
    bpy.ops.object.transform_apply(scale=True)
    cap.location = (dx, pil_proj / 2 + 0.01, door_h + 0.095)
    assign_material(cap, mat)
    objects.append(cap)
    return objects


def create_soffit_vents(params, wall_h, width, depth, bldg_id=""):
    """Create soffit vents in eave overhang."""
    if "flat" in str(params.get("roof_type", "")).lower():
        return []
    objects = []
    vent_mat = get_or_create_material("mat_soffit_vent", colour_hex="#3A3A3A", roughness=0.5)
    rd = params.get("roof_detail", {})
    overhang = (rd.get("eave_overhang_mm", 300) if isinstance(rd, dict) else 300) / 1000.0
    if overhang < 0.15:
        return []
    num_vents = max(1, int(width / 1.5))
    for vi in range(num_vents):
        vx = -width / 2 + 1.5 / 2 + vi * 1.5
        if vx > width / 2:
            break
        bpy.ops.mesh.primitive_cube_add(size=1)
        vent = bpy.context.active_object
        vent.name = f"soffit_vent_{vi}_{bldg_id}"
        vent.scale = (0.15, overhang * 0.4, 0.005)
        bpy.ops.object.transform_apply(scale=True)
        vent.location = (vx, overhang * 0.5, wall_h - 0.12)
        assign_material(vent, vent_mat)
        objects.append(vent)
    return objects


def create_vent_pipes(params, wall_h, width, depth, bldg_id=""):
    """Create plumbing vent pipes through roof."""
    objects = []
    pipe_mat = get_or_create_material("mat_vent_pipe", colour_hex="#5A5A5A", roughness=0.4)
    pitch = params.get("roof_pitch_deg", 35)
    ridge_h = (width / 2) * _safe_tan(pitch)
    pipe_h = 0.6
    pipe_x = width * 0.15
    pipe_y = -depth * 0.6
    pipe_z = wall_h + ridge_h * 0.3
    bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=pipe_h, vertices=8)
    pipe = bpy.context.active_object
    pipe.name = f"vent_pipe_{bldg_id}"
    pipe.location = (pipe_x, pipe_y, pipe_z + pipe_h / 2)
    assign_material(pipe, pipe_mat)
    objects.append(pipe)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=0.02, vertices=8)
    cap = bpy.context.active_object
    cap.name = f"vent_cap_{bldg_id}"
    cap.location = (pipe_x, pipe_y, pipe_z + pipe_h + 0.01)
    assign_material(cap, pipe_mat)
    objects.append(cap)
    return objects


def create_mail_slot(params, facade_width, bldg_id=""):
    """Create brass mail slot in front door."""
    if params.get("has_storefront"):
        return []
    objects = []
    slot_mat = get_or_create_material("mat_mail_slot", colour_hex="#C0A030", roughness=0.25)
    # Brass mail slot
    _bsdf = slot_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.95
    doors = params.get("doors_detail", [])
    dx = 0
    if doors and isinstance(doors[0], dict):
        pos = str(doors[0].get("position", "center")).lower()
        dx = -facade_width / 4 if "left" in pos else facade_width / 4 if "right" in pos else 0
    bpy.ops.mesh.primitive_cube_add(size=1)
    slot = bpy.context.active_object
    slot.name = f"mail_slot_{bldg_id}"
    slot.scale = (0.2, 0.015, 0.04)
    bpy.ops.object.transform_apply(scale=True)
    slot.location = (dx, -0.02, 1.1)
    assign_material(slot, slot_mat)
    objects.append(slot)
    return objects


def create_kick_plate(params, facade_width, bldg_id=""):
    """Create metal kick plate at bottom of front door."""
    doors = params.get("doors_detail", [])
    if not doors:
        return []
    objects = []
    plate_mat = get_or_create_material("mat_kick_plate", colour_hex="#C0A060", roughness=0.25)
    # Brass/bronze kick plate
    _bsdf = plate_mat.node_tree.nodes.get("Principled BSDF")
    if _bsdf and "Metallic" in _bsdf.inputs:
        _bsdf.inputs["Metallic"].default_value = 0.90
    for di, door in enumerate(doors):
        if not isinstance(door, dict):
            continue
        door_w = door.get("width_m", 1.0)
        pos = str(door.get("position", "center")).lower()
        dx = -facade_width / 4 if "left" in pos else facade_width / 4 if "right" in pos else 0
        bpy.ops.mesh.primitive_cube_add(size=1)
        kp = bpy.context.active_object
        kp.name = f"kick_plate_{di}_{bldg_id}"
        kp.scale = (door_w * 0.9, 0.01, 0.2)
        bpy.ops.object.transform_apply(scale=True)
        kp.location = (dx, -0.01, 0.1)
        assign_material(kp, plate_mat)
        objects.append(kp)
    return objects


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

    # Resolve bond pattern and polychrome for all volumes (inherited from main params)
    mv_bond = "running"
    fd_mv = params.get("facade_detail", {})
    if isinstance(fd_mv, dict):
        bp_mv = (fd_mv.get("bond_pattern") or "").lower()
        if bp_mv:
            mv_bond = bp_mv
    dfa_mv = params.get("deep_facade_analysis", {})
    if isinstance(dfa_mv, dict):
        bp_dfa_mv = (dfa_mv.get("brick_bond_observed") or "").lower()
        if bp_dfa_mv:
            mv_bond = bp_dfa_mv
    mv_polychrome = None
    if isinstance(dfa_mv, dict):
        poly_mv = dfa_mv.get("polychromatic_brick")
        if isinstance(poly_mv, dict):
            ph_mv = poly_mv.get("accent_hex", "")
            if ph_mv and ph_mv.startswith("#"):
                mv_polychrome = ph_mv

    # Track x position for placing volumes side by side
    total_width = 0
    for v in volumes:
        if not isinstance(v, dict):
            continue
        if v.get("stack_with_previous"):
            continue
        total_width += v.get("width_m", 5)
    x_cursor = -total_width / 2
    prev_cx = None

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
        vol_w = _clamp_positive(vol.get("width_m"), 5.0, minimum=1.0)
        vol_d = _clamp_positive(vol.get("depth_m"), 10.0, minimum=1.0)
        vol_floors = vol.get("floor_heights_m", [3.5])
        if not vol_floors or not isinstance(vol_floors, list):
            vol_floors = [3.5]
        vol_h = sum(max(0.5, float(fh)) for fh in vol_floors)
        vol_total_h = _clamp_positive(vol.get("total_height_m"), vol_h, minimum=2.0)

        print(f"  Volume: {vol_id} ({vol_w}m x {vol_d}m x {vol_total_h}m)")

        # Volume center x
        stack_with_previous = bool(vol.get("stack_with_previous", False))
        if stack_with_previous and prev_cx is not None:
            vol_cx = prev_cx
        else:
            vol_cx = x_cursor + vol_w / 2
        vol_cx += float(vol.get("x_offset_m", 0.0))
        vol_y_off = float(vol.get("y_offset_m", 0.0))
        vol_z_off = float(vol.get("z_offset_m", 0.0))
        vol_start_idx = len(all_objs)

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
                                               vol_hex, mortar_hex,
                                               bond_pattern=mv_bond,
                                               polychrome_hex=mv_polychrome)
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

            # Optional open belfry + spire cap
            spire_start = len(all_objs)
            spire = vol.get("spire", {})
            if isinstance(spire, dict) and spire:
                spire_h = float(spire.get("height_m", 4.0))
                spire_w = float(spire.get("base_width_m", vol_w * 0.9))
                spire_d = float(spire.get("base_depth_m", vol_d * 0.9))
                spire_style = str(spire.get("style", "pyramid")).lower()

                if "open" in spire_style or spire.get("open_belfry", False):
                    # Four slender corner posts at top stage
                    post_w = max(0.08, min(0.16, spire_w * 0.08))
                    post_d = post_w
                    post_h = max(0.8, spire_h * 0.45)
                    for sx in (-1, 1):
                        for sy in (-1, 1):
                            bpy.ops.mesh.primitive_cube_add(size=1)
                            post = bpy.context.active_object
                            post.name = f"tower_belfry_post_{sx}_{sy}_{bldg_id}"
                            post.scale = (post_w, post_d, post_h)
                            bpy.ops.object.transform_apply(scale=True)
                            post.location = (
                                vol_cx + sx * (spire_w / 2 - post_w / 2),
                                -vol_d / 2 + sy * (spire_d / 2 - post_d / 2),
                                vol_total_h + post_h / 2,
                            )
                            assign_material(post, tower_mat)
                            all_objs.append(post)

                # Spire body
                bm = bmesh.new()
                hw = spire_w / 2
                hd = spire_d / 2
                z0 = vol_total_h + 0.02
                apex = bm.verts.new((vol_cx, -vol_d / 2, z0 + spire_h))
                v0 = bm.verts.new((vol_cx - hw, -vol_d / 2 - hd, z0))
                v1 = bm.verts.new((vol_cx + hw, -vol_d / 2 - hd, z0))
                v2 = bm.verts.new((vol_cx + hw, -vol_d / 2 + hd, z0))
                v3 = bm.verts.new((vol_cx - hw, -vol_d / 2 + hd, z0))
                bm.faces.new([v0, v1, apex])
                bm.faces.new([v1, v2, apex])
                bm.faces.new([v2, v3, apex])
                bm.faces.new([v3, v0, apex])
                bm.faces.new([v0, v3, v2, v1])
                smesh = bpy.data.meshes.new(f"tower_spire_{bldg_id}")
                bm.to_mesh(smesh)
                bm.free()
                sobj = bpy.data.objects.new(f"tower_spire_{bldg_id}", smesh)
                bpy.context.collection.objects.link(sobj)
                spire_hex = str(spire.get("colour_hex", "#2E3138"))
                if not spire_hex.startswith("#"):
                    spire_hex = colour_name_to_hex(spire_hex)
                spire_mat = get_or_create_material(f"mat_tower_spire_{spire_hex.lstrip('#')}", colour_hex=spire_hex, roughness=0.65)
                assign_material(sobj, spire_mat)
                all_objs.append(sobj)

                if spire.get("cross", False):
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    cross_v = bpy.context.active_object
                    cross_v.name = f"tower_cross_v_{bldg_id}"
                    cross_v.scale = (0.04, 0.04, 0.45)
                    bpy.ops.object.transform_apply(scale=True)
                    cross_v.location = (vol_cx, -vol_d / 2, z0 + spire_h + 0.25)
                    assign_material(cross_v, get_or_create_material("mat_tower_cross", colour_hex="#8A8A8A", roughness=0.4))
                    all_objs.append(cross_v)
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    cross_h = bpy.context.active_object
                    cross_h.name = f"tower_cross_h_{bldg_id}"
                    cross_h.scale = (0.18, 0.04, 0.04)
                    bpy.ops.object.transform_apply(scale=True)
                    cross_h.location = (vol_cx, -vol_d / 2, z0 + spire_h + 0.25)
                    assign_material(cross_h, get_or_create_material("mat_tower_cross", colour_hex="#8A8A8A", roughness=0.4))
                    all_objs.append(cross_h)
            log_volume_feature("Tower spire", spire_start)

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
                                              "#B85A3A", mortar_hex,
                                              bond_pattern=mv_bond)
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
                band_count = max(1, int(cw.get("band_count", 1) or 1))
                band_gap = float(cw.get("band_gap_m", 0.35) or 0.35)
                z_base = float(cw.get("z_base_m", base_h) or base_h)
                add_mid_mullion = bool(cw.get("mid_mullion", True))

                glass_mat = create_glass_material("mat_curtain_glass", glass_type="storefront")
                mullion_hex = cw.get("mullion_colour", "#2A2A2A")
                if not mullion_hex.startswith("#"):
                    mullion_hex = "#2A2A2A"
                mullion_mat = get_or_create_material("mat_mullion", colour_hex=mullion_hex, roughness=0.4)

                cw_start_x = vol_cx - (bay_count * bay_w) / 2 + bay_w / 2
                for ri in range(band_count):
                    cw_z = z_base + bay_h / 2 + ri * (bay_h + band_gap)
                    for bi in range(bay_count):
                        bx = cw_start_x + bi * bay_w

                        # Glass panel
                        bpy.ops.mesh.primitive_plane_add(size=1)
                        gp = bpy.context.active_object
                        gp.name = f"curtain_glass_{ri}_{bi}_{bldg_id}"
                        gp.scale = (bay_w - mullion_w, 1, bay_h)
                        bpy.ops.object.transform_apply(scale=True)
                        gp.rotation_euler.x = math.pi / 2
                        gp.location = (bx, 0.16, cw_z)
                        assign_material(gp, glass_mat)
                        all_objs.append(gp)

                        # Vertical mullion (right side of each bay)
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        mul = bpy.context.active_object
                        mul.name = f"mullion_{ri}_{bi}_{bldg_id}"
                        mul.scale = (mullion_w, 0.08, bay_h)
                        bpy.ops.object.transform_apply(scale=True)
                        mul.location = (bx + bay_w / 2, 0.14, cw_z)
                        assign_material(mul, mullion_mat)
                        all_objs.append(mul)

                    # Horizontal mullion at mid height (optional)
                    if add_mid_mullion:
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        hmul = bpy.context.active_object
                        hmul.name = f"mullion_h_{ri}_{bldg_id}"
                        hmul.scale = (bay_count * bay_w, 0.08, mullion_w)
                        bpy.ops.object.transform_apply(scale=True)
                        hmul.location = (vol_cx, 0.14, cw_z)
                        assign_material(hmul, mullion_mat)
                        all_objs.append(hmul)
            log_volume_feature("Curtain wall", curtain_start)

            # Explicit openings for modern blocks (optional, used for coarse facade cut-ins)
            modern_openings_start = len(all_objs)
            win_rows = vol.get("window_rows", [])
            if isinstance(win_rows, list):
                for ri, row in enumerate(win_rows):
                    if not isinstance(row, dict):
                        continue
                    count = int(row.get("count", 0) or 0)
                    if count <= 0:
                        continue
                    ww = float(row.get("width_m", 1.2))
                    wh = float(row.get("height_m", 1.0))
                    sill = float(row.get("sill_height_m", 1.0))
                    row_z_off = float(row.get("z_offset_m", 0.0) or 0.0)
                    row_x_off = float(row.get("x_offset_m", 0.0) or 0.0)
                    spacing = vol_w / (count + 1)
                    frame_hex = str(row.get("frame_colour", "#2F3A52"))
                    if not frame_hex.startswith("#"):
                        frame_hex = colour_name_to_hex(frame_hex)
                    frame_mat = get_or_create_material(f"mat_modern_frame_{frame_hex.lstrip('#')}", colour_hex=frame_hex, roughness=0.45)
                    add_frames = bool(row.get("add_frames", True))
                    positions = row.get("positions_m", [])
                    use_positions = isinstance(positions, list) and len(positions) > 0

                    iter_count = len(positions) if use_positions else count
                    for wi in range(iter_count):
                        if use_positions:
                            wx = vol_cx + float(positions[wi] or 0.0) + row_x_off
                        else:
                            wx = vol_cx - vol_w / 2 + spacing * (wi + 1) + row_x_off
                        cutter = create_rect_cutter(f"modern_win_cut_{ri}_{wi}_{bldg_id}", ww, wh, depth=0.8)
                        cutter.location.x = wx
                        cutter.location.y = 0.01
                        cutter.location.z = sill + row_z_off + wh / 2
                        boolean_cut(outer, cutter)

                        bpy.ops.mesh.primitive_plane_add(size=1)
                        gl = bpy.context.active_object
                        gl.name = f"modern_glass_{ri}_{wi}_{bldg_id}"
                        gl.scale = (ww * 0.88, 1, wh * 0.88)
                        bpy.ops.object.transform_apply(scale=True)
                        gl.rotation_euler.x = math.pi / 2
                        gl.location = (wx, 0.02, sill + row_z_off + wh / 2)
                        assign_material(gl, create_glass_material())
                        all_objs.append(gl)

                        if add_frames:
                            ft = 0.04
                            for fn, fs, fl in [
                                ("t", (ww + ft, 0.05, ft), (wx, 0.03, sill + row_z_off + wh)),
                                ("b", (ww + ft, 0.05, ft), (wx, 0.03, sill + row_z_off)),
                                ("l", (ft, 0.05, wh), (wx - ww / 2, 0.03, sill + row_z_off + wh / 2)),
                                ("r", (ft, 0.05, wh), (wx + ww / 2, 0.03, sill + row_z_off + wh / 2)),
                            ]:
                                bpy.ops.mesh.primitive_cube_add(size=1)
                                fr = bpy.context.active_object
                                fr.name = f"modern_frame_{fn}_{ri}_{wi}_{bldg_id}"
                                fr.scale = fs
                                bpy.ops.object.transform_apply(scale=True)
                                fr.location = fl
                                assign_material(fr, frame_mat)
                                all_objs.append(fr)
                        if row.get("add_horizontal_mullion", False):
                            bpy.ops.mesh.primitive_cube_add(size=1)
                            hbar = bpy.context.active_object
                            hbar.name = f"modern_hmullion_{ri}_{bldg_id}"
                            hbar.scale = (vol_w / 2, 0.03, 0.015)
                            bpy.ops.object.transform_apply(scale=True)
                            hbar.location = (vol_cx, 0.14, sill + row_z_off + wh / 2)
                            assign_material(hbar, frame_mat)
                            all_objs.append(hbar)

            vol_doors = vol.get("doors_detail", [])
            if isinstance(vol_doors, list):
                door_hex = str(vol.get("door_colour_hex", "#2F3A52"))
                if not door_hex.startswith("#"):
                    door_hex = colour_name_to_hex(door_hex)
                door_roughness = float(vol.get("door_roughness", 0.45) or 0.45)
                door_mat = get_or_create_material(
                    f"mat_modern_door_{door_hex.lstrip('#')}",
                    colour_hex=door_hex,
                    roughness=door_roughness,
                )
                for di, ds in enumerate(vol_doors):
                    if not isinstance(ds, dict):
                        continue
                    dw = float(ds.get("width_m", 1.2))
                    dh = float(ds.get("height_m", 2.2))
                    dpos = str(ds.get("position", "center")).lower()
                    if "left" in dpos:
                        dx = vol_cx - vol_w * 0.28
                    elif "right" in dpos:
                        dx = vol_cx + vol_w * 0.28
                    else:
                        dx = vol_cx
                    dx += float(ds.get("x_offset_m", 0.0) or 0.0)

                    cutter = create_rect_cutter(f"modern_door_cut_{di}_{bldg_id}", dw, dh, depth=0.8)
                    cutter.location.x = dx
                    cutter.location.y = 0.01
                    cutter.location.z = dh / 2
                    boolean_cut(outer, cutter)

                    bpy.ops.mesh.primitive_cube_add(size=1)
                    dmesh = bpy.context.active_object
                    dmesh.name = f"modern_door_{di}_{bldg_id}"
                    dmesh.scale = (dw * 0.92, 0.03, dh * 0.96)
                    bpy.ops.object.transform_apply(scale=True)
                    dmesh.location = (dx, 0.03, dh / 2)
                    assign_material(dmesh, door_mat)
                    all_objs.append(dmesh)
                    frame_depth = float(ds.get("frame_depth_m", 0.04) or 0.04)
                    frame_mat = get_or_create_material(f"mat_modern_doorframe_{door_hex.lstrip('#')}", colour_hex=door_hex, roughness=door_roughness)
                    for fn, fl_offset in (("left", -dw / 2), ("right", dw / 2)):
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        df = bpy.context.active_object
                        df.name = f"door_frame_{fn}_{di}_{bldg_id}"
                        df.scale = (0.02, frame_depth / 2, dh)
                        bpy.ops.object.transform_apply(scale=True)
                        x_off = dx + fl_offset
                        df.location = (x_off, 0.02, dh / 2)
                        assign_material(df, frame_mat)
                        all_objs.append(df)
            log_volume_feature("Modern explicit openings", modern_openings_start)

            # Flat roof
            modern_roof_start = len(all_objs)
            if not bool(vol.get("skip_flat_roof", False)):
                bpy.ops.mesh.primitive_plane_add(size=1)
                mroof = bpy.context.active_object
                mroof.name = f"modern_roof_{bldg_id}"
                mroof.scale = (vol_w + 0.1, vol_d + 0.1, 1)
                bpy.ops.object.transform_apply(scale=True)
                mroof.location = (vol_cx, -vol_d / 2, vol_h + 0.01)
                roof_mat = get_or_create_material("mat_roof_flat_modern", colour_hex="#4A4A4A", roughness=0.9)
                assign_material(mroof, roof_mat)
                all_objs.append(mroof)

            # Optional roofline proxy details (parapet/fascia/canopy posts)
            roofline_start = len(all_objs)
            parapet_h = float(vol.get("parapet_height_m", 0.0) or 0.0)
            parapet_t = float(vol.get("parapet_thickness_m", 0.18) or 0.18)
            fascia_d = float(vol.get("fascia_depth_m", 0.0) or 0.0)
            fascia_h = float(vol.get("fascia_height_m", 0.35) or 0.35)
            trim_hex = str(vol.get("trim_colour_hex", get_trim_hex(params)))
            if not trim_hex.startswith("#"):
                trim_hex = colour_name_to_hex(trim_hex)
            trim_roughness = float(vol.get("trim_roughness", 0.55) or 0.55)
            trim_mat = get_or_create_material(
                f"mat_modern_trim_{trim_hex.lstrip('#')}",
                colour_hex=trim_hex,
                roughness=trim_roughness,
            )

            if parapet_h > 0.01:
                # Front
                bpy.ops.mesh.primitive_cube_add(size=1)
                pf = bpy.context.active_object
                pf.name = f"modern_parapet_f_{bldg_id}"
                pf.scale = (vol_w / 2, parapet_t / 2, parapet_h / 2)
                bpy.ops.object.transform_apply(scale=True)
                pf.location = (vol_cx, parapet_t / 2, vol_h + parapet_h / 2)
                assign_material(pf, trim_mat)
                all_objs.append(pf)
                # Back
                bpy.ops.mesh.primitive_cube_add(size=1)
                pb = bpy.context.active_object
                pb.name = f"modern_parapet_b_{bldg_id}"
                pb.scale = (vol_w / 2, parapet_t / 2, parapet_h / 2)
                bpy.ops.object.transform_apply(scale=True)
                pb.location = (vol_cx, -vol_d - parapet_t / 2, vol_h + parapet_h / 2)
                assign_material(pb, trim_mat)
                all_objs.append(pb)
                # Left
                bpy.ops.mesh.primitive_cube_add(size=1)
                pl = bpy.context.active_object
                pl.name = f"modern_parapet_l_{bldg_id}"
                pl.scale = (parapet_t / 2, vol_d / 2 + parapet_t, parapet_h / 2)
                bpy.ops.object.transform_apply(scale=True)
                pl.location = (vol_cx - vol_w / 2 - parapet_t / 2, -vol_d / 2, vol_h + parapet_h / 2)
                assign_material(pl, trim_mat)
                all_objs.append(pl)
                # Right
                bpy.ops.mesh.primitive_cube_add(size=1)
                pr = bpy.context.active_object
                pr.name = f"modern_parapet_r_{bldg_id}"
                pr.scale = (parapet_t / 2, vol_d / 2 + parapet_t, parapet_h / 2)
                bpy.ops.object.transform_apply(scale=True)
                pr.location = (vol_cx + vol_w / 2 + parapet_t / 2, -vol_d / 2, vol_h + parapet_h / 2)
                assign_material(pr, trim_mat)
                all_objs.append(pr)

            if fascia_d > 0.01:
                bpy.ops.mesh.primitive_cube_add(size=1)
                fb = bpy.context.active_object
                fb.name = f"modern_fascia_{bldg_id}"
                fb.scale = (vol_w / 2, fascia_d / 2, fascia_h / 2)
                bpy.ops.object.transform_apply(scale=True)
                fb.location = (vol_cx, fascia_d / 2, vol_h - fascia_h / 2)
                assign_material(fb, trim_mat)
                all_objs.append(fb)

            post_count = int(vol.get("canopy_post_count", 0) or 0)
            if post_count > 0:
                post_w = float(vol.get("canopy_post_width_m", 0.25) or 0.25)
                post_d = float(vol.get("canopy_post_depth_m", 0.25) or 0.25)
                post_h = float(vol.get("canopy_post_height_m", max(2.4, vol_h - 0.08)) or max(2.4, vol_h - 0.08))
                post_inset = float(vol.get("canopy_post_inset_m", 0.4) or 0.4)
                door_hex = str(vol.get("door_colour_hex", "#2F3A52"))
                if not door_hex.startswith("#"):
                    door_hex = colour_name_to_hex(door_hex)
                post_roughness = float(vol.get("post_roughness", 0.6) or 0.6)
                post_mat = get_or_create_material(
                    f"mat_canopy_post_{door_hex.lstrip('#')}",
                    colour_hex=door_hex,
                    roughness=post_roughness,
                )
                denom = post_count + 1
                for pi in range(post_count):
                    px = vol_cx - vol_w / 2 + (pi + 1) * (vol_w / denom)
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    post = bpy.context.active_object
                    post.name = f"canopy_post_{pi}_{bldg_id}"
                    post.scale = (post_w / 2, post_d / 2, post_h / 2)
                    bpy.ops.object.transform_apply(scale=True)
                    post.location = (px, post_inset, post_h / 2)
                    assign_material(post, post_mat)
                    all_objs.append(post)

                beam_h = float(vol.get("canopy_beam_height_m", 0.0) or 0.0)
                if beam_h > 0.01:
                    beam_d = float(vol.get("canopy_beam_depth_m", 0.2) or 0.2)
                    beam_z = float(vol.get("canopy_beam_z_m", post_h) or post_h)
                    beam_w = max(0.4, vol_w - 2 * post_inset)
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    beam = bpy.context.active_object
                    beam.name = f"canopy_beam_{bldg_id}"
                    beam.scale = (beam_w / 2, beam_d / 2, beam_h / 2)
                    bpy.ops.object.transform_apply(scale=True)
                    beam.location = (vol_cx, post_inset, beam_z - beam_h / 2)
                    assign_material(beam, post_mat)
                    all_objs.append(beam)

            roof_units = vol.get("roof_units", [])
            if isinstance(roof_units, list):
                for ui, unit in enumerate(roof_units):
                    if not isinstance(unit, dict):
                        continue
                    uw = float(unit.get("width_m", 1.2) or 1.2)
                    ud = float(unit.get("depth_m", 1.0) or 1.0)
                    uh = float(unit.get("height_m", 0.8) or 0.8)
                    ux = float(unit.get("x_offset_m", 0.0) or 0.0)
                    uy = float(unit.get("y_offset_m", -vol_d * 0.5) or -vol_d * 0.5)
                    uz = float(unit.get("z_offset_m", vol_h + 0.05) or (vol_h + 0.05))
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    ru = bpy.context.active_object
                    ru.name = f"roof_unit_{ui}_{bldg_id}"
                    ru.scale = (uw / 2, ud / 2, uh / 2)
                    bpy.ops.object.transform_apply(scale=True)
                    ru.location = (vol_cx + ux, uy, uz + uh / 2)
                    unit_roughness = float(unit.get("roughness", 0.7) or 0.7)
                    unit_mat = get_or_create_material(
                        f"mat_roof_unit_{ui}_{bldg_id}",
                        colour_hex="#6A7078",
                        roughness=unit_roughness,
                    )
                    assign_material(ru, unit_mat)
                    all_objs.append(ru)

            pickets = vol.get("fence_pickets", {})
            if isinstance(pickets, dict) and pickets:
                count = max(2, int(pickets.get("count", 24) or 24))
                pw = float(pickets.get("width_m", 0.07) or 0.07)
                pd = float(pickets.get("depth_m", 0.05) or 0.05)
                ph = float(pickets.get("height_m", max(1.2, vol_h - 0.2)) or max(1.2, vol_h - 0.2))
                inset = float(pickets.get("inset_m", 0.02) or 0.02)
                lift = float(pickets.get("lift_m", 0.0) or 0.0)
                phex = str(pickets.get("colour_hex", "#B99661"))
                if not phex.startswith("#"):
                    phex = colour_name_to_hex(phex)
                pmat = get_or_create_material(f"mat_fence_picket_{phex.lstrip('#')}", colour_hex=phex, roughness=0.85)
                for pi in range(count):
                    px = vol_cx - vol_w / 2 + (pi + 0.5) * (vol_w / count)
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    pk = bpy.context.active_object
                    pk.name = f"fence_picket_{pi}_{bldg_id}"
                    pk.scale = (pw / 2, pd / 2, ph / 2)
                    bpy.ops.object.transform_apply(scale=True)
                    pk.location = (px, inset, lift + ph / 2)
                    assign_material(pk, pmat)
                    all_objs.append(pk)
            lights = vol.get("sidewalk_lights", [])
            if isinstance(lights, list) and lights:
                light_color = str(lights[0].get("colour_hex", "#F7E85C"))
                if not light_color.startswith("#"):
                    light_color = colour_name_to_hex(light_color)
                light_mat = get_or_create_material("mat_sidewalk_light", colour_hex=light_color, roughness=0.15)
                pole_mat = get_or_create_material("mat_sidewalk_pole", colour_hex="#0E0E0E", roughness=0.35)
                _bsdf = pole_mat.node_tree.nodes.get("Principled BSDF")
                if _bsdf and "Metallic" in _bsdf.inputs:
                    _bsdf.inputs["Metallic"].default_value = 0.75
                spacing = vol_w / (len(lights) + 1)
                for li, light in enumerate(lights):
                    lx = vol_cx - vol_w / 2 + spacing * (li + 1)
                    pole_h = float(light.get("height_m", 2.8) or 2.8)
                    pole_d = float(light.get("diameter_m", 0.08) or 0.08)
                    lamp_d = float(light.get("lamp_diameter_m", 0.28) or 0.28)
                    bpy.ops.mesh.primitive_cylinder_add(radius=pole_d / 2, depth=pole_h)
                    pole = bpy.context.active_object
                    pole.name = f"sidewalk_pole_{li}_{bldg_id}"
                    pole.location = (lx, inset, pole_h / 2)
                    assign_material(pole, pole_mat)
                    all_objs.append(pole)

                    bpy.ops.mesh.primitive_uv_sphere_add(radius=lamp_d / 2)
                    lamp = bpy.context.active_object
                    lamp.name = f"sidewalk_lamp_{li}_{bldg_id}"
                    lamp.location = (lx, inset, pole_h + lamp_d / 2)
                    assign_material(lamp, light_mat)
                    all_objs.append(lamp)

            log_volume_feature("Modern roofline proxies", roofline_start)
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
                                              vol_hex, mortar_hex,
                                              bond_pattern=mv_bond,
                                              polychrome_hex=mv_polychrome)
            assign_material(outer, hall_mat)
            all_objs.append(outer)

            # Volume-specific openings (for detailed multi-volume churches)
            detail_openings_start = len(all_objs)
            win_rows = vol.get("windows_detail", vol.get("window_rows", []))
            if isinstance(win_rows, list):
                for ri, row in enumerate(win_rows):
                    if not isinstance(row, dict):
                        continue
                    count = int(row.get("count", 0) or 0)
                    if count <= 0:
                        continue
                    ww = float(row.get("width_m", 0.9))
                    wh = float(row.get("height_m", 1.8))
                    sill = float(row.get("sill_height_m", 0.9))
                    row_type = str(row.get("type", ""))
                    arch_type = str(row.get("arch_type", ""))
                    if not arch_type:
                        arch_type = "pointed" if "lancet" in row_type.lower() or "pointed" in row_type.lower() else "segmental"
                    spacing = vol_w / (count + 1)
                    frame_hex = str(row.get("frame_colour", "#3A3A3A"))
                    if not frame_hex.startswith("#"):
                        frame_hex = colour_name_to_hex(frame_hex)
                    frame_mat = get_or_create_material(f"mat_volframe_{frame_hex.lstrip('#')}", colour_hex=frame_hex, roughness=0.5)

                    for wi in range(count):
                        wx = vol_cx - vol_w / 2 + spacing * (wi + 1)
                        if arch_type in ("pointed", "segmental", "semicircular"):
                            spring_h = wh * 0.72
                            cutter = create_arch_cutter(
                                f"vol_win_cut_{ri}_{wi}_{bldg_id}",
                                ww,
                                wh,
                                spring_h,
                                arch_type=arch_type,
                                depth=0.8,
                            )
                        else:
                            cutter = create_rect_cutter(f"vol_win_cut_{ri}_{wi}_{bldg_id}", ww, wh, depth=0.8)
                            cutter.location.z = wh / 2

                        cutter.location.x = wx
                        cutter.location.y = 0.01
                        cutter.location.z += sill
                        boolean_cut(outer, cutter)

                        # Glass
                        bpy.ops.mesh.primitive_plane_add(size=1)
                        gl = bpy.context.active_object
                        gl.name = f"vol_glass_{ri}_{wi}_{bldg_id}"
                        gl.scale = (ww * 0.85, 1, wh * 0.85)
                        bpy.ops.object.transform_apply(scale=True)
                        gl.rotation_euler.x = math.pi / 2
                        gl.location = (wx, 0.02, sill + wh / 2)
                        assign_material(gl, create_glass_material())
                        all_objs.append(gl)

                        # Simple frame
                        ft = 0.04
                        for fn, fs, fl in [
                            ("t", (ww + ft, 0.05, ft), (wx, 0.03, sill + wh)),
                            ("b", (ww + ft * 2, 0.06, ft), (wx, 0.03, sill)),
                            ("l", (ft, 0.05, wh), (wx - ww / 2, 0.03, sill + wh / 2)),
                            ("r", (ft, 0.05, wh), (wx + ww / 2, 0.03, sill + wh / 2)),
                        ]:
                            bpy.ops.mesh.primitive_cube_add(size=1)
                            fr = bpy.context.active_object
                            fr.name = f"vol_frame_{fn}_{ri}_{wi}_{bldg_id}"
                            fr.scale = fs
                            bpy.ops.object.transform_apply(scale=True)
                            fr.location = fl
                            assign_material(fr, frame_mat)
                            all_objs.append(fr)

            vol_doors = vol.get("doors_detail", [])
            if isinstance(vol_doors, list):
                door_mat = get_or_create_material("mat_vol_door", colour_hex="#7B2132", roughness=0.45)
                for di, ds in enumerate(vol_doors):
                    if not isinstance(ds, dict):
                        continue
                    dw = float(ds.get("width_m", 1.0))
                    dh = float(ds.get("height_m", 2.2))
                    dpos = str(ds.get("position", "center")).lower()
                    if "left" in dpos:
                        dx = vol_cx - vol_w * 0.25
                    elif "right" in dpos:
                        dx = vol_cx + vol_w * 0.25
                    else:
                        dx = vol_cx

                    dtype = str(ds.get("type", "")).lower()
                    is_arched = "arch" in dtype or "pointed" in dtype or "gothic" in dtype
                    if is_arched:
                        cutter = create_arch_cutter(
                            f"vol_door_cut_{di}_{bldg_id}",
                            dw,
                            dh,
                            dh * 0.72,
                            arch_type="pointed" if ("pointed" in dtype or "gothic" in dtype) else "segmental",
                            depth=0.8,
                        )
                    else:
                        cutter = create_rect_cutter(f"vol_door_cut_{di}_{bldg_id}", dw, dh, depth=0.8)
                        cutter.location.z = dh / 2
                    cutter.location.x = dx
                    cutter.location.y = 0.01
                    boolean_cut(outer, cutter)

                    bpy.ops.mesh.primitive_cube_add(size=1)
                    d_obj = bpy.context.active_object
                    d_obj.name = f"vol_door_{di}_{bldg_id}"
                    d_obj.scale = (dw * 0.92, 0.06, dh * 0.95)
                    bpy.ops.object.transform_apply(scale=True)
                    d_obj.location = (dx, 0.04, dh * 0.48)
                    assign_material(d_obj, door_mat)
                    all_objs.append(d_obj)

            buttress_count = int(vol.get("buttress_count", 0) or 0)
            if buttress_count > 0:
                buttress_mat = create_stone_material("mat_vol_buttress", "#4E4A43")
                b_w = float(vol.get("buttress_width_m", 0.34))
                b_d = float(vol.get("buttress_depth_m", 0.45))
                b_h = float(vol.get("buttress_height_m", max(2.2, vol_h * 0.85)))
                stepped = bool(vol.get("buttress_stepped", False))
                spacing = vol_w / (buttress_count + 1)
                for bi in range(buttress_count):
                    bx = vol_cx - vol_w / 2 + spacing * (bi + 1)
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    bt = bpy.context.active_object
                    bt.name = f"vol_buttress_{bi}_{bldg_id}"
                    bt.scale = (b_w, b_d, b_h)
                    bpy.ops.object.transform_apply(scale=True)
                    bt.location = (bx, b_d / 2, b_h / 2)
                    assign_material(bt, buttress_mat)
                    all_objs.append(bt)
                    if stepped:
                        bpy.ops.mesh.primitive_cube_add(size=1)
                        bt2 = bpy.context.active_object
                        bt2.name = f"vol_buttress_step_{bi}_{bldg_id}"
                        bt2.scale = (b_w * 0.72, b_d * 0.72, b_h * 0.45)
                        bpy.ops.object.transform_apply(scale=True)
                        bt2.location = (bx, b_d * 0.65, b_h * 0.72)
                        assign_material(bt2, buttress_mat)
                        all_objs.append(bt2)

            # Optional repeated chapel gables along front face
            chapel_gable_count = int(vol.get("chapel_gable_count", 0) or 0)
            if chapel_gable_count > 0:
                cg_start = len(all_objs)
                cg_w = float(vol.get("chapel_gable_width_m", 2.6))
                cg_d = float(vol.get("chapel_gable_depth_m", 1.8))
                cg_h = float(vol.get("chapel_gable_height_m", 3.2))
                cg_y = float(vol.get("chapel_gable_y_m", cg_d / 2))
                spacing = vol_w / (chapel_gable_count + 1)
                for ci in range(chapel_gable_count):
                    cx = vol_cx - vol_w / 2 + spacing * (ci + 1)
                    # Small gable wall
                    gbm = bmesh.new()
                    v0 = gbm.verts.new((cx - cg_w / 2, cg_y, vol_h))
                    v1 = gbm.verts.new((cx + cg_w / 2, cg_y, vol_h))
                    v2 = gbm.verts.new((cx, cg_y, vol_h + cg_h))
                    gbm.faces.new([v0, v1, v2])
                    gmesh = bpy.data.meshes.new(f"chapel_gable_{ci}_{bldg_id}")
                    gbm.to_mesh(gmesh)
                    gbm.free()
                    gobj = bpy.data.objects.new(f"chapel_gable_{ci}_{bldg_id}", gmesh)
                    bpy.context.collection.objects.link(gobj)
                    mod = gobj.modifiers.new("Solidify", 'SOLIDIFY')
                    mod.thickness = 0.24
                    mod.offset = 0
                    bpy.context.view_layer.objects.active = gobj
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                    assign_material(gobj, hall_mat)
                    all_objs.append(gobj)

                    # Small roof for this chapel gable
                    rbm = bmesh.new()
                    ov = 0.12
                    vv0 = rbm.verts.new((cx - cg_w / 2 - ov, cg_y + cg_d, vol_h))
                    vv1 = rbm.verts.new((cx + cg_w / 2 + ov, cg_y + cg_d, vol_h))
                    vv2 = rbm.verts.new((cx + cg_w / 2 + ov, cg_y - ov, vol_h))
                    vv3 = rbm.verts.new((cx - cg_w / 2 - ov, cg_y - ov, vol_h))
                    vv4 = rbm.verts.new((cx, cg_y + cg_d, vol_h + cg_h * 0.75))
                    vv5 = rbm.verts.new((cx, cg_y - ov, vol_h + cg_h * 0.75))
                    rbm.faces.new([vv0, vv3, vv5, vv4])
                    rbm.faces.new([vv1, vv4, vv5, vv2])
                    rm = bpy.data.meshes.new(f"chapel_roof_{ci}_{bldg_id}")
                    rbm.to_mesh(rm)
                    rbm.free()
                    robj = bpy.data.objects.new(f"chapel_roof_{ci}_{bldg_id}", rm)
                    bpy.context.collection.objects.link(robj)
                    rmod = robj.modifiers.new("Solidify", 'SOLIDIFY')
                    rmod.thickness = 0.06
                    rmod.offset = -1
                    bpy.context.view_layer.objects.active = robj
                    bpy.ops.object.modifier_apply(modifier=rmod.name)
                    assign_material(robj, create_roof_material(f"mat_chapelroof_{bldg_id}", get_roof_hex(params)))
                    all_objs.append(robj)
                log_volume_feature("Chapel gables", cg_start)
            log_volume_feature("Volume-specific openings/details", detail_openings_start)

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
                ridge_h = (vol_w / 2) * _safe_tan(pitch)

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

        # Offset this volume after geometry creation (supports side chapel strips / annex shifts)
        if vol_y_off != 0.0 or vol_z_off != 0.0:
            for obj in all_objs[vol_start_idx:]:
                if obj:
                    obj.location.y += vol_y_off
                    obj.location.z += vol_z_off

        # --- Seam filler between adjacent volumes ---
        # When two volumes sit side by side (not stacked), add a thin strip of
        # wall material at the junction to prevent light leaks at the seam.
        if vi > 0 and not stack_with_previous:
            prev_vol = volumes[vi - 1] if isinstance(volumes[vi - 1], dict) else {}
            prev_h = sum(max(0.5, float(fh)) for fh in (prev_vol.get("floor_heights_m") or [3.5]))
            seam_h = min(vol_h, prev_h)  # height of shared wall = shorter of the two
            seam_x = vol_cx - vol_w / 2  # left edge of current volume
            seam_depth = max(vol_d, prev_vol.get("depth_m", 10.0))
            if seam_h > 0.5:
                bpy.ops.mesh.primitive_cube_add(size=1)
                seam = bpy.context.active_object
                seam.name = f"seam_filler_{vi}_{bldg_id}"
                seam.scale = (0.02, seam_depth / 2, seam_h / 2)
                bpy.ops.object.transform_apply(scale=True)
                seam.location = (seam_x, -seam_depth / 2, seam_h / 2)
                seam_mat = create_brick_material(
                    f"mat_seam_{vol_hex.lstrip('#')}", vol_hex, mortar_hex,
                    bond_pattern=mv_bond)
                assign_material(seam, seam_mat)
                all_objs.append(seam)

            # Log eave height mismatch for QA
            if abs(vol_h - prev_h) > 0.5:
                print(f"    [WARN] Eave height mismatch at seam {vi}: "
                      f"prev={prev_h:.1f}m vs current={vol_h:.1f}m (delta={abs(vol_h - prev_h):.1f}m)")

        if not stack_with_previous:
            x_cursor += vol_w
            prev_cx = vol_cx

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
def generate_st_stephens_custom(params, offset=(0, 0, 0)):
    """Custom one-off generator for St. Stephen-in-the-Fields Church.

    This bypasses generic house-form assumptions and builds a church-like
    massing directly (nave, chapel bay run, tower/spire, and rear annexes).
    """
    address = "103 Bellevue Ave"
    meta = params.get("_meta", {})
    if isinstance(meta, dict):
        address = meta.get("address", address)
    bldg_id = address.replace(" ", "_").replace(",", "").replace(".", "")
    print(f"[GENERATE CUSTOM] {address} (St. Stephen)")

    facade_hex = get_facade_hex(params)
    roof_hex = get_roof_hex(params)
    trim_hex = get_trim_hex(params)

    brick_mat = create_brick_material(f"mat_custom_brick_{facade_hex.lstrip('#')}", facade_hex, "#8A8A8A")
    roof_mat = create_roof_material(f"mat_custom_roof_{roof_hex.lstrip('#')}", roof_hex)
    stone_mat = create_stone_material(f"mat_custom_stone_{trim_hex.lstrip('#')}", trim_hex)
    glass_mat = create_glass_material(f"mat_custom_glass_{bldg_id}")
    stucco_mat = create_painted_material(f"mat_custom_stucco_{bldg_id}", "#B8826B")
    door_mat = get_or_create_material(f"mat_custom_door_{bldg_id}", colour_hex="#7B2132", roughness=0.45)

    all_objs = []

    def _obj_valid(o):
        try:
            return o is not None and o.name is not None
        except ReferenceError:
            return False

    def _gable_roof(name, width, depth, eave_z, ridge_z, cx=0.0, cy=0.0, overhang=0.25):
        bm = bmesh.new()
        hw = width / 2 + overhang
        hd = depth / 2 + overhang
        # Build in local object coordinates; position with object.location.
        v0 = bm.verts.new((-hw, -hd, eave_z))
        v1 = bm.verts.new((hw, -hd, eave_z))
        v2 = bm.verts.new((hw, hd, eave_z))
        v3 = bm.verts.new((-hw, hd, eave_z))
        v4 = bm.verts.new((0.0, -hd, ridge_z))
        v5 = bm.verts.new((0.0, hd, ridge_z))
        bm.faces.new([v0, v3, v5, v4])
        bm.faces.new([v1, v4, v5, v2])
        bm.faces.new([v2, v5, v3])
        bm.faces.new([v0, v4, v1])
        rmesh = bpy.data.meshes.new(name)
        bm.to_mesh(rmesh)
        bm.free()
        robj = bpy.data.objects.new(name, rmesh)
        bpy.context.collection.objects.link(robj)
        mod = robj.modifiers.new("Solidify", 'SOLIDIFY')
        mod.thickness = 0.08
        mod.offset = -1
        bpy.context.view_layer.objects.active = robj
        bpy.ops.object.modifier_apply(modifier=mod.name)
        robj.location.x = cx
        robj.location.y = cy
        assign_material(robj, roof_mat)
        return robj

    def _gable_end_wall(name, width, eave_z, ridge_z, cy, thickness=0.18):
        bm = bmesh.new()
        hw = width / 2
        ht = thickness / 2
        # Build in local coordinates; place at cy using object.location.
        v0 = bm.verts.new((-hw, -ht, 0.0))
        v1 = bm.verts.new((hw, -ht, 0.0))
        v2 = bm.verts.new((hw, ht, 0.0))
        v3 = bm.verts.new((-hw, ht, 0.0))
        v4 = bm.verts.new((-hw, -ht, eave_z))
        v5 = bm.verts.new((hw, -ht, eave_z))
        v6 = bm.verts.new((hw, ht, eave_z))
        v7 = bm.verts.new((-hw, ht, eave_z))
        va = bm.verts.new((0.0, -ht, ridge_z))
        vb = bm.verts.new((0.0, ht, ridge_z))

        bm.faces.new([v0, v1, v2, v3])      # bottom
        bm.faces.new([v0, v4, v5, v1])      # side
        bm.faces.new([v1, v5, v6, v2])      # side
        bm.faces.new([v2, v6, v7, v3])      # side
        bm.faces.new([v3, v7, v4, v0])      # side
        bm.faces.new([v4, va, v5])          # front triangle
        bm.faces.new([v7, v6, vb])          # back triangle
        bm.faces.new([v4, v7, vb, va])      # top left slope
        bm.faces.new([v5, va, vb, v6])      # top right slope

        m = bpy.data.meshes.new(name)
        bm.to_mesh(m)
        bm.free()
        obj = bpy.data.objects.new(name, m)
        bpy.context.collection.objects.link(obj)
        obj.location.y = cy
        assign_material(obj, brick_mat)
        return obj

    def _box_center(name, width, depth, height, cx, cy, bz=0.0):
        """Create box using center-XY and bottom-Z coordinates."""
        return create_box(name, width, depth, height, location=(cx, cy + depth / 2, bz))

    def _polygon_prism(name, points_xy, z0, z1, material):
        """Create vertical prism from 2D footprint points."""
        bm = bmesh.new()
        bottom = [bm.verts.new((x, y, z0)) for x, y in points_xy]
        top = [bm.verts.new((x, y, z1)) for x, y in points_xy]
        bm.faces.new(bottom)
        bm.faces.new(list(reversed(top)))
        n = len(points_xy)
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new([bottom[i], bottom[j], top[j], top[i]])
        m = bpy.data.meshes.new(name)
        bm.to_mesh(m)
        bm.free()
        obj = bpy.data.objects.new(name, m)
        bpy.context.collection.objects.link(obj)
        assign_material(obj, material)
        return obj

    # Main nave (GIS-calibrated envelope)
    use_footprint_base = False
    if use_footprint_base:
        # GID 411057 footprint (SRID 2952) recentered to centroid, in metres.
        footprint_pts = [
            (1.844, 10.083), (1.414, 11.709), (5.143, 12.696), (5.284, 12.162),
            (12.532, 14.081), (14.067, 8.281), (16.762, 8.995), (19.025, 0.446),
            (20.424, -4.589), (17.742, -5.349), (10.466, -7.276), (10.339, -6.796),
            (7.121, -7.668), (7.156, -7.800), (-14.591, -13.556), (-15.321, -10.797),
            (-15.942, -10.961), (-16.757, -7.882), (-17.624, -8.112), (-19.174, -2.255),
            (-18.382, -2.046), (-19.223, 1.136), (-18.838, 1.238), (-19.671, 4.389),
        ]
        base = _polygon_prism(f"custom_footprint_base_{bldg_id}", footprint_pts, 0.0, 8.7, brick_mat)
        all_objs.append(base)

    nave_w = 13.6
    nave_d = 31.0
    nave_eave = 8.0
    nave_ridge = 13.4
    nave = _box_center(f"custom_nave_{bldg_id}", nave_w, nave_d, nave_eave, 0, 0, 0)
    assign_material(nave, brick_mat)
    all_objs.append(nave)
    nave_roof = _gable_roof(f"custom_nave_roof_{bldg_id}", nave_w, nave_d, nave_eave, nave_ridge, 0, 0, overhang=0.18)
    all_objs.append(nave_roof)
    nave_front_gable = _gable_end_wall(
        f"custom_nave_front_gable_{bldg_id}",
        nave_w - 0.25,
        nave_eave,
        nave_ridge - 0.15,
        nave_d / 2 - 0.12,
        thickness=0.22,
    )
    all_objs.append(nave_front_gable)
    nave_rear_gable = _gable_end_wall(
        f"custom_nave_rear_gable_{bldg_id}",
        nave_w - 0.25,
        nave_eave,
        nave_ridge - 0.15,
        -nave_d / 2 + 0.12,
        thickness=0.22,
    )
    all_objs.append(nave_rear_gable)

    # F