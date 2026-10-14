# Data quality — Inbound Lead Routing — Cobalt Ops

21 raw records from 3 sources merged into 18 accounts.

| Source | Records |
|---|---|
| data/web_form.csv | 12 |
| data/event_badge_scans.json | 5 |
| data/inbound_emails.txt | 4 |

## Issues by account

**Leo Martins** (LEAD-004)
- missing required field 'company'

**Stonebridge Insurance** (LEAD-017)
- could not read budget='TBD' as money

**Kai** (LEAD-018)
- missing required field 'company'

## Duplicates merged

- Harborline Freight Inc.: 2 records ← Website demo form
- Varda Capital: 2 records ← OpsSummit badge scans, Website demo form
- Meridian Health Network: 2 records ← OpsSummit badge scans, Website demo form
