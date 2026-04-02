#!/usr/bin/env python3
"""Generate UE5 level setup JSON for Kensington Market scene.

Produces a JSON blueprint specifying:
- DirectionalLight (Toronto sun angles by month)
- SkyLight + SkyAtmosphere
- Post-process volume (Lumen GI, exposure, colour grading)
- PlayerStart + cinematic camera rig
- ExponentialHeightFog for Toronto lake-effect atmosphere
- Level bounds matching SRID 2952 extents

Usage:
    python scripts/unreal/generate_level_blueprint.py
    python scripts/unreal/generate_level_blueprint.py --month 7 --time 14
    python scripts/unreal/generate_level_blueprint.py --output outputs/unreal/level_blueprint.json
"""
import argparse
import json
import math
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent.parent.parent

# Toronto coordinates for sun angle calculation
TORONTO_LAT = 43.656
TORONTO_LON = -79.400

# Scene bounds (SRID 2952 local coords, centred on Kensington)
SCENE_ORIGIN_X = 312672.94
SCENE_ORIGIN_Y = 4834994.86
SCENE_EXTENT = 500.0  # metres radius from origin


def solar_angles(month, hour, lat=TORONTO_LAT):
    """Approximate solar elevation and azimuth for Toronto.

    Simplified formula — good enough for lighting direction.
    """
    # Declination angle (approximate)
    day_of_year = (month - 1) * 30 + 15
    declination = 23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))

    # Hour angle (15 deg per hour from solar noon)
    hour_angle = (hour - 12) * 15

    # Solar elevation
    lat_r = math.radians(lat)
    dec_r = math.radians(declination)
    ha_r = math.radians(hour_angle)
    sin_elev = (math.sin(lat_r) * math.sin(dec_r) +
                math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r))
    elevation = math.degrees(math.asin(max(-1, min(1, sin_elev))))

    # Solar azimuth (simplified)
    cos_az = ((math.sin(dec_r) - math.sin(lat_r) * sin_elev) /
              (math.cos(lat_r) * math.cos(math.radians(elevation)) + 1e-6))
    azimuth = math.degrees(math.acos(max(-1, min(1, cos_az))))
    if hour > 12:
        azimuth = 360 - azimuth

    return elevation, azimuth


