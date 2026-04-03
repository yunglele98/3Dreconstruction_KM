#!/usr/bin/env python3
"""Configure Sentry error monitoring for the pipeline.

Initialises sentry-sdk with the provided DSN and environment.
Gracefully skips if sentry-sdk is not installed.

Usage:
    python scripts/monitor/sentry_setup.py --dsn https://examplePublicKey@o0.ingest.sentry.io/0
    python scripts/monitor/sentry_setup.py --environment prod --test
    SENTRY_DSN=https://... python scripts/monitor/sentry_setup.py --test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def configure_sentry(dsn: str, environment: str) -> dict:
    """Attempt to configure sentry-sdk. Returns a status dict."""
    try:
        import sentry_sdk  # noqa: F811
    except ImportError:
        return {
            "status": "skipped",
            "reason": "sentry-sdk not installed (pip install sentry-sdk)",
            "dsn": dsn,
            "environment": environment,
        }

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=0.1,
        release="kensington-3d@0.1.0",
    )

    return {
        "status": "ok",
        "dsn_masked": dsn[:20] + "..." if len(dsn) > 20 else dsn,
        "environment": environment,
        "sdk_version": sentry_sdk.VERSION,
    }


def send_test_event(dsn: str, environment: str) -> dict:
    """Send a test event to Sentry and verify it was captured."""
    try:
        import sentry_sdk
    except ImportError:
        return {
            "status": "error",
            "reason": "sentry-sdk not installed",
        }

    # Ensure SDK is initialised
    if not sentry_sdk.is_initialized():
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=1.0,
            release="kensington-3d@0.1.0",
        )

    event_id = sentry_sdk.capture_message(
        f"Kensington 3D pipeline test event (env={environment})"
    )

    if event_id:
        return {
            "status": "ok",
            "event_id": event_id,
            "message": "Test event sent successfully",
        }
    else:
        return {
            "status": "error",
            "reason": "capture_message returned None (check DSN)",
        }


def main():
    parser = argparse.ArgumentParser(
        description="Configure Sentry error monitoring for the pipeline."
    )
    parser.add_argument(
        "--dsn",
        default=os.environ.get("SENTRY_DSN", ""),
        help="Sentry DSN (or set SENTRY_DSN env var)",
    )
    parser.add_argument(
        "--environment",
        default="dev",
        choices=["dev", "staging", "prod"],
        help="Sentry environment (default: dev)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Send a test event to verify Sentry integration",
    )
    args = parser.parse_args()

    if not args.dsn:
        print("ERROR: No DSN provided. Use --dsn or set SENTRY_DSN env var.")
        sys.exit(1)

    print("=" * 50)
    print("  Sentry Setup — Kensington Market 3D Pipeline")
    print("=" * 50)

    config_result = configure_sentry(args.dsn, args.environment)
    print(f"\nConfiguration: {config_result['status']}")
    for key, value in config_result.items():
        if key != "status":
            print(f"  {key}: {value}")

    if args.test:
        print("\nSending test event...")
        test_result = send_test_event(args.dsn, args.environment)
        print(f"Test: {test_result['status']}")
        for key, value in test_result.items():
            if key != "status":
                print(f"  {key}: {value}")

    summary = {"config": config_result}
    if args.test:
        summary["test"] = test_result

    print(f"\n{json.dumps(summary, indent=2)}")

    if config_result["status"] == "error" or (
        args.test and test_result.get("status") == "error"
    ):
        sys.exit(1)


if __name__ == "__main__":
    main()
