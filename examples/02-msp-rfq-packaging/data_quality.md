# Data quality — Quote Request Packaging — Brightline Managed IT

14 raw records from 3 sources merged into 12 accounts.

| Source | Records |
|---|---|
| data/quote_portal.csv | 8 |
| data/intake_inbox.txt | 3 |
| data/partner_referrals.json | 3 |

## Issues by account

**Greenway Property Management** (RFQ-006)
- could not read start_date='ASAP' as date

**Thornton Roofing** (RFQ-009)
- could not read start_date='Q1' as date

## Duplicates merged

- Lakeshore Family Dental: 2 records ← Quote portal, Referral partners
- Ridgeview Precision Machining: 2 records ← Quote portal
