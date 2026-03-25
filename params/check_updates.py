import json
import os

files = sorted([f for f in os.listdir('.') if f.endswith('.json')])
count_with_obs = 0
count_facade_obs = 0  # has facade_colour_observed
count_no_obs_fields = 0  # has photo_obs but no _observed fields
count_minimal = 0  # has photo_obs but only notes/confidence
count_with_batch_update = 0
count_with_nighttime = 0

for fname in files:
    try:
        with open(fname) as f:
            data = json.load(f)
        
        obs = data.get('photo_observations', {})
        if not obs:
            continue
        
        count_with_obs += 1
        
        # Check for _observed fields (schema 1 - detailed observations)
        has_facade_obs = 'facade_colour_observed' in obs
        if has_facade_obs:
            count_facade_obs += 1
        
        # Check for batch_NNN_update nested objects
        has_batch_update = any(k.startswith('batch_') and isinstance(obs.get(k), dict) for k in obs)
        if has_batch_update:
            count_with_batch_update += 1
        
        # Check for nighttime_observations
        if 'nighttime_observations' in obs:
            count_with_nighttime += 1
        
        # Check if minimal (only notes, confidence, metadata)
        minimal_keys = {'notes', 'confidence', 'agent', 'timestamp', '_meta', 'batch', 'photo', 'photo_time', 'source_photo', 'overall_style', 'source_image', 'source_image_orientation', 'lighting', 'photo_time', 'photo_notes', 'photo_conditions', 'observed_by'}
        obs_keys = set(obs.keys())
        actual_keys = obs_keys - minimal_keys
        if not actual_keys and obs_keys:
            count_minimal += 1
        
    except:
        pass

print(f"Total files with photo_observations: {count_with_obs}")
print(f"  - With facade_colour_observed (detailed schema): {count_facade_obs}")
print(f"  - With batch_NNN_update sub-objects: {count_with_batch_update}")
print(f"  - With nighttime_observations: {count_with_nighttime}")
print(f"  - With minimal data (notes/confidence only): {count_minimal}")
print(f"  - Unaccounted for (other schema patterns): {count_with_obs - count_facade_obs - count_with_batch_update - count_minimal}")
