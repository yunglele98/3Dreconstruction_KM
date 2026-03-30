"""
Centralized configuration of all hardcoded numeric defaults in generate_building.py

This module consolidates numeric constants used throughout the building generation
pipeline to make them easy to tweak and maintain in one place.

Categories:
- Wall Geometry — structural wall dimensions
- Windows — default dimensions and counts
- Doors — default dimensions and spacing
- String Courses & Decorative Bands — horizontal belt courses
- Quoins — corner decorative blocks
- Cornices — roof edge details
- Porches — front porch structure
- Steps & Stairs — default step dimensions
- Railings — baluster and rail dimensions
- Chimneys — chimney sizing
- Bay Windows — bay projection and sizing
- Roofs — pitch, overhang, and related dimensions
- Foundations — foundation height
- Materials — texture scales and roughness values
- Gutters & Fascia — roof edge finishing
- Brick Patterns — individual brick dimensions for corbels and voussoirs
"""

# =============================================================================
# WALL GEOMETRY
# =============================================================================

WALL_THICKNESS_M = 0.3
"""Wall thickness in metres. Represents the hollow gap between exterior and
interior faces of the building walls."""

DEFAULT_DEPTH_M = 10.0
"""Default building depth when not specified in params. Used as fallback
for buildings without explicit facade_depth_m."""

WALL_HOLLOW_OFFSET_M = 0.02
"""Small vertical offset for interior wall box to prevent z-fighting.
Ensures interior box is slightly taller than necessary to cleanly cut the hole."""

WALL_NORMAL_OFFSET_Y = -0.01
"""Slight Y-offset when creating interior wall cutout to ensure clean boolean
operation. Prevents coincident faces."""

# =============================================================================
# WINDOWS
# =============================================================================

DEFAULT_WINDOW_WIDTH_M = 0.85
"""Default window width in metres when not specified in params or window_detail."""

DEFAULT_WINDOW_HEIGHT_M = 1.3
"""Default window height in metres when not specified."""

WINDOW_SILL_HEIGHT_M = 0.8
"""Default window sill height above floor when not explicitly specified.
Used to center windows vertically within floor height."""

WINDOW_FRAME_DEPTH_M = 0.06
"""Frame depth (how much frame extends from wall surface). Used for glass pane
positioning to create realistic window reveal."""

GABLE_WINDOW_DEFAULT_HEIGHT_M = 0.8
"""Default height for gable/attic windows, which are typically smaller than
regular floor windows."""

GABLE_WINDOW_CENTER_RATIO = 0.45
"""Position of gable window from the bottom of the gable triangle, as a ratio
of ridge height. 0.45 = slightly below visual center."""

# =============================================================================
# DOORS
# =============================================================================

DEFAULT_DOOR_WIDTH_M = 1.0
"""Default door opening width in metres."""

DEFAULT_DOOR_HEIGHT_M = 2.1
"""Default door height in metres (full ceiling height to lintel)."""

DOOR_SILL_OFFSET_Y = 0.01
"""Small Y-offset for door cutters to prevent z-fighting with wall."""

# =============================================================================
# STRING COURSES & DECORATIVE BANDS
# =============================================================================

STRING_COURSE_HEIGHT_MM = 120
"""Default height of string course (belt course) in millimetres. Typical
Kensington Market heritage buildings have ~120mm courses."""

STRING_COURSE_PROJECTION_MM = 20
"""Default projection (overhang) of string course in millimetres. Controls
how far the band protrudes from the wall surface."""

STRING_COURSE_COLOUR_HEX = "#D4C9A8"
"""Default colour (buff stone) for string courses when not specified."""

# =============================================================================
# QUOINS
# =============================================================================

QUOIN_STRIP_WIDTH_MM = 220
"""Default width of individual quoin (corner) stone blocks in millimetres."""

QUOIN_PROJECTION_MM = 18
"""Default projection (relief) of quoin blocks in millimetres."""

QUOIN_COLOUR_HEX = "#D4C9A8"
"""Default colour for quoins (buff stone) when not specified."""

# =============================================================================
# CORNICES
# =============================================================================

CORNICE_HEIGHT_MM = 220
"""Default cornice height in millimetres. Cornices sit at the eave line,
between the wall and roof."""

CORNICE_PROJECTION_MM = 180
"""Default cornice projection (overhang) in millimetres."""

