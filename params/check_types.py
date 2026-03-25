import json
import os

files = sorted([f for f in os.listdir('.') if f.endswith('.json')])
string_confidence = []
bool_types = []
type_issues = []

for fname in files:
    try:
        with open(fname) as f:
            data = json.load(f)
        
        obs = data.get('photo_observations', {})
        if not obs:
            continue
        
        # Check confidence type
        confidence = obs.get('confidence')
        if confidence is not None:
            if isinstance(confidence, str):
                string_confidence.append((fname, confidence))
            elif not isinstance(confidence, (int, float)):
                type_issues.append((fname, f"confidence: {type(confidence).__name__}"))
        
        # Check boolean fields
        for bool_field in ['quoins', 'pilasters', 'string_course', 'decorative_lintels', 'porch_present', 'has_storefront_observed', 'graffiti', 'matches_hcd_typology', 'fire_escape']:
            if bool_field in obs:
                val = obs[bool_field]
                if val is not None and not isinstance(val, bool):
                    type_issues.append((fname, f"{bool_field}: {type(val).__name__} = {val}"))
        
        # Check windows_per_floor type
        wpf = obs.get('windows_per_floor')
        if wpf is not None and not isinstance(wpf, list):
            type_issues.append((fname, f"windows_per_floor: {type(wpf).__name__}"))
        
        # Check that observed fields are strings not arrays
        for obs_field in ['facade_colour_observed', 'facade_material_observed', 'condition', 'window_type']:
            if obs_field in obs:
                val = obs[obs_field]
                if val is not None and isinstance(val, list):
                    type_issues.append((fname, f"{obs_field}: list instead of string"))
        
    except Exception as e:
        pass

print(f"String confidence values (should be numeric): {len(string_confidence)}")
for fname, val in string_confidence[:10]:
    print(f"  - {fname}: \"{val}\"")

print(f"\nOther type issues: {len(type_issues)}")
for fname, issue in type_issues[:20]:
    print(f"  - {fname}: {issue}")
