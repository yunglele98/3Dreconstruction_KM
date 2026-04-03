#!/bin/bash
# Wait for collision to finish, then run FBX export batch
echo "Waiting for Blender collision batch to finish..."
while powershell.exe -Command "Get-Process blender -ErrorAction SilentlyContinue" 2>/dev/null | grep -q blender; do
    sleep 30
done
echo "Collision done. Starting FBX export batch..."
cd C:/Users/liam1/blender_buildings
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background --python scripts/batch_export_unreal.py -- --source-dir outputs/full/ --skip-existing 2>&1 | tee outputs/fbx_export_batch.log
echo "FBX export batch complete."
