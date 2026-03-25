# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **photo documentation project** for Kensington Market in Toronto, not a software codebase. It contains ~1,928 geotagged field photos (JPG) and supporting CSV/text data files used to track street-level photographic coverage of the study area.

**Study area perimeter:** Dundas St W (north side) / Bathurst St (east side) / College St (south side) / Spadina Ave (west side). Only the market-facing side of each perimeter street is in scope.

## Directory Structure

- **Root:** JPG photos named by device timestamp (e.g., `IMG_20260315_150049808_HDR.jpg`, `PXL_20260318_...`)
- **csv/**: All structured data and planning documents:
  - `photo_address_index.csv` — master index (columns: `filename,address_or_location,source`). The canonical record for every photo.
  - `photo_address_index_revised.csv` — working copy of the index incorporating review corrections (same schema).
  - `photo_address_uncertain.csv` — subset of rows with lower confidence for review
  - `photo_address_consistency_report.txt` — flagged typos, weak clusters, and consistency issues
  - `perimeter_market_side_photos.csv` — photos specifically from perimeter streets
  - `kensington_field_card.txt` — walk order and per-block capture rules
  - `kensington_block_route_checklist.txt` — block-by-block route with segment boundaries
  - `kensington_coverage_checklist.txt` — per-street coverage status (covered / partial / missing)
  - `kensington_fieldwork_punch_list.txt` — prioritized list of streets still needing photo passes
  - `kensington_route_checkboxes.csv` — route progress tracking

### Review Workflow Files

A batch-based visual review process upgrades `inferred-cascade` labels to higher-confidence addresses:

- `build_review.py` — Python script that generates `review_tool.html` from `inferred-cascade` rows in `photo_address_index.csv`. The HTML tool groups photos by current label, lets the reviewer confirm/flag/relabel, and exports a corrections CSV.
- `batch1.json` … `batch4_d.json` — JSON arrays of `[line_number, filename]` pairs defining photo subsets for each review batch.
- `batch1_review.csv`, `batch2_results.csv`, `batch3_verified.csv`, `batch4_a_results.csv`, `batch4_verified.csv` — Review output CSVs (columns: `line_number,filename,current_label,suggested_label,confidence`).
- `photo_review_corrections (N).csv` — Corrections exported from the HTML review tool (columns: `filename,new_address,status`).
- `unreviewed_samples.csv` — Photos still awaiting review (columns: `timestamp,filename,current_label`).

## Key Concepts

- **Confidence tagging:** Each photo-address mapping has a `source` field indicating reliability. `confirmed` is highest; `inferred-cascade` and `inferred-approx` mean broad time/sequence-based guessing; `ref-match-low` needs manual review. The review workflow aims to promote `inferred-cascade` rows to `confirmed` or more specific labels.
- **Coverage status:** Streets are rated `covered`, `partial`, or `missing` based on labeled photo count and quality.
- **Per-block capture rule:** Each block segment needs (1) a wide establishing shot, (2) one shot per storefront/address cluster, (3) a corner shot at intersections.
- **Perimeter-side rule:** Only the market-facing side of perimeter streets is documented (Dundas=north, Bathurst=east, College=south, Spadina=west).
- **Weak clusters:** The consistency report flags large groups of photos sharing a vague label (e.g., 275 rows of "Kensington alley (graffiti wall…)"). These are the highest-value targets for review.

## Common Tasks

- **Check coverage gaps:** Read `csv/kensington_coverage_checklist.txt` or `csv/kensington_fieldwork_punch_list.txt`
- **Look up a photo's location:** Search `csv/photo_address_index.csv` by filename
- **Find uncertain/flagged photos:** Check `csv/photo_address_uncertain.csv` and `csv/photo_address_consistency_report.txt`
- **Plan a fieldwork route:** Refer to `csv/kensington_block_route_checklist.txt` and `csv/kensington_field_card.txt`
- **View a photo:** Use the Read tool on a JPG file in the root directory
- **Run a review batch:** `python csv/build_review.py` generates `csv/review_tool.html`, then open in a browser to review photos grouped by label
- **Apply review corrections:** Merge a `photo_review_corrections*.csv` or `batch*_results.csv` back into `photo_address_index.csv`, updating labels and upgrading confidence sources
