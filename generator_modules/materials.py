"""Blender material creation functions for the Kensington building generator.

Procedural Principled BSDF materials: brick, wood, stone, metal roofing,
glass, painted surfaces, canvas. All require bpy.

Extracted from generate_building.py.
"""

import bpy
from generator_modules.colours import hex_to_rgb


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



def apply_weathering_layer(mat, condition="fair", age_years=80):
    """Add procedural weathering effects to an existing material.

    Adds condition-driven surface degradation:
    - Edge wear (chipped paint, exposed substrate at corners/edges)
    - Water stain streaks (vertical dark streaks from rain runoff)
    - Dirt accumulation (darker values in crevices and lower zones)
    - Surface roughness variation (worn areas are smoother)

    Args:
        mat: Existing Blender material to weatherize.
        condition: "good", "fair", or "poor" — controls intensity.
        age_years: Approximate building age — scales moss/patina.

    Returns the modified material.
    """
    if not mat or not mat.node_tree:
        return mat

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = _get_bsdf(mat)
    if not bsdf:
        return mat

    # Intensity multipliers by condition
    intensity = {"good": 0.3, "fair": 0.6, "poor": 1.0}.get(
        (condition or "fair").lower(), 0.6
    )
    age_factor = min(1.0, age_years / 120.0)

    # Get current base colour connection
    base_color_link = None
    for link in links:
        if link.to_socket == bsdf.inputs["Base Color"]:
            base_color_link = link
            break

    if not base_color_link:
        return mat

    original_color_output = base_color_link.from_socket
    links.remove(base_color_link)

    # --- Water stain streaks (vertical) ---
    stain_noise = nodes.new('ShaderNodeTexNoise')
    stain_noise.location = (-600, 400)
    stain_noise.inputs["Scale"].default_value = 3.0
    stain_noise.inputs["Detail"].default_value = 8.0
    stain_noise.inputs["Roughness"].default_value = 0.7
    stain_noise.inputs["Distortion"].default_value = 2.0

    # Stretch vertically for streak effect
    stain_mapping = nodes.new('ShaderNodeMapping')
    stain_mapping.location = (-750, 400)
    stain_mapping.inputs["Scale"].default_value = (0.3, 1.0, 8.0)

    stain_coord = nodes.new('ShaderNodeTexCoord')
    stain_coord.location = (-900, 400)
    links.new(stain_coord.outputs["Generated"], stain_mapping.inputs["Vector"])
    links.new(stain_mapping.outputs["Vector"], stain_noise.inputs["Vector"])

    # Ramp to make streaks darker
    stain_ramp = nodes.new('ShaderNodeValToRGB')
    stain_ramp.location = (-400, 400)
    stain_ramp.color_ramp.elements[0].position = 0.4
    stain_ramp.color_ramp.elements[0].color = (0.15, 0.13, 0.12, 1.0)
    stain_ramp.color_ramp.elements[1].position = 0.6
    stain_ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    links.new(stain_noise.outputs["Fac"], stain_ramp.inputs["Fac"])

    # Mix stains with original colour
    stain_mix = nodes.new('ShaderNodeMixRGB')
    stain_mix.location = (-200, 300)
    stain_mix.blend_type = 'MULTIPLY'
    stain_mix.inputs["Fac"].default_value = 0.15 * intensity
    links.new(original_color_output, stain_mix.inputs["Color1"])
    links.new(stain_ramp.outputs["Color"], stain_mix.inputs["Color2"])

    # --- Dirt accumulation (gravity-driven, lower areas darker) ---
    dirt_coord = nodes.new('ShaderNodeTexCoord')
    dirt_coord.location = (-600, 100)

    dirt_sep = nodes.new('ShaderNodeSeparateXYZ')
    dirt_sep.location = (-450, 100)
    links.new(dirt_coord.outputs["Generated"], dirt_sep.inputs["Vector"])

    # Gradient: more dirt at bottom (Z=0), less at top
    dirt_ramp = nodes.new('ShaderNodeValToRGB')
    dirt_ramp.location = (-300, 100)
    dirt_ramp.color_ramp.elements[0].position = 0.0
    dirt_ramp.color_ramp.elements[0].color = (0.3, 0.28, 0.25, 1.0)
    dirt_ramp.color_ramp.elements[1].position = 0.3
    dirt_ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    links.new(dirt_sep.outputs["Z"], dirt_ramp.inputs["Fac"])

    # Add noise to break up the gradient
    dirt_noise = nodes.new('ShaderNodeTexNoise')
    dirt_noise.location = (-450, 0)
    dirt_noise.inputs["Scale"].default_value = 12.0
    dirt_noise.inputs["Detail"].default_value = 4.0

    dirt_mix_noise = nodes.new('ShaderNodeMixRGB')
    dirt_mix_noise.location = (-200, 100)
    dirt_mix_noise.blend_type = 'MULTIPLY'
    dirt_mix_noise.inputs["Fac"].default_value = 0.5
    links.new(dirt_ramp.outputs["Color"], dirt_mix_noise.inputs["Color1"])
    links.new(dirt_noise.outputs["Color"], dirt_mix_noise.inputs["Color2"])

    # Apply dirt to stained colour
    dirt_apply = nodes.new('ShaderNodeMixRGB')
    dirt_apply.location = (0, 200)
    dirt_apply.blend_type = 'MULTIPLY'
    dirt_apply.inputs["Fac"].default_value = 0.12 * intensity
    links.new(stain_mix.outputs["Color"], dirt_apply.inputs["Color1"])
    links.new(dirt_mix_noise.outputs["Color"], dirt_apply.inputs["Color2"])

    # --- Surface roughness variation ---
    rough_noise = nodes.new('ShaderNodeTexNoise')
    rough_noise.location = (-400, -200)
    rough_noise.inputs["Scale"].default_value = 15.0
    rough_noise.inputs["Detail"].default_value = 5.0

    rough_ramp = nodes.new('ShaderNodeValToRGB')
    rough_ramp.location = (-200, -200)
    # Weathered = more roughness variation
    base_rough = 0.85
    rough_ramp.color_ramp.elements[0].position = 0.3
    rough_ramp.color_ramp.elements[0].color = (base_rough - 0.1, 0, 0, 1)
    rough_ramp.color_ramp.elements[1].position = 0.7
    rough_ramp.color_ramp.elements[1].color = (base_rough + 0.1 * intensity, 0, 0, 1)
    links.new(rough_noise.outputs["Fac"], rough_ramp.inputs["Fac"])

    # Connect final colour and roughness
    links.new(dirt_apply.outputs["Color"], bsdf.inputs["Base Color"])

    return mat


