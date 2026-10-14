# Play: Renewal negotiation

*Software Estate Review — Keystone Advisory · 4 product line(s)*

**Objective:** Benchmark price and terms on a large renewal and negotiate on the customer's behalf for a share of the savings.

**Owner:** Advisory lead · **SLA:** Benchmark within 10 business days · **Success metric:** Savings of 10%+ against the vendor's first renewal quote

## Target product lines (highest priority first)

| Product Line | Customer | Score | Band | Renewal | Package | Value | Flags |
|---|---|---|---|---|---|---|---|
| [Microsoft 365 E3 · Brightwater Credit Union](../lines/SW-013-microsoft-365-e3-brightwater-credit-unio.md) | Brightwater Credit Union | 50 | High | 2027-03-31 | Negotiation advisory | $5,450 | 0 |
| [Microsoft 365 E3 · Northbeam Logistics](../lines/SW-002-microsoft-365-e3-northbeam-logistics.md) | Northbeam Logistics | 45 | Medium | 2027-06-30 | Negotiation advisory | $11,025 | 0 |
| [Microsoft 365 E5 · Halcyon Health Group](../lines/SW-021-microsoft-365-e5-halcyon-health-group.md) | Halcyon Health Group | 45 | Medium | 2027-06-30 | Negotiation advisory | $45,150 | 0 |
| [ServiceNow ITSM · Halcyon Health Group](../lines/SW-024-servicenow-itsm-halcyon-health-group.md) | Halcyon Health Group | 45 | Medium | 2027-09-30 | Negotiation advisory | $14,400 | 0 |

**Pipeline in this play: $76,025**

## Sequence

| When | Channel | Action |
|---|---|---|
| Day 0 | Email | Ask {customer} for the current {product} order form and any renewal quote received |
| Day 5 | Internal | Benchmark ${cost_per_license}/license/yr against comparable deals; list alternatives ({alternatives}) |
| Day 10 | Meeting | Negotiation plan with {exec_contact}: targets, walk-away, timeline |
| Day 15 | Email | Open negotiation with {vendor} well before {renewal_date} |

## Talk track (template)

- At ${annual_spend} a year, a 10–15% improvement on {product} is worth about ${negotiation_savings}. Credible alternatives ({alternatives}) are what move the vendor.

## Discovery questions

1. What did the last renewal increase look like?
2. Are there modules or SKUs nobody uses?
3. Would a longer term be acceptable for better pricing?

## Objection handling

**"We can negotiate ourselves."**  
Sure. We bring benchmark data from other deals and we're paid only from the savings we get.

## Assets to send

- Benchmark summary
- Negotiation plan template
