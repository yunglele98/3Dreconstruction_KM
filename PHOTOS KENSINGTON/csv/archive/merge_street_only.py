import csv

CORR = 'C:/Users/liam1/DOWNLOADS/MASTERLIST/DATA/photo_review_street_only_corrections (1).csv'
BASE = 'C:/PHOTOS KENSINGTON/csv/'

corrections = {}
flagged_count = 0
with open(CORR, encoding='utf-8') as f:
    for row in csv.DictReader(f):
        if row['status'] == 'reviewed':
            corrections[row['filename']] = row['new_address']
        elif row['status'] == 'flagged':
            flagged_count += 1

rows_out = []
updated = 0
with open(BASE + 'photo_address_index_merged.csv', encoding='utf-8') as f:
    reader = csv.reader(f)
    header = next(reader)
    rows_out.append(header)
    for row in reader:
        if row[0] in corrections:
            row[1] = corrections[row[0]]
            row[2] = 'confirmed'
            updated += 1
        rows_out.append(row)

with open(BASE + 'photo_address_index_merged.csv', 'w', encoding='utf-8', newline='') as f:
    csv.writer(f).writerows(rows_out)

total = len(rows_out) - 1
cascade = sum(1 for r in rows_out[1:] if r[2] == 'inferred-cascade')
confirmed = sum(1 for r in rows_out[1:] if r[2] == 'confirmed')
print('Merged %d reviewed corrections (%d flagged, skipped)' % (updated, flagged_count))
print('Total: %d | Confirmed: %d | Inferred-cascade: %d' % (total, confirmed, cascade))
