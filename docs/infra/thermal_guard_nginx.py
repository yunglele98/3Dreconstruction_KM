#!/usr/bin/env python3
"""
thermal_guard_nginx.py — Sidecar that writes a maintenance flag when CPU > 70%.

Nginx Proxy Manager checks for this flag file in custom location blocks
and returns 503 to pause heavy inference routes until load drops.

Run inside a lightweight container or as a host-level service:
    python thermal_guard_nginx.py

The flag file path must match the volume mount in docker-compose.proxy-git.yml:
    ./infra/nginx-custom:/data/nginx/custom:ro  (NPM reads it)
    ./infra/nginx-custom:/flags                  (this script writes it)
"""

import time
import sys
from pathlib import Path

try:
    import psutil
except ImportError:
    print("ERROR: psutil required. Install with: pip install psutil")
    sys.exit(1)

FLAG_PATH = Path(__file__).parent / "nginx-custom" / "maintenance.flag"
CPU_THRESHOLD = 70       # percent
CHECK_INTERVAL = 5       # seconds
COOLDOWN_CHECKS = 3      # require N consecutive below-threshold readings before clearing

def main():
    consecutive_below = 0
    print(f"Thermal guard active — threshold: {CPU_THRESHOLD}% CPU")
    print(f"Flag file: {FLAG_PATH}")

    while True:
        cpu = psutil.cpu_percent(interval=CHECK_INTERVAL)

        if cpu > CPU_THRESHOLD:
            consecutive_below = 0
            if not FLAG_PATH.exists():
                FLAG_PATH.touch()
                print(f"[THROTTLE] CPU {cpu:.0f}% > {CPU_THRESHOLD}% — maintenance flag SET")
        else:
            consecutive_below += 1
            if FLAG_PATH.exists() and consecutive_below >= COOLDOWN_CHECKS:
                FLAG_PATH.unlink(missing_ok=True)
                print(f"[CLEAR] CPU {cpu:.0f}% < {CPU_THRESHOLD}% for {COOLDOWN_CHECKS} checks — flag CLEARED")

if __name__ == "__main__":
    main()
