# Detail Revision Batches — Agent Dispatch

30 parallel agent tasks for adding more detail to `scripts/demo_footprint_based.py`.
Each batch is independent — agents can work in parallel without conflicts.

**Rules for all agents:**
- Edit ONLY `scripts/demo_footprint_based.py`
- Add code BEFORE `def main():` (inside `create_building_from_footprint`)
- Or add to `main()` for environment features (after existing sections)
- Use `mat(name, hex, roughness)` for materials
- Use `link(obj, collection)` for all objects
- Use `scene_transform(x, y)` for GIS coordinates in `main()`
- Don't refactor or modify existing code
- Test with: `python -c "import ast; ast.parse(open('scripts/demo_footprint_based.py').read()); print('OK')"`

---

## Batch 1: Roof Details
Add to `create_building_from_footprint`, before `def main():`
- Roof snow accumulation (white patches on roof slopes, 40%)
- Roof moss/lichen patches (green spots on old shingle roofs, 20%)
- Roof edge ice dam (white strip at eave, 30% — March)
- Solar panels (flat rectangles on south-facing roof slope, 5%)
- Roof access hatch (small raised box on flat roofs, 30%)

## Batch 2: Window Refinements
Add to `create_building_from_footprint`, near existing window code
- Storm windows (outer glass panel, slightly larger than window, 40%)
- Window air gap / reveal depth (darker recess around each window frame)
- Frosted/privacy glass on bathroom windows (opaque white, 20% of side windows)
- Stained glass accent pane (small coloured panel in transom, 10%)
- Window screen (mesh panel, slightly different shade, 30%)

## Batch 3: Door & Entry Details
Add to `create_building_from_footprint`, near door code
- Door knocker (small dark circle on door, 30%)
- Door mail slot (horizontal rectangle on door, 40%)
- Door sidelight (narrow glass panel beside door, 20%)
- Door canopy / hood (small peaked roof over door, 25%)
- Welcome mat (small dark rectangle at threshold, 40%)

## Batch 4: Porch & Balcony Refinements
Add to `create_building_from_footprint`
- Porch ceiling (flat panel under porch roof, painted colour)
- Porch swing (hanging bench, 10%)
- Balcony planter boxes (on balcony railing, 30%)
- Wrought iron balcony brackets (decorative supports, 20%)
- Enclosed glass porch / vestibule (from photo_observations.alterations_visible, 15%)

## Batch 5: Commercial Ground Floor
Add to `create_building_from_footprint`, near storefront code
- Neon "OPEN" sign (small glowing rectangle in window, 40% of storefronts)
- Hours of operation sign (small white rectangle on door, 60%)
- Menu board (blackboard outside restaurants, 30% of food businesses)
- Wheelchair ramp at entrance (concrete slope, 15%)
- Entrance mat / carpet (dark rectangle at door, 50%)

## Batch 6: Signage Details
Add to `create_building_from_footprint`
- Projecting bracket sign with chains (hanging sign, 20%)
- Illuminated box sign (backlit rectangular box, 25%)
- Vinyl banner between posts (temporary promotional, 10%)
- Window lettering (gold/white text on glass, 40% of commercial)
- Chalkboard specials sign (small A-frame near door, 30%)

## Batch 7: Wall Surface Details
Add to `create_building_from_footprint`
- Tuck-pointing lines (thin mortar accent bands on brick, 30%)
- Painted address numbers on wall (large numbers, 20%)
- Security alarm box (small white box with red light, 30%)
- Exterior outlet/receptacle (small box on wall, 25%)
- Hose bib / spigot (small projection at ground level, 40%)

## Batch 8: Roof Mechanical
Add to `create_building_from_footprint`
- Plumbing vent stack (thin pipe through roof, 80%)
- Furnace exhaust flue (metal pipe, 60%)
- Roof-mounted HVAC unit (large box on flat roofs, 15%)
- Roof drain scupper (opening in parapet for flat roof drainage, 25%)
- Chimney cap / rain cap (wire mesh on chimney top, 40%)

