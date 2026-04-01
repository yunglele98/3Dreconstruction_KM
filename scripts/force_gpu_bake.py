import bpy

def enable_gpu():
    print("Enabling GPU (CUDA/OPTIX)...")
    prefs = bpy.context.preferences
    cprefs = prefs.addons['cycles'].preferences
    
    # Attempt to use OPTIX (best for RTX 2080 Super)
    try:
        cprefs.compute_device_type = 'OPTIX'
    except:
        cprefs.compute_device_type = 'CUDA'
        
    cprefs.get_devices()
    for device in cprefs.devices:
        if "RTX 2080" in device.name or device.type == 'OPTIX':
            device.use = True
            print(f"Using Device: {device.name}")
        else:
            device.use = False
            
    bpy.context.scene.cycles.device = 'GPU'
    print(f"Cycles Device set to: {bpy.context.scene.cycles.device}")

# This can be imported or run directly
if __name__ == "__main__":
    enable_gpu()
