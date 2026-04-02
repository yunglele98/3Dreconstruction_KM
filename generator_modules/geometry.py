"""Core geometry helpers for the Kensington building generator.

create_box, boolean_cut, arch/rect cutters, mesh cleanup.
All require bpy/bmesh.

Extracted from generate_building.py.
"""

import bpy
import bmesh
import math


def _safe_tan(degrees, lo=5.0, hi=85.0):
    """Return tan(degrees) with the angle clamped to [lo, hi] to avoid infinity."""
    clamped = max(lo, min(hi, float(degrees)))
    return math.tan(math.radians(clamped))


def _clamp_positive(value, default, minimum=0.5):
    """Return *value* if it is a positive number >= *minimum*, else *default*."""
    try:
        v = float(value)
        return v if v >= minimum else default
    except (TypeError, ValueError):
        return default


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