CORNICE_COLOUR_HEX = "#D4C9A8"
"""Default cornice colour (buff stone) when not specified."""

# =============================================================================
# PORCHES
# =============================================================================

DEFAULT_PORCH_WIDTH_M = 2.0
"""Default porch width when not specified. Falls back to facade_width if
porch params missing."""

DEFAULT_PORCH_DEPTH_M = 2.0
"""Default porch depth (Y-extent) in metres. Typical front porch projection."""

DEFAULT_PORCH_HEIGHT_M = 2.8
"""Default porch roof height in metres (top of porch beam)."""

DEFAULT_PORCH_FLOOR_HEIGHT_M = 0.5
"""Default height of porch deck above sidewalk/grade in metres."""

PORCH_DECK_THICKNESS_M = 0.1
"""Thickness of the porch deck/floor in metres."""

PORCH_BEAM_HEIGHT_M = 0.12
"""Height of the front porch beam (connects posts to roof) in metres."""

PORCH_ROOF_THICKNESS_M = 0.08
"""Thickness of porch roof structure in metres."""

PORCH_POST_RADIUS_M = 0.05
"""Radius of cylindrical porch posts in metres."""

PORCH_RAILING_HEIGHT_MM = 800
"""Default height of porch railings in millimetres (3-4 ft typical)."""

PORCH_BALUSTER_SPACING_M = 0.12
"""Spacing between balusters (small vertical posts) in metres."""

PORCH_BALUSTER_SIZE_M = 0.025
"""Width/depth of individual balusters in metres."""

PORCH_RAIL_THICKNESS_M = 0.04
"""Thickness of the horizontal top and bottom rails."""

PORCH_RAIL_BOTTOM_HEIGHT_M = 0.05
"""Height of bottom rail from porch deck."""

PORCH_BALUSTER_HEIGHT_FROM_DECK_M = 0.04
"""Bottom margin of balusters from porch deck."""

# =============================================================================
# STEPS & STAIRS
# =============================================================================

DEFAULT_STEP_COUNT = 3
"""Default number of steps on front porch stair when not specified."""

DEFAULT_STEP_WIDTH_M = 1.2
"""Default step width (X-extent, how wide the stair tread is) in metres."""

DEFAULT_STEP_RUN_M = 0.28
"""Default step run (Y-depth, horizontal tread depth) in metres."""

DEFAULT_STEP_X_OFFSET_M = 0.0
"""Default X-position for steps relative to porch center. Can be overridden
by 'left' or 'right' position specs."""

STEP_HANDRAIL_POST_RADIUS_M = 0.04
"""Radius of handrail support posts/balusters."""

STEP_HANDRAIL_HEIGHT_M = 0.85
"""Height of handrails on porch steps."""

STEP_HANDRAIL_BOTTOM_POST_HEIGHT_M = 0.9
"""Height of support posts for handrails (extends below rail)."""

STEP_HANDRAIL_TOP_POST_HEIGHT_M = 0.9
"""Height of top posts at landing."""

# =============================================================================
# RAILINGS
# =============================================================================

RAILING_HEIGHT_MM = 800
"""Default railing height in millimetres."""

RAILING_BALUSTER_SPACING_M = 0.12
"""Spacing between balusters in metres."""

RAILING_BALUSTER_SIZE_M = 0.025
"""Width/depth of balusters."""

RAILING_RAIL_THICKNESS_M = 0.04
"""Horizontal rail thickness."""

RAILING_RAIL_BOTTOM_THICKNESS_M = 0.03
"""Bottom rail thickness (slightly thinner)."""

RAILING_BOTTOM_OFFSET_M = 0.05
"""Distance from deck to bottom rail."""

RAILING_BALUSTER_HEIGHT_MARGIN_M = 0.08
"""Margin from rail to top/bottom of balusters."""

# =============================================================================
# CHIMNEYS
# =============================================================================

DEFAULT_CHIMNEY_WIDTH_M = 0.5
"""Default chimney width when not specified."""

DEFAULT_CHIMNEY_DEPTH_M = 0.4
"""Default chimney depth when not specified."""

DEFAULT_CHIMNEY_HEIGHT_ABOVE_RIDGE_M = 1.0
"""Default how far chimney extends above ridge peak."""

