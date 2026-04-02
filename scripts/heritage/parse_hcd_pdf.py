#!/usr/bin/env python3
"""Parse HCD PDF Vol. 2 — extract per-building heritage statements.

Reads the pre-extracted PDF text from outputs/heritage/hcd_pdf_pages.json
and parses Appendix D (Statements of Contribution) into structured per-building
records with address, sub_area, typology, construction_date, and full statement.

Usage:
    python scripts/heritage/parse_hcd_pdf.py
    python scripts/heritage/parse_hcd_pdf.py --output outputs/heritage/hcd_parsed.json
"""
import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).parent.parent.parent


def normalize_address(raw):
    """Normalize HCD address to match params filename convention.

    '187 AUGUSTA AVENUE' -> '187 Augusta Ave'
    '145 & 147 AUGUSTA AVENUE' -> ['145 Augusta Ave', '147 Augusta Ave']
    '175, 177, & 179 AUGUSTA AVENUE' -> ['175 Augusta Ave', '177 Augusta Ave', '179 Augusta Ave']
    """
    raw = raw.strip()
    # Common street suffix normalization
    suffix_map = {
        "AVENUE": "Ave", "STREET": "St", "PLACE": "Pl",
        "LANE": "Lane", "TERRACE": "Ter", "COURT": "Ct",
        "ROAD": "Rd", "DRIVE": "Dr", "CRESCENT": "Cres",
    }

    # Extract street name (last 1-2 words, all caps)
    # Pattern: numbers + street name
    parts = raw.split()
    # Find where the street name starts (first fully uppercase word after numbers)
    street_start = 0
    for i, p in enumerate(parts):
        if p.replace(",", "").replace("&", "").isdigit() or p in ("&", ","):
            continue
        if p[0].isdigit():
            continue
        street_start = i
        break

    street_parts = parts[street_start:]
    number_part = " ".join(parts[:street_start])

    # Normalize street name
    street_words = []
    for w in street_parts:
        w_upper = w.upper().rstrip(",.")
        if w_upper in suffix_map:
            street_words.append(suffix_map[w_upper])
        elif w_upper in ("&", "AND"):
            continue
        else:
            street_words.append(w.title())
    street_name = " ".join(street_words)

    # Parse multiple addresses: "145 & 147", "175, 177, & 179"
    number_part = number_part.replace("&", ",")
    numbers = [n.strip().rstrip(",") for n in number_part.split(",") if n.strip().rstrip(",")]
    # Filter out empty and non-numeric-ish
    numbers = [n for n in numbers if n and (n[0].isdigit() or n[0] in "ABCDEFG")]

    if not numbers:
        # Single address with no parseable number
        return [raw.title()]

    addresses = []
    for num in numbers:
        addr = f"{num} {street_name}"
        addresses.append(addr)

    return addresses


def parse_building_entry(text):
    """Parse a single building entry from the Statement of Contribution text."""
    entry = {}

    # Character Sub-Area
    m = re.search(r"Character Sub-Area:\s*(.+?)(?:\n|$)", text)
    if m:
        entry["sub_area"] = m.group(1).strip()

    # Typology
    m = re.search(r"Typology:\s*(.+?)(?:\n|$)", text)
    if m:
        entry["typology"] = m.group(1).strip()

    # Construction Date
    m = re.search(r"Construction Date:\s*(.+?)(?:\n|$)", text)
    if m:
        entry["construction_date"] = m.group(1).strip()

    # Statement of Contribution (everything after the label)
    m = re.search(r"Statement of Contribution:\s*(.+)", text, re.DOTALL)
    if m:
        stmt = m.group(1).strip()
        # Clean up line breaks within the statement
        stmt = re.sub(r"\s*\n\s*", " ", stmt)
        # Remove page headers that got mixed in
        stmt = re.sub(r"APPENDIX D:.*?(?:JANUARY )?20\d{2}\s*\d*\s*", "", stmt)
        stmt = re.sub(r"CITY OF TORONTO\s*", "", stmt)
        stmt = stmt.strip()
        entry["statement"] = stmt

    return entry


def parse_all_pages(pages_data):
    """Parse all pages of Appendix D into building records."""
    pages = pages_data["pages"]
    buildings = {}

    # Concatenate all Appendix D pages (starts around page 15)
    full_text = ""
    for pg_num in sorted(pages.keys(), key=int):
        text = pages[pg_num]
        if "STATEMENTS OF CONTRIBUTION" in text or int(pg_num) >= 15:
            # Strip page headers
            cleaned = re.sub(
                r"APPENDIX D: STATEMENTS OF CONTRIBUTION \| KENSINGTON MARKET HCD PLAN\s*",
                "", text)
            cleaned = re.sub(r"CITY OF TORONTO\s*JANUARY 2025\s*", "", cleaned)
            cleaned = re.sub(r"^\d+\s*$", "", cleaned, flags=re.MULTILINE)
            full_text += cleaned + "\n"

    # Split by address patterns (NUMBER(S) STREET in ALL CAPS)
    # Pattern: line that looks like "187 AUGUSTA AVENUE" or "145 & 147 AUGUSTA AVENUE"
    entry_pattern = re.compile(
        r"^((?:\d+[A-Z]?\s*(?:,\s*)?(?:&\s*)?)+[A-Z][A-Z\s]+(?:AVENUE|STREET|PLACE|LANE|TERRACE|COURT|ROAD|DRIVE|CRESCENT))\s*$",
        re.MULTILINE
    )

    matches = list(entry_pattern.finditer(full_text))

    for i, match in enumerate(matches):
        raw_address = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        body = full_text[start:end].strip()

        if not body or "Character Sub-Area" not in body:
            continue

        entry = parse_building_entry(body)
        entry["raw_address"] = raw_address

        # Normalize to individual addresses
        addresses = normalize_address(raw_address)
        for addr in addresses:
            buildings[addr] = {**entry, "normalized_address": addr}

    return buildings


def main():
    parser = argparse.ArgumentParser(description="Parse HCD PDF Vol. 2")
    parser.add_argument("--input", type=Path,
                        default=REPO / "outputs" / "heritage" / "hcd_pdf_pages.json")
    parser.add_argument("--output", type=Path,
                        default=REPO / "outputs" / "heritage" / "hcd_parsed.json")
    args = parser.parse_args()

    pages_data = json.loads(args.input.read_text(encoding="utf-8"))
    buildings = parse_all_pages(pages_data)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(buildings, indent=2, ensure_ascii=False), encoding="utf-8")

    # Stats
    sub_areas = {}
    typologies = {}
    for b in buildings.values():
        sa = b.get("sub_area", "unknown")
        sub_areas[sa] = sub_areas.get(sa, 0) + 1
        ty = b.get("typology", "unknown")
        typologies[ty] = typologies.get(ty, 0) + 1

    print(f"Parsed {len(buildings)} building entries from {pages_data['total_pages']} pages")
    print(f"\nSub-areas:")
    for sa, count in sorted(sub_areas.items(), key=lambda x: -x[1]):
        print(f"  {sa}: {count}")
    print(f"\nTop typologies:")
    for ty, count in sorted(typologies.items(), key=lambda x: -x[1])[:10]:
        print(f"  {ty}: {count}")


if __name__ == "__main__":
    main()