def build_level_blueprint(month=6, hour=14, lumen_gi=True):
    """Build complete UE5 level setup JSON."""
    sun_elev, sun_az = solar_angles(month, hour)

    blueprint = {
        "_meta": {
            "generator": "kensington-pipeline",
            "generated_at": datetime.now().isoformat(),
            "ue_version": "5.4+",
            "description": "Kensington Market scene level blueprint",
        },

        "world_settings": {
            "world_to_meters": 100,
            "enable_world_partition": True,
            "streaming_distance": 50000,
        },

        "directional_light": {
            "class": "DirectionalLight",
            "label": "Sun_Toronto",
            "rotation": {
                "pitch": -sun_elev,
                "yaw": sun_az,
                "roll": 0,
            },
            "intensity": 10.0,
            "light_color": {"r": 255, "g": 240, "b": 220},
            "temperature": 5800,
            "cast_shadows": True,
            "use_atmosphere_sun_light": True,
            "atmosphere_sun_light_index": 0,
            "shadow_cascade_count": 4,
            "dynamic_shadow_distance": 20000,
            "notes": f"Toronto solar angles: elev={sun_elev:.1f}° az={sun_az:.1f}° (month={month} hour={hour})",
        },

        "sky_light": {
            "class": "SkyLight",
            "label": "SkyLight_Kensington",
            "intensity": 1.0,
            "real_time_capture": True,
            "source_type": "SLS_CapturedScene",
            "lower_hemisphere_color": {"r": 0.15, "g": 0.13, "b": 0.12},
        },

        "sky_atmosphere": {
            "class": "SkyAtmosphere",
            "label": "SkyAtmosphere_Toronto",
            "ground_albedo": {"r": 0.3, "g": 0.3, "b": 0.3},
            "atmosphere_height": 60000,
            "rayleigh_scattering": {"r": 0.0058, "g": 0.0135, "b": 0.0331},
        },

        "exponential_height_fog": {
            "class": "ExponentialHeightFog",
            "label": "LakeEffectFog",
            "fog_density": 0.005,
            "fog_height_falloff": 0.2,
            "start_distance": 5000,
            "fog_inscattering_color": {"r": 0.6, "g": 0.65, "b": 0.75},
            "volumetric_fog": True,
            "volumetric_fog_distance": 10000,
            "notes": "Toronto lake-effect haze — subtle blue-grey shift",
        },

        "post_process_volume": {
            "class": "PostProcessVolume",
            "label": "PP_Kensington",
            "infinite_extent": True,
            "priority": 0,
            "settings": {
                "global_illumination": {
                    "method": "Lumen" if lumen_gi else "ScreenSpace",
                    "lumen_scene_lighting_quality": 3,
                    "lumen_scene_detail": 2,
                    "lumen_final_gather_quality": 1.0,
                    "lumen_max_trace_distance": 20000,
                },
                "reflections": {
                    "method": "Lumen" if lumen_gi else "ScreenSpace",
                    "lumen_reflection_quality": 2,
                },
                "exposure": {
                    "method": "Manual",
                    "exposure_compensation": 0.0,
                    "min_ev100": 6.0,
                    "max_ev100": 16.0,
                },
                "color_grading": {
                    "white_balance_temp": 6200,
                    "saturation": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 0.95},
                    "contrast": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.05},
                    "film_toe": 0.5,
                    "film_shoulder": 0.26,
                },
                "ambient_occlusion": {
                    "intensity": 0.5,
                    "radius": 200.0,
                    "power": 2.0,
                },
                "bloom": {
                    "method": "Standard",
                    "intensity": 0.3,
                    "threshold": 1.0,
                },
            },
        },

        "player_start": {
            "class": "PlayerStart",
            "label": "PlayerStart_Augusta",
            "location": {"x": 0, "y": 0, "z": 200},
            "rotation": {"pitch": 0, "yaw": 0, "roll": 0},
            "notes": "Centre of Augusta Ave — primary walkthrough start",
        },

        "cinematic_cameras": [
            {
                "class": "CineCameraActor",
                "label": "Cam_Augusta_Flyover",
                "location": {"x": 0, "y": 0, "z": 2500},
                "rotation": {"pitch": -45, "yaw": 90, "roll": 0},
                "focal_length": 24,
                "sensor_width": 36,
                "notes": "High flyover looking down Augusta Ave",
            },
            {
                "class": "CineCameraActor",
                "label": "Cam_Kensington_StreetLevel",
                "location": {"x": -50, "y": 100, "z": 180},
                "rotation": {"pitch": -5, "yaw": 0, "roll": 0},
                "focal_length": 35,
                "sensor_width": 36,
                "notes": "Eye-level walk along Kensington Ave",
            },
            {
                "class": "CineCameraActor",
                "label": "Cam_Market_Overview",
                "location": {"x": 0, "y": -200, "z": 5000},
                "rotation": {"pitch": -60, "yaw": 0, "roll": 0},
                "focal_length": 50,
                "sensor_width": 36,
                "notes": "Bird's eye overview of entire market district",
            },
        ],

        "level_bounds": {
            "origin_srid2952": {"x": SCENE_ORIGIN_X, "y": SCENE_ORIGIN_Y},
            "extent_metres": SCENE_EXTENT,
            "bounding_box": {
                "min": {"x": -SCENE_EXTENT * 100, "y": -SCENE_EXTENT * 100, "z": -100},
                "max": {"x": SCENE_EXTENT * 100, "y": SCENE_EXTENT * 100, "z": 10000},
            },
            "notes": "All coords in UE centimetres, origin at scene centre",
        },
    }

    return blueprint


def main():
    parser = argparse.ArgumentParser(description="Generate UE5 level blueprint")
    parser.add_argument("--month", type=int, default=6, help="Month (1-12) for sun angle")
    parser.add_argument("--time", type=int, default=14, help="Hour (0-23) for sun angle")
    parser.add_argument("--no-lumen", action="store_true", help="Use screen-space GI instead of Lumen")
    parser.add_argument("--output", type=Path,
                        default=REPO / "outputs" / "unreal" / "level_blueprint.json")
    args = parser.parse_args()

    blueprint = build_level_blueprint(
        month=args.month, hour=args.time, lumen_gi=not args.no_lumen)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(blueprint, indent=2), encoding="utf-8")
    print(f"Level blueprint: {args.output}")
    print(f"  Sun: elev={blueprint['directional_light']['rotation']['pitch']:.1f}° "
          f"az={blueprint['directional_light']['rotation']['yaw']:.1f}°")
    print(f"  GI: {blueprint['post_process_volume']['settings']['global_illumination']['method']}")


if __name__ == "__main__":
    main()
