#!/usr/bin/env python3
"""Stage 10b: Batch health check. Called by n8n WF-01 or standalone."""
import json, logging, shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
REPO = Path(__file__).parent.parent.parent

def check_disk():
    usage = shutil.disk_usage(str(REPO))
    free_gb = usage.free / (1024**3)
    pct = usage.used / usage.total * 100
    return {"free_gb": round(free_gb,1), "used_pct": round(pct,1),
            "severity": "ok" if pct < 80 else "warn" if pct < 90 else "critical"}

def check_gpu_lock():
    lock = REPO / ".gpu_lock"
    if lock.exists():
        try: return {"locked": True, **json.loads(lock.read_text(encoding="utf-8"))}
        except: return {"locked": True, "holder": "unknown"}
    return {"locked": False}

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    health = {"checked_at": datetime.now().isoformat(), "disk": check_disk(),
              "gpu_lock": check_gpu_lock(), "overall": "healthy"}
    if health["disk"]["severity"] != "ok": health["overall"] = health["disk"]["severity"]
    if args.json: print(json.dumps(health, indent=2))
    else:
        logger.info("Health: %s | Disk: %.1fGB free (%.1f%%) | GPU: %s",
                     health["overall"], health["disk"]["free_gb"],
                     health["disk"]["used_pct"], "LOCKED" if health["gpu_lock"]["locked"] else "free")
    (REPO / ".health_state.json").write_text(json.dumps(health, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
