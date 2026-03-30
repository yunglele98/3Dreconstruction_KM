#!/bin/bash
cd "$(dirname "$0")/.."

echo "Waiting for current Blender processes to finish..."
while [ $(tasklist 2>/dev/null | grep -c -i blender) -gt 2 ]; do sleep 10; done

echo "Generating College St demo..."
blender --background --python generate_building.py -- --params params/ --match "College" --output-dir outputs/demos/

echo "Generating Dundas St demo..."
blender --background --python generate_building.py -- --params params/ --match "Dundas" --output-dir outputs/demos/

echo "Generating Bathurst St demo..."
blender --background --python generate_building.py -- --params params/ --match "Bathurst" --output-dir outputs/demos/

echo "Generating Oxford St demo..."  
blender --background --python generate_building.py -- --params params/ --match "Oxford" --output-dir outputs/demos/

echo "Generating Wales Ave demo..."
blender --background --python generate_building.py -- --params params/ --match "Wales" --output-dir outputs/demos/

echo "All demos complete"
