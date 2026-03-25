"""Merge photo_review_corrections (6).csv and (19).csv into photo_address_index.csv.

- Only 'reviewed' rows are merged; 'flagged' rows are skipped.
- Corrections (19): updates inferred-cascade -> confirmed
- Corrections (6):  updates verified-visual -> confirmed
- Writes updated index to photo_address_index_merged.csv (does NOT overwrite the original).
- Prints a summary of changes made.
"""

import csv

BASE = 'C:/PHOTOS KENSINGTON/csv/'

# 1. Load corrections into a dict: filename -> new_address
corrections = {}
flagged = []

for corr_file in ['photo_review_corrections (19).csv', 'photo_review_corrections (6).csv']:
    with open(BASE + corr_file, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            fn = row['filename']
            status = row['status']
            if status == 'reviewed':
                corrections[fn] = row['new_address']
            elif status == 'flagged':
                flagged.append((corr_file, fn))

print(f"Loaded {len(corrections)} reviewed corrections, {len(flagged)} flagged (skipped)")

# 2. Read the master index and apply corrections
updated_cascade = 0
updated_visual = 0
unchanged = 0
output_rows = []

with open(BASE + 'photo_address_index.csv', encoding='utf-8') as f:
    reader = csv.reader(f)
    header = next(reader)
    output_rows.append(header)

    for row in reader:
        fn, addr, source = row[0], row[1], row[2]
        if fn in corrections:
            new_addr = corrections[fn]
            if source == 'inferred-cascade':
                updated_cascade += 1
            elif source == 'verified-visual':
                updated_visual += 1
            else:
                unchanged += 1  # unexpected source type, still apply
            output_rows.append([fn, new_addr, 'confirmed'])
        else:
            output_rows.append(row)

# 3. Write merged output
out_path = BASE + 'photo_address_index_merged.csv'
with open(out_path, 'w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerows(output_rows)

print(f"\nMerge complete -> {out_path}")
print(f"  inferred-cascade -> confirmed: {updated_cascade}")
print(f"  verified-visual  -> confirmed: {updated_visual}")
print(f"  other source updated:         {unchanged}")
print(f"  flagged (skipped):            {len(flagged)}")
print(f"  total rows written:           {len(output_rows) - 1}")

if flagged:
    print(f"\nFlagged photos (not merged):")
    for src, fn in flagged:
        print(f"  [{src}] {fn}")
