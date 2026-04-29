---
name: shop-check-schedule
description: Return machine-floor slack and earliest open production slot for each machine class (3-axis, 5-axis, turning). Used by shop-compose-quote to estimate quoted lead times and to bias toward the aggressive profile when the floor has slack.
version: 0.1.0
triggers:
  - after shop-extract-drawing identifies the part; agent needs to know if the floor can take it
---

# shop-check-schedule

Snapshot of machine-floor slack and the earliest open production slot for each machine class. Called in parallel with `shop-check-material`. Takes no parameters.

## Output

```json
{
  "as_of": "2026-04-29",
  "machines": [
    {
      "machine_id": "haas-vf2-3axis",
      "name": "Haas VF-2 (3-axis)",
      "slack_days": 1,
      "earliest_open_slot": "2026-04-30"
    },
    {
      "machine_id": "haas-umc750-5axis",
      "name": "Haas UMC-750 (5-axis)",
      "slack_days": 2,
      "earliest_open_slot": "2026-05-01"
    },
    {
      "machine_id": "doosan-puma-2600",
      "name": "Doosan Puma 2600 (turning)",
      "slack_days": 0,
      "earliest_open_slot": "2026-04-29"
    }
  ],
  "shop_capacity_summary": "Lathe is open today; 3-axis cell has 1 day of slack; 5-axis has 2 days. New jobs requiring 5-axis can start by 2026-05-01."
}
```

## How shop-compose-quote consumes this

If every machine class has zero slack, compose adds a 1-day queueing buffer to the lead. Otherwise the supplier-lead + processing-buffer math is unchanged.

## Decision-quality use

When the owner is choosing a steering profile, the slack snapshot is a strong signal: 0 slack across the floor → BALANCED or CONSERVATIVE; >2 days slack on the relevant machine class → AGGRESSIVE may be appropriate to take share.