MAX_CHIMNEY_HEIGHT_ABOVE_RIDGE_M = 1.5
"""Maximum clamp for chimney height above ridge to prevent unrealistic
proportions."""

# =============================================================================
# BAY WINDOWS
# =============================================================================

DEFAULT_BAY_WINDOW_PROJECTION_M = 0.6
"""Default how far bay windows project from the facade."""

DEFAULT_BAY_WINDOW_WIDTH_RATIO = 0.42
"""Bay window width as a ratio of facade width (0.42 = 42% of facade)."""

MIN_BAY_WINDOW_WIDTH_M = 1.8
"""Minimum bay window width to prevent unrealistically narrow bays."""

MAX_BAY_WINDOW_WIDTH_M = 2.6
"""Maximum bay window width for typical Victorian/Edwardian bays."""

# =============================================================================
# ROOFS
# =============================================================================

DEFAULT_ROOF_PITCH_DEG = 35
"""Default roof pitch in degrees when not specified."""

PARAPET_HEIGHT_M = 0.3
"""Height of parapet wall above roof line."""

ROOF_THICKNESS_M = 0.08
"""Thickness of roof mesh geometry."""

HIP_ROOFLET_THICKNESS_M = 0.08
"""Thickness of small hip rooflets (e.g. on towers)."""

EAVE_OVERHANG_MM = 300
"""Default eave overhang (how far roof extends past wall) in millimetres."""

EAVE_OVERHANG_METAL_STRAP_SPACING_M = 0.3
"""Spacing of metal straps under eave overhang."""

# =============================================================================
# FOUNDATIONS
# =============================================================================

FOUNDATION_HEIGHT_M = 0.2
"""Height of visible foundation/basement storey above grade."""

# =============================================================================
# MATERIALS & TEXTURES
# =============================================================================

BRICK_MATERIAL_ROUGHNESS = 0.85
"""Roughness value for brick shader (affects specularity). 0.85 = matte brick."""

WOOD_MATERIAL_ROUGHNESS = 0.65
"""Roughness value for wood materials."""

PAINTED_MATERIAL_ROUGHNESS = 0.75
"""Roughness value for painted surfaces (brick or clapboard)."""

ROOF_MATERIAL_ROUGHNESS = 0.92
"""Roughness value for roof shingles (very matte)."""

STONE_MATERIAL_ROUGHNESS = 0.85
"""Roughness value for stone materials (concrete, limestone, etc.)."""

POST_MATERIAL_ROUGHNESS = 0.6
"""Roughness for porch posts (slightly shinier wood)."""

TEXTURE_SCALE_BRICKS = 8.0
"""Scale factor for brick texture mapping. Controls how many bricks appear
per metre of wall. 8.0 = typical brick size."""

TEXTURE_SCALE_ROOF_SHINGLES = 15.0
"""Scale factor for roof shingle texture."""

TEXTURE_SCALE_WOOD_GRAIN = 1.0
"""Scale factor for wood grain texture."""

BRICK_PATTERN_BRICK_WIDTH = 0.5
"""Brick pattern width ratio in procedural texture node (0.5 = 50% width)."""

BRICK_PATTERN_ROW_HEIGHT = 0.25
"""Brick pattern row height ratio."""

BRICK_MORTAR_SIZE = 0.015
"""Mortar joint size in procedural texture."""

BRICK_MORTAR_SMOOTH = 0.1
"""Mortar smoothness in procedural texture."""

BRICK_BUMP_STRENGTH = 0.3
"""Strength of bump mapping for brick texture."""

BRICK_BUMP_DISTANCE = 0.01
"""Distance for bump mapping (affects appearance of mortar relief)."""

WOOD_WAVE_SCALE = 3.0
"""Scale of wood wave texture."""

WOOD_WAVE_DISTORTION = 8.0
"""Distortion amount for wood grain."""

WOOD_WAVE_DETAIL = 3.0
"""Detail level of wood grain."""

WOOD_BUMP_STRENGTH = 0.15
"""Bump strength for wood texture."""

STONE_NOISE_SCALE = 25.0
"""Scale of noise texture for stone/concrete."""

STONE_NOISE_DETAIL = 6.0
"""Detail level of stone noise texture."""

STONE_NOISE_ROUGHNESS = 0.6
"""Roughness of noise pattern."""

STONE_BUMP_STRENGTH = 0.2
"""Bump strength for stone texture."""

