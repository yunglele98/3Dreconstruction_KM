import bpy

# List available render engines
print("=== Render Engine Check ===")
print(f"Current engine: {bpy.context.scene.render.engine}")

# Try setting each engine
for engine in ["CYCLES", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"]:
    try:
        bpy.context.scene.render.engine = engine
        print(f"  {engine}: AVAILABLE")
    except Exception as e:
        print(f"  {engine}: NOT AVAILABLE ({e})")

# Check GPU compute
try:
    prefs = bpy.context.preferences.addons.get("cycles")
    if prefs:
        cprefs = prefs.preferences
        print(f"Cycles compute device: {cprefs.compute_device_type}")
        for dev in cprefs.devices:
            print(f"  Device: {dev.name} ({dev.type}) - {'ENABLED' if dev.use else 'disabled'}")
    else:
        print("Cycles addon not found in preferences")
except Exception as e:
    print(f"Could not check Cycles GPU: {e}")

# Check EEVEE capabilities
try:
    bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
    print(f"EEVEE shadows: {bpy.context.scene.eevee.use_shadows}")
except:
    try:
        bpy.context.scene.render.engine = "BLENDER_EEVEE"
        print("Using legacy EEVEE")
    except:
        print("No EEVEE available")
