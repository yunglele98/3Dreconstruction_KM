#!/bin/bash
# Safe batch FBX export — one Blender process per building, skips failures
# Usage: bash scripts/batch_export_safe.sh [limit]

cd "$(dirname "$0")/.."
LIMIT=${1:-50}
COUNT=0
DONE=0
SKIP=0

while IFS= read -r stem; do
    if [ -f "outputs/exports/$stem/${stem}.fbx" ]; then
        SKIP=$((SKIP + 1))
        continue
    fi

    COUNT=$((COUNT + 1))
    if [ $COUNT -gt $LIMIT ]; then
        break
    fi

    ADDR=$(echo "$stem" | sed 's/_/ /g')
    echo "[$COUNT/$LIMIT] $ADDR"
    blender --background --python scripts/export_building_fbx.py -- --address "$ADDR" 2>&1 | grep -E "^(Export complete|  FBX|Error)" || true

done < outputs/export_queue.txt

echo ""
echo "Done: $COUNT attempted, $SKIP skipped (already exported)"
