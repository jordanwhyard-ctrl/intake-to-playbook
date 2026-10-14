# Data quality — Software Estate Review — Keystone Advisory

48 raw records from 4 sources merged into 36 accounts.

| Source | Records |
|---|---|
| data/discovery_workbook.csv | 21 |
| data/halcyon_procurement_export.json | 9 |
| data/pemberton_interview_notes.txt | 7 |
| data/license_usage_export.csv | 11 |

## Issues by account

**Smartsheet Business · Brightwater Credit Union** (SW-020)
- could not read renewal_date='TBD' as date
- missing required field 'renewal_date'

**Clio Manage · Pemberton & Rowe LLP** (SW-036)
- 'Clio Manage' not found in reference/isv_catalog.yaml — add it or an alias

## Duplicates merged

- Salesforce Sales Cloud · Northbeam Logistics: 2 records ← Admin-console usage export, Discovery workbook
- Slack Business+ · Northbeam Logistics: 3 records ← Admin-console usage export, Discovery workbook
- Zoom Workplace Business · Northbeam Logistics: 2 records ← Admin-console usage export, Discovery workbook
- Tableau Creator/Viewer · Northbeam Logistics: 2 records ← Admin-console usage export, Discovery workbook
- Asana Business · Northbeam Logistics: 2 records ← Admin-console usage export, Discovery workbook
- Box Business · Brightwater Credit Union: 2 records ← Admin-console usage export, Discovery workbook
- Zoom Workplace Business · Brightwater Credit Union: 2 records ← Admin-console usage export, Discovery workbook
- Okta Workforce Identity · Halcyon Health Group: 2 records ← Admin-console usage export, Halcyon procurement export
- Zendesk Suite · Halcyon Health Group: 2 records ← Admin-console usage export, Halcyon procurement export
- Tableau Creator/Viewer · Halcyon Health Group: 2 records ← Admin-console usage export, Halcyon procurement export
- Dropbox Business · Pemberton & Rowe LLP: 2 records ← Admin-console usage export, Pemberton interview notes