PAINTED_NOISE_SCALE = 40.0
"""Scale of wear/aging noise pattern for painted surfaces."""

PAINTED_NOISE_DETAIL = 3.0
"""Detail level of painted surface aging."""

GLASS_COLOUR_RGB = (0.7, 0.82, 0.88)
"""Glass colour in RGB (slight blue-green tint)."""

GLASS_ROUGHNESS = 0.02
"""Glass surface roughness (very smooth/polished)."""

GLASS_ALPHA = 0.3
"""Glass alpha/transparency. 0.3 = some opacity/reflection blending."""

GLASS_TRANSMISSION = 0.7
"""Glass transmission (how much light passes through)."""

# =============================================================================
# GUTTERS & FASCIA
# =============================================================================

GUTTER_RADIUS_M = 0.04
"""Radius of cylindrical gutter profile."""

FASCIA_BOARD_THICKNESS_M = 0.025
"""Thickness of fascia board."""

FASCIA_BOARD_HEIGHT_M = 0.12
"""Height of fascia board (visible from below)."""

# =============================================================================
# BRICK PATTERNS & CORBELS
# =============================================================================

CORBEL_BRICK_WIDTH_M = 0.22
"""Width of individual brick in corbel course."""

CORBEL_BRICK_HEIGHT_M = 0.075
"""Height of individual brick in corbel course."""

CORBEL_BASE_PROJECTION_M = 0.035
"""Base projection of corbel course."""

CORBEL_STEP_PROJECTION_M = 0.02
"""Additional projection per course in corbel table."""

CORBEL_BRICK_SCALE_FACTOR = 0.46
"""Corbel brick scale factor relative to spacing."""

CORBEL_BRICK_HEIGHT_SCALE_FACTOR = 0.48
"""Corbel brick height scale factor."""

# =============================================================================
# VOUSSOIRS (ARCH STONES)
# =============================================================================

VOUSSOIR_DEFAULT_COUNT = 11
"""Default number of voussoir wedges in an arch."""

VOUSSOIR_RADIUS_OFFSET_M = 0.08
"""Extra radius offset from opening width to position voussoirs."""

VOUSSOIR_DEPTH_M = 0.12
"""Depth (Y-extent) of individual voussoir blocks."""

VOUSSOIR_WIDTH_RATIO = 0.06
"""Voussoir width as ratio of arch width."""

VOUSSOIR_HEIGHT_RATIO = 0.08
"""Voussoir height as ratio of arch height."""

VOUSSOIR_MIN_WIDTH_M = 0.08
"""Minimum voussoir width to prevent too-small geometry."""

VOUSSOIR_MIN_HEIGHT_M = 0.10
"""Minimum voussoir height."""

# =============================================================================
# BARGEBOARD & GABLE
# =============================================================================

BARGEBOARD_THICKNESS_M = 0.04
"""Thickness of bargeboard trim on gable edges."""

BARGEBOARD_DEFAULT_WIDTH_MM = 220
"""Default bargeboard width in millimetres when not specified."""

GABLE_SHINGLE_EXPOSURE_MM = 110
"""Shingle exposure (how much shows) in millimetres."""

GABLE_SHINGLE_COLOUR_HEX = "#6B4C3B"
"""Default shingle colour (brown) when not specified."""

# =============================================================================
# STOREFRONT
# =============================================================================

STOREFRONT_BULKHEAD_HEIGHT_M = 0.6
"""Default bulkhead height (solid panel below storefront windows)."""

STOREFRONT_CUTTER_OFFSET_Y = 0.01
"""Y-offset for storefront cutter to prevent z-fighting."""

STOREFRONT_GLASS_PANEL_DEPTH_M = 0.04
"""Depth of glass panels in storefront."""

STOREFRONT_METAL_FRAME_THICKNESS_M = 0.03
"""Thickness of metal frames in storefront."""

STOREFRONT_SLAT_HEIGHT_M = 0.08
"""Height of individual vertical slats in storefront grille."""

# =============================================================================
# ARCHITECTURE-SPECIFIC DEFAULTS
# =============================================================================

ONTARIO_COTTAGE_FLOOR_COUNT = 1
"""Ontario cottage typology always has 1 floor (from get_typology_hints)."""

INSTITUTIONAL_EXPECTED_FLOORS = 3
"""Institutional buildings typically expected to have 3 floors."""