## Batch 9: Landscape & Yard
Add to `create_building_from_footprint`
- Front yard tree (bare deciduous, 30%)
- Garden bed border (low stone/brick edging, 25%)
- Birdbath / garden ornament (small pedestal, 10%)
- Compost bin (wooden box at rear, 15%)
- Outdoor BBQ / grill (small dark box at rear, 10%)

## Batch 10: Street Infrastructure
Add to `main()`, after existing environment sections
- Fire call box (red pillar at intersections)
- Utility vault cover (large rectangular cover, different from manhole)
- Storm drain grate (long narrow grate at curb)
- Street name painted on curb (white text)
- No parking signs (red/white, on posts along roads)

## Batch 11: Traffic Infrastructure
Add to `main()`
- Traffic signal poles (at major intersections — Dundas/Augusta, etc.)
- Pedestrian crossing signals (walk/don't walk boxes)
- Turn restriction signs
- One-way signs (from photo — red circle with white bar)
- Speed limit signs (30 km/h residential)

## Batch 12: Transit Infrastructure
Add to `main()`
- TTC bus shelters (glass + metal frame, from College St photo)
- Transit stop signs (TTC red/white circular signs)
- Fare payment machines (grey boxes at stops)
- Transit shelter benches
- Route map display (under shelter glass)

## Batch 13: Park Amenities
Add to `main()`, in park section
- Basketball half-court (concrete pad with hoop)
- Splash pad / water play area (concrete with jets)
- Community garden plots (raised beds)
- Dog off-leash area (fenced section)
- Picnic tables (wooden, 4-6 in park)

## Batch 14: Alley Details
Add to `main()`
- Alley dumpster enclosures (wooden screen around dumpsters)
- Loading zone markings (yellow curb paint in alleys)
- Back gate / yard gate (wooden or metal gate in fence)
- Alley speed bump (raised asphalt)
- Graffiti wall sections (coloured panels on alley walls)

## Batch 15: Utility Infrastructure
Add to `main()`
- Transformer pad (green metal box on concrete pad)
- Cable junction boxes (small grey boxes on poles)
- Fire hydrant markers (small reflective posts near hydrants)
- Utility pole guy wires (diagonal support cables)
- Utility pole transformers (cylindrical on pole top)

## Batch 16: Seasonal Details (March)
Add to `create_building_from_footprint`
- Salt stains on walkways (white patches on concrete)
- Dead leaf accumulation (brown patches in corners)
- Bare vine/ivy on wall (thin branching lines on brick)
- Frozen puddle (reflective white patches)
- Muddy tire tracks (dark strips on grass near driveways)

## Batch 17: Vehicle Details
Add to `main()`
- Delivery trucks (larger than cars, white/brown boxes)
- Motorcycles (smaller, parked between cars)
- Cargo bikes (long frame, near storefronts)
- Electric scooters (small, scattered on sidewalks)
- Shopping carts (stray, near commercial areas)

## Batch 18: Accessibility Features
Add to both `create_building_from_footprint` and `main()`
- Tactile paving (textured yellow strips at crosswalks)
- Accessible parking signs (blue wheelchair signs)
- Ramp handrails (metal rails on wheelchair ramps)
- Automatic door buttons (small box beside commercial doors)
- Curb cut warning strips (truncated domes at curb ramps)

## Batch 19: Heritage-Specific Details
Add to `create_building_from_footprint`
- Date stone (carved stone with construction year, from HCD data)
- Heritage designation plaque (specific to Toronto)
- Original hardware (period-appropriate door handles, knockers)
- Decorative iron cresting (on flat roof parapets)
- Rosette / medallion ornament (circular decorative element on facade)

## Batch 20: Night/Lighting Details
Add to both
- Facade uplighting (ground-level light washing up building face)
- Shop window display lighting (warm glow from storefront)
- Under-eave LED strip (modern accent lighting)
- Neon sign tubes (coloured tube shapes, commercial)
- Motion sensor light (small box with sensor, on residential)

## Batch 21: Fence & Boundary Details
Add to both
- Wrought iron gate with arch (at front walkway)
- Stone/concrete fence pillars (at property corners)
- Chain link fence with privacy slats (at rear)
- Wooden picket fence (white, traditional style)
- Metal mesh fence panels (modern, at commercial)

## Batch 22: Garden & Planting Details
Add to both
- Window herb garden (small pots on windowsill)
- Hanging plant bracket (metal arm with pot hook)
- Mulch bed around trees (dark circle at tree base)
- Dead ornamental grass (tan/brown clumps)
- Empty raised planter (concrete or wooden box, dormant)

## Batch 23: Waste Management
Add to `main()`
- City waste collection calendar signs
- Compost bags (brown paper bags at curb)
- Recycling overflow (boxes beside blue bins)
- Commercial waste containers (large wheeled bins)
- Dog waste bag dispenser (at lamp posts)

## Batch 24: Building Services
Add to `create_building_from_footprint`
- Gas meter (small box on wall near foundation)
- Water meter pit cover (small round cover in front yard)
- Cable TV junction (small box on wall)
- Intercom buzzer panel (multi-button panel at apartment entrance)
- Security keypad (small box beside door)

## Batch 25: Architectural Ornament
Add to `create_building_from_footprint`
- Sunburst / fan motif above door (half-circle decorative)
- Egg and dart moulding (under cornice, heritage buildings)
- Rope/cable moulding (twisted decorative band)
- Acroterion (corner ornament on parapet)
- Dentil band at floor lines (small repeating blocks)

## Batch 26: Material Transitions
Add to `create_building_from_footprint`
- Stone/brick transition band (where materials change)
- Flashing at material change (metal strip)
- Colour change line (different paint above/below)
- Exposed foundation stone (visible rough stone at base)
- Concrete block infill (grey blocks replacing original material)

## Batch 27: Modern Additions
Add to `create_building_from_footprint`
- Rooftop patio / green roof (raised planting on flat roof, 5%)
- Solar hot water panel (flat panel, 3%)
- EV charger (small box on wall or post, 5%)
- Modern glass addition (contemporary rear extension, 5%)
- Smart doorbell camera (small circle beside door, 20%)

## Batch 28: Street Art & Culture
Add to `main()`
- Large-scale murals on blank walls (from Kensington photos)
- Mosaic tile art (on walls or posts)
- Painted utility box art (coloured transformer boxes)
- Community message board (cork/wood board with flyers)
- Street art sticker accumulation (on lamp posts, signs)

## Batch 29: Seasonal Commerce
Add to `create_building_from_footprint`
- Sidewalk sale clothing racks (outside vintage shops)
- Fruit/vegetable display tables (Kensington specialty)
- Ice cream freezer (small white chest outside convenience)
- Flower bucket display (buckets of flowers at florists)
- Newspaper/magazine rack (wire rack at convenience stores)

## Batch 30: Final Polish
Add to both
- Shadow-catching ground plane refinement (better ground texture zones)
- Ambient occlusion strips (dark bands at wall-ground junction)
- Grime/weathering strips (dark patches at drip lines below windows)
- Rust stains from metal fixtures (orange streaks below iron hardware)
- Bird deterrent spikes (thin strips on ledges and signs)

---

## Dispatch Command (No Claude)

Claude can be disabled when quota is limited. Use Codex/Gemini managers and Ollama workers only.

### 1) Disable Claude in config

- In `agent_ops/state/agents.json`, set `claude-1` to:
  - `"status": "disabled"`
  - `"capacity": 0`
- In `agent_ops/state/control_plane.json`, remove `"claude-1"` from `manager_agents`.

### 2) Start the live stack

```powershell
cd C:\Users\liam1\blender_buildings
.\scripts\start_agent_ops.ps1 -RunRoute -RunControlPlane -ExecuteOllama -StartControlLoop -ControlLoopSec 120
```

### 3) Add batches as backlog tasks

Create one task JSON per batch in `agent_ops/10_backlog/` with:
- `task_id`, `title`, `description`
- `skills` (example: `["python","blender","qa"]`)
- `write_scope` (keep narrow to reduce conflicts)
- `status: "backlog"`

Then run:

```powershell
python scripts\run_blender_buildings_workflows.py route
python scripts\run_blender_buildings_workflows.py control-plane --execute-ollama
```

### 4) Suggested parallelism

- Run 2-3 active batches per code file region.
- Keep each batch isolated; merge and validate before opening the next wave.
- Use watchdog and dashboard for stale-task reassignment and visibility.