def apply_moss_layer(mat, coverage=0.1):
    """Add moss/lichen growth to a material (for poor-condition old buildings).

    Adds green organic growth concentrated in crevices and north-facing
    areas (lower parts of the wall, mortar joints).

    Args:
        mat: Existing Blender material.
        coverage: 0.0-1.0 moss coverage fraction.
    """
    if not mat or not mat.node_tree or coverage <= 0:
        return mat

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = _get_bsdf(mat)
    if not bsdf:
        return mat

    # Get current base colour
    base_link = None
    for link in links:
        if link.to_socket == bsdf.inputs["Base Color"]:
            base_link = link
            break
    if not base_link:
        return mat

    original_output = base_link.from_socket
    links.remove(base_link)

    # Moss colour
    moss_color = nodes.new('ShaderNodeRGB')
    moss_color.location = (-400, 500)
    moss_color.outputs["Color"].default_value = (0.18, 0.28, 0.08, 1.0)

    # Moss distribution: noise + gravity (more at bottom and in crevices)
    moss_noise = nodes.new('ShaderNodeTexNoise')
    moss_noise.location = (-600, 500)
    moss_noise.inputs["Scale"].default_value = 8.0
    moss_noise.inputs["Detail"].default_value = 6.0
    moss_noise.inputs["Roughness"].default_value = 0.8

    moss_ramp = nodes.new('ShaderNodeValToRGB')
    moss_ramp.location = (-400, 600)
    # Sharp threshold for patchy moss
    threshold = 1.0 - coverage
    moss_ramp.color_ramp.elements[0].position = threshold - 0.05
    moss_ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    moss_ramp.color_ramp.elements[1].position = threshold + 0.05
    moss_ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
    links.new(moss_noise.outputs["Fac"], moss_ramp.inputs["Fac"])

    # Mix moss with base
    moss_mix = nodes.new('ShaderNodeMixRGB')
    moss_mix.location = (-200, 500)
    links.new(moss_ramp.outputs["Color"], moss_mix.inputs["Fac"])
    links.new(original_output, moss_mix.inputs["Color1"])
    links.new(moss_color.outputs["Color"], moss_mix.inputs["Color2"])

    links.new(moss_mix.outputs["Color"], bsdf.inputs["Base Color"])

    return mat


def assign_material(obj, mat):
    """Assign a material to an object."""
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

