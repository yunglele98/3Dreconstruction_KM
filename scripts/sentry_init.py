"""Shared Sentry initialization for all pipeline batch scripts.

Usage:
    from sentry_init import init_sentry, capture_building_error
    init_sentry()

    try:
        generate_building(params)
    except Exception as e:
        capture_building_error(address, "generate", e)
"""

import os
import subprocess

try:
    import sentry_sdk
    HAS_SENTRY = True
except ImportError:
    HAS_SENTRY = False


def _get_git_hash():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return "unknown"


def init_sentry(dsn=None):
    """Initialize Sentry SDK. No-op if sentry_sdk not installed or no DSN."""
    if not HAS_SENTRY:
        return

    dsn = dsn or os.environ.get("SENTRY_DSN")
    if not dsn:
        return

    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=0.1,
        environment="production",
        release=_get_git_hash(),
    )


def capture_building_error(address, stage, error, params=None):
    """Capture a per-building error with context tags."""
    if not HAS_SENTRY:
        return

    try:
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("address", address)
            scope.set_tag("stage", stage)
            if params:
                scope.set_tag("facade_material", (params.get("facade_material") or "unknown"))
                scope.set_tag("roof_type", (params.get("roof_type") or "unknown"))
                scope.set_tag("floors", str(params.get("floors", "?")))
                street = ""
                site = params.get("site")
                if isinstance(site, dict):
                    street = site.get("street", "")
                scope.set_tag("street", street)
            sentry_sdk.capture_exception(error)
    except Exception:
        pass  # never let Sentry crash the pipeline
