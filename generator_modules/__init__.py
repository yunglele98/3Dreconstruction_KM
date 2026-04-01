# generator_modules — extracted modules from generate_building.py
#
# This package decomposes the monolithic generate_building.py (~9,800 lines)
# into focused, testable modules. Functions are re-exported into the main
# generator's namespace via:
#
#   from generator_modules.colours import *
#
# Module roadmap:
#   colours.py    — colour resolution, hex conversion, era defaults  (pure Python)
#   materials.py  — procedural Blender materials (bpy-dependent)
#   roofs.py      — roof geometry creation
#   walls.py      — wall + window + door geometry
#   decorative.py — string courses, quoins, cornices, etc.
#   porch.py      — porch, steps, railings
#   storefront.py — ground-floor commercial shopfronts
