#!/usr/bin/env python3
"""Build per-instance runtime override table (wetness/grime/decal intensity)."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import psycopg2

from db_config import DB_CONFIG, get_connection

ROOT = Path(__file__).resolve().parents[1]
IN_INST = ROOT / "outputs" / "alley_garages" / "alley_garage_instances_unreal_refined_cm.csv"
IN_ZONES = ROOT / "outputs" / "alley_garages" / "graffiti_zone_presets.json"
OUT_CSV = ROOT / "outputs" / "alley_garages" / "unreal_alley_runtime_overrides.csv"

ORIGIN_X = 312672.94
ORIGIN_Y = 4834994.86


def u(seed: str) -> float:
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def to_local_cm(cur, lon: float, lat: float):
    cur.execute(
        """
        SELECT ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),4326),2952)) AS x,
               ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),4326),2952)) AS y
        """,
        (lon, lat, lon, lat),
    )
    r = cur.fetchone()
    x = float(r[0] if not isinstance(r, dict) else r["x"])
    y = float(r[1] if not isinstance(r, dict) else r["y"])
    return (x - ORIGIN_X) * 100.0, (y - ORIGIN_Y) * 100.0


def main() -> int:
    inst = list(csv.DictReader(IN_INST.open("r", encoding="utf-8", newline="")))
    zones = json.loads(IN_ZONES.read_text(encoding="utf-8")).get("zones", [])

    conn = get_connection()
    try:
        cur = conn.cursor()
        zone_xy = []
        for z in zones:
            lat = float(z["lat"])
            lon = float(z["lon"])
            x, y = to_local_cm(cur, lon, lat)
            zone_xy.append((z, x, y))
    finally:
        conn.close()

    rows = []
    for r in inst:
        x = float(r["x_cm"])
        y = float(r["y_cm"])
        key = r["alley_garage_key"].lower()

        # find nearest zone
        nearest = None
        best = 1e30
        for z, zx, zy in zone_xy:
            d = math.hypot(x - zx, y - zy)
            if d < best:
                best = d
                nearest = z

        tier = (nearest or {}).get("tier", "baseline")
        boost = float((nearest or {}).get("grime_boost", 0.04))
        density = float((nearest or {}).get("graffiti_density", 0.32))

        # Distance falloff in centimeters.
        falloff = max(0.2, min(1.0, 1.0 - (best / 12000.0)))

        wet = 0.35 + 0.25 * u(r["instance_id"] + "wet")
        grime = 0.45 + boost + 0.25 * u(r["instance_id"] + "gr")
        decal = density * falloff

        if "garage" in key:
            grime += 0.08
            decal += 0.12
        if "degraded" in key:
            grime += 0.15
        if "structured_interior" in key:
            wet -= 0.18
            decal -= 0.20

        rows.append(
            {
                "instance_id": r["instance_id"],
                "alley_garage_key": r["alley_garage_key"],
                "zone_tier": tier,
                "distance_to_zone_cm": f"{best:.1f}",
                "wetness_override": f"{max(0.0, min(1.0, wet)):.3f}",
                "grime_override": f"{max(0.0, min(1.0, grime)):.3f}",
                "decal_intensity_override": f"{max(0.0, min(1.0, decal)):.3f}",
                "roughness_shift": (nearest or {}).get("roughness_shift", 0.03),
            }
        )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["instance_id", "alley_garage_key", "zone_tier", "distance_to_zone_cm", "wetness_override", "grime_override", "decal_intensity_override", "roughness_shift"])
        w.writeheader()
        if rows:
            w.writerows(rows)

    print(f"[OK] Wrote {OUT_CSV}")
    print(f"[INFO] instance_overrides={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

