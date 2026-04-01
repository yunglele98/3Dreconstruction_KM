import bpy

def check_gpu():
    print("--- Blender GPU Audit ---")
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    cycles = scene.cycles
    
    print(f"Configured Device: {cycles.device}")
    
    # Check available devices
    prefs = bpy.context.preferences
    cprefs = prefs.addons['cycles'].preferences
    
    print("\nComputing Devices:")
    for device_type in cprefs.get_device_types(bpy.context):
        print(f" Type: {device_type[0]}")
        cprefs.compute_device_type = device_type[0]
        for device in cprefs.devices:
            print(f"  - Device: {device.name} (Type: {device.type}, Used: {device.use})")

if __name__ == "__main__":
    check_gpu()
