import json
import os
from collections import defaultdict

files = sorted([f for f in os.listdir('.') if f.endswith('.json')])

# Collect all key patterns in photo_observations
schema_patterns = defaultdict(int)
agent_distribution = defaultdict(int)
lighting_values = defaultdict(int)

for fname in files:
    try:
        with open(fname) as f:
            data = json.load(f)
        
        obs = data.get('photo_observations', {})
        if not obs:
            continue
        
        # Get the key structure
        keys = frozenset(obs.keys())
        schema_patterns[keys] += 1
        
        # Track agents
        agent = obs.get('agent') or data.get('_meta', {}).get('agent')
        if agent:
            agent_distribution[agent] += 1
        
        # Track lighting
        lighting = obs.get('lighting')
        if lighting:
            lighting_values[lighting] += 1
        
    except:
        pass

print("=== SCHEMA KEY PATTERN DISTRIBUTION ===")
for pattern, count in sorted(schema_patterns.items(), key=lambda x: -x[1])[:15]:
    keys_list = sorted(list(pattern))[:10]  # Show first 10 keys
    print(f"\n{count} files with keys: {keys_list}...")

print("\n\n=== AGENT DISTRIBUTION ===")
for agent, count in sorted(agent_distribution.items(), key=lambda x: -x[1])[:10]:
    print(f"{agent}: {count}")

print("\n\n=== LIGHTING VALUES ===")
for lighting, count in sorted(lighting_values.items(), key=lambda x: -x[1]):
    print(f"{lighting}: {count}")