# =============================================================================
# COLOUR & MATERIAL DEFAULTS
# =============================================================================

MORTAR_COLOUR_DEFAULT_HEX = "#B0A898"
"""Default mortar colour (warm grey-tan) when not specified."""

MORTAR_COLOUR_GREY_HEX = "#8A8A8A"
"""Grey mortar colour (modern)."""

MORTAR_COLOUR_LIGHT_HEX = "#C0B8A8"
"""Light mortar colour (bleached)."""

BRICK_COLOUR_DEFAULT_RGB = (0.45, 0.18, 0.10)
"""Default brick colour RGB (warm red-brown)."""

BRICK_COLOUR_PRE1889_RGB = (0.5, 0.15, 0.08)
"""Pre-1889 Victorian brick colour (richer red)."""

TRIM_COLOUR_DARK_HEX = "#3A2A20"
"""Dark trim colour (walnut brown, pre-1889)."""

TRIM_COLOUR_BLACK_HEX = "#2A2A2A"
"""Near-black trim colour (Edwardian, 1904-1913)."""

TRIM_COLOUR_CREAM_HEX = "#F0EDE8"
"""Cream trim colour (modern, 1931+)."""

POST_COLOUR_DARK_HEX = "#3A2A20"
"""Default porch post colour (dark brown)."""

ROOF_COLOUR_DARK_HEX = "#3A3A3A"
"""Dark roof colour (charcoal)."""

ROOF_COLOUR_GREY_HEX = "#5A5A5A"
"""Grey roof colour."""

ROOF_COLOUR_RED_HEX = "#8A3A2A"
"""Red roof colour."""

CONCRETE_COLOUR_HEX = "#A0A0A0"
"""Concrete/step colour."""

WOOD_COLOUR_HEX = "#8B7355"
"""Wood colour for porch deck."""

# =============================================================================
# SPECIAL SITE/SCALING
# =============================================================================

SITE_COORDINATE_ORIGIN_X = 312672.94
"""X-coordinate origin for SRID 2952 (NAD83 / Ontario MTM Zone 10)."""

SITE_COORDINATE_ORIGIN_Y = 4834994.86
"""Y-coordinate origin for SRID 2952."""

DEFAULT_BUILDING_SPACING_M = 15.0
"""Default spacing between buildings when laying out multiple buildings
in linear sequence (for preview/test scenes)."""

# =============================================================================
# RENDERING & OUTPUT
# =============================================================================

ARCH_SEGMENTS = 24
"""Number of segments for smooth arch curves in window/door openings."""

BRICK_COLOUR_VARIATION = 0.85
"""Colour2 for brick texture (85% of Color1). Creates shading variation."""

ROOF_SHINGLE_COLOUR_BRIGHT_FACTOR = 1.2
"""Brightness multiplier for roof shingle highlights."""

ROOF_SHINGLE_COLOUR_SHADOW_FACTOR = 0.7
"""Darkness multiplier for roof shingle shadows."""

ROOF_SHINGLE_MORTAR_FACTOR = 0.4
"""Mortar colour multiplier (how dark the grout between shingles)."""

GLASS_COLOUR_VARIATION = 0.85
"""Colour2 for glass-like surfaces (85% of primary)."""

# =============================================================================
# UTILITY
# =============================================================================

UTILITY_ANCHOR_HEIGHT_RATIO = 0.7
"""Utility wire anchors placed at this ratio of total building height
(0.7 = 70% up the facade, mid-wall spaghetti)."""

# =============================================================================
# API DEFAULTS FOR PARAMETER FILES
# =============================================================================

DEFAULT_PARAM_FACADE_WIDTH_M = 6.0
"""Default facade_width_m if not in params file."""

DEFAULT_PARAM_FLOORS = 2
"""Default floor count if not specified."""

DEFAULT_PARAM_FLOOR_HEIGHT_M = 3.0
"""Default individual floor height if not specified."""

DEFAULT_PARAM_TOTAL_HEIGHT_M = 9.0
"""Default total height if not calculated from floors."""

DEFAULT_PARAM_WINDOW_TYPE = "double_hung"
"""Default window type if not specified."""

DEFAULT_PARAM_CONDITION = "good"
"""Default building condition rating if not specified."""

DEFAULT_PARAM_ROOF_COLOUR = "#4A4A4A"
"""Default roof colour if not determinable from params."""
