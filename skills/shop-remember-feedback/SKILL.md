---
name: shop-remember-feedback
description: Persist an owner correction (margin and/or lead-time adjustment) for a customer. Called automatically when the owner replies to a draft quote with a correction, preference, or rule. The correction is retrievable via shop-recall-personality on the next matching RFQ.
version: 0.1.0
triggers:
  - the owner replies to a draft quote with a correction in plain English
    ("too low", "add X% for this customer", "never quote under $Y", etc.)
  - direct owner instruction "remember this", "save this rule", "from now on..."
---

# shop-remember-feedback

The write side of the hero learning loop. Persists an owner correction to the personality store via `ForemanMemoryStore.append_pricing_correction()`. Every write also creates an audit-log entry — the audit happens at the data layer; you cannot skip it.

## When to call

The hero behavior: as soon as you recognize the owner's reply contains a correction, preference, or rule, call this tool. Do NOT wait for the owner to say "remember this." Examples that trigger:

- "Too low — they pay slow, add 8%."
- "Never quote rush orders for this customer; we always lose money."
- "Boeing wants 30-day payment, not 60. Bake in 5% to cover the float."
- "Pricing is fine but always quote Tuesday delivery — they expect it."

## Inputs

```json
{
  "customer_id": "aerospace_customer",
  "rule_text": "They always pay slow. Add 8 percent.",
  "margin_pct_delta": 8.0,           // null if the correction doesn't affect margin
  "lead_delta_days": null,           // null if the correction doesn't affect lead
  "context_key": "default",          // optional, default "default"
  "applies_when": "always"           // optional, default "always"
}
```

## Hard rule: don't store no-op corrections

If both `margin_pct_delta` and `lead_delta_days` are zero or null, the tool REJECTS the call with `status: "rejected"`. A correction that doesn't move price OR lead can't be applied; ask the owner what they want changed before calling again.

## Output

```json
{
  "status": "stored",
  "correction_id": "<uuid>",
  "customer_id": "aerospace_customer",
  "rule_text": "They always pay slow. Add 8 percent.",
  "applied_delta": {"margin_pct_delta": 8.0, "lead_delta_days": null},
  "context_key": "default",
  "applies_when": "always",
  "note": "..."
}
```

After storing, confirm to the owner in plain English: "Saved. Next quote for Aerospace Customer will include +8% margin and cite this correction." Do not re-quote automatically — the owner asked you to remember, not to redo.
