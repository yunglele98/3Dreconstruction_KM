import json
import os

files = sorted([f for f in os.listdir('.') if f.endswith('.json')])
count_condition_updated = 0
count_condition_not_updated = 0
count_facade_colour_updated = 0
count_facade_colour_not_updated = 0
count_windows_updated = 0
count_windows_not_updated = 0
count_facade_material_updated = 0
count_facade_material_not_updated = 0

for fname in files:
    try:
        with open(fname) as f:
            data = json.load(f)
        
        obs = data.get('photo_observations', {})
        if not obs:
            continue
        
        # Check condition field
        top_condition = data.get('condition')
        obs_condition = obs.get('condition')
        if obs_condition is not None:
            if obs_condition == top_condition:
                # Check if it was actually updated or just copied
                if 'condition_notes' in obs or 'facade_condition_notes' in obs:
                    count_condition_updated += 1
                else:
                    count_condition_not_updated += 1
            else:
                count_condition_updated += 1
        
        # Check facade_colour
        top_facade_colour = data.get('facade_colour')
        obs_facade_colour = obs.get('facade_colour_observed')
        if obs_facade_colour is not None and obs_facade_colour != top_facade_colour:
            count_facade_colour_updated += 1
        elif obs_facade_colour is not None:
            count_facade_colour_not_updated += 1
        
        # Check windows_per_floor
        top_windows = data.get('windows_per_floor')
        obs_windows = obs.get('windows_per_floor')
        if obs_windows is not None and obs_windows != top_windows:
            count_windows_updated += 1
        elif obs_windows is not None:
            count_windows_not_updated += 1
        
        # Check facade_material
        top_material = data.get('facade_material')
        obs_material = obs.get('facade_material_observed')
        if obs_material is not None and obs_material != top_material:
            count_facade_material_updated += 1
        elif obs_material is not None:
            count_facade_material_not_updated += 1
        
    except:
        pass

print("Condition field updates:")
print(f"  - Updated (different from top-level): {count_condition_updated}")
print(f"  - Not updated (same as top-level): {count_condition_not_updated}")
print("\nFacade colour updates:")
print(f"  - Updated (facade_colour_observed differs): {count_facade_colour_updated}")
print(f"  - Not updated (same as top-level): {count_facade_colour_not_updated}")
print("\nWindows per floor updates:")
print(f"  - Updated (differs from top-level): {count_windows_updated}")
print(f"  - Not updated (same as top-level): {count_windows_not_updated}")
print("\nFacade material updates:")
print(f"  - Updated (differs from top-level): {count_facade_material_updated}")
print(f"  - Not updated (same as top-level): {count_facade_material_not_updated}")
