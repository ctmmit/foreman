---
name: shop-retrieve-similar-jobs
description: Return the top-N historical jobs for a given material and customer, with at least one loss when one exists in the pool. Used by shop-compose-quote to establish a baseline unit price from comparable wons. Phase 3 returns synthetic seed data; production wires this to the shop's ERP.
version: 0.1.0
triggers:
  - after shop-extract-drawing returns a material; the agent needs comparable history
---

# shop-retrieve-similar-jobs

Look up historical jobs that match the extracted material and the resolved customer. Returns at most N (default 3) jobs, customer-matching first. The result is guaranteed to include at least one LOSS when one exists in the pool, so the agent has a competitive benchmark instead of only won-bid optimism.

## When to call

- Step 2 of `foreman-quote-rfq` orchestration, immediately after `shop-extract-drawing` returned a material with acceptable confidence.
- Independently when the owner asks "what have we quoted for X recently?"

## Inputs

```json
{
  "material": "6061-T6",            // from shop-extract-drawing.material
  "customer_id": "aerospace_customer",
  "limit": 3                        // optional, default 3, max 10
}
```

## Output

```json
{
  "material": "6061-T6",
  "customer_id": "aerospace_customer",
  "match_count": 3,
  "jobs": [
    {"job_id": "J-23-441", "won": true, "unit_price": 32.10, "lead_days": 7, ...},
    {"job_id": "J-23-507", "won": false, "loss_reason": "lost on price; competitor at $24.80", ...}
  ],
  "data_source": "synthetic-seed",
  "note": "..."
}
```

## How shop-compose-quote consumes this

The agent passes the entire `jobs` array to compose. Compose computes the baseline unit price as the median of won jobs (or mean of all comparables if no wons exist).

## Phase 3 limitation

`data_source: "synthetic-seed"` means the underlying records are about 8 fixed jobs across 6061-T6, 1018, 304, and AISI D-2. Phase 2 of the broader Foreman roadmap wires a real ERP adapter (ProShop / JobBOSS / E2 / Global Shop) without changing this tool's interface.
