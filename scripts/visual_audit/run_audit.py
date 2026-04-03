#!/usr/bin/env python3
"""Phase 0 orchestrator: Run the full visual audit pipeline.

Chains: pair → compare → classify+score+rank → output priority queue.

Usage:
    python scripts/visual_audit/run_audit.py
    python scripts/visual_audit/run_audit.py --limit 10
    python scripts/visual_audit/run_audit.py --renders outputs/buildings_renders_v1/ --output outputs/visual_audit/
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent


def main():
    parser = argparse.ArgumentParser(description="Phase 0: Full visual audit")
    parser.add_argument("--renders", type=Path,
                        default=REPO_ROOT / "outputs" / "buildings_renders_v1")
    parser.add_argument("--photos", type=Path,
                        default=REPO_ROOT / "PHOTOS KENSINGTON")
    parser.add_argument("--params", type=Path,
                        default=REPO_ROOT / "params")
    parser.add_argument("--output", type=Path,
                        default=REPO_ROOT / "outputs" / "visual_audit")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only first N renders (0 = all)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args.output.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # ── Stage 1: Pair ──────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STAGE 1: PAIR renders to photos")
    logger.info("=" * 60)

    from pair_renders_to_photos import pair_all
    pairs = pair_all(args.renders, args.params, limit=args.limit)

    pairs_path = args.output / "pairs.json"
    pairs_path.write_text(json.dumps(pairs, indent=2), encoding="utf-8")

    matched = sum(1 for p in pairs if p["match_status"] == "matched")
    no_photo = sum(1 for p in pairs if p["match_status"] == "no_photo")
    logger.info("  %d matched, %d no_photo, %d total", matched, no_photo, len(pairs))

    # ── Stage 2: Compare ───────────────────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("STAGE 2: COMPARE render vs photo (metrics)")
    logger.info("=" * 60)

    from compare_render_to_photo import compare_all
    comparisons = compare_all(pairs, limit=args.limit)

    comparisons_path = args.output / "comparisons.json"
    comparisons_path.write_text(json.dumps(comparisons, indent=2), encoding="utf-8")
    logger.info("  %d comparisons computed", len([c for c in comparisons if c.get("metrics")]))

    # ── Stages 3-5: Classify + Score + Rank ────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("STAGES 3-5: CLASSIFY + SCORE + RANK")
    logger.info("=" * 60)

    from score_and_rank import score_and_rank
    result = score_and_rank(comparisons, args.params)

    priority_path = args.output / "priority_queue.json"
    priority_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    # ── Summary ────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 0 COMPLETE (%.1f seconds)", elapsed)
    logger.info("=" * 60)
    logger.info("\nTier breakdown:")
    for tier, count in result["tier_counts"].items():
        logger.info("  %-12s %4d", tier, count)

    logger.info("\nTop issues:")
    for issue, count in list(result["top_issues"].items())[:5]:
        logger.info("  %-25s %d", issue, count)

    logger.info("\nPipeline routing:")
    for stage, info in result["pipeline_routing"].items():
        logger.info("  %-30s %d buildings", stage, info["building_count"])

    logger.info("\nOutputs:")
    logger.info("  pairs.json          → %s", pairs_path)
    logger.info("  comparisons.json    → %s", comparisons_path)
    logger.info("  priority_queue.json → %s", priority_path)


if __name__ == "__main__":
    main()
