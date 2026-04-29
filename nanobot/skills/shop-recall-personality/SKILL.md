---
name: shop-recall-personality
description: Retrieve prior owner pricing corrections for a given customer. Always called before shop-compose-quote. If matches are non-empty, the agent MUST translate each correction's rule_text into numeric deltas (margin_pct_delta, lead_delta_days) and pass them to compose so the displayed price actually moves in sync with the cited feedback.
version: 0.1.0
triggers:
  - before every call to shop-compose-quote
  - when the owner asks "what have I told you about this customer?"
---

# shop-recall-personality

Read the active pricing corrections for a customer from the personality store (the `ForemanMemoryStore`-backed slot). Called before every quote so the LLM sees the owner's prior corrections and applies them to the current quote.

## When to call

- Step 4 of `foreman-quote-rfq` orchestration. Always called.
- Direct owner request: "what corrections do I have for Boeing?"

## Inputs

```json
{
  "customer_id": "aerospace_customer",   // resolved upstream
  "context_key": "rush_orders",          // optional discriminator
  "include_inactive": false              // default false: only active corrections
}
```

## Hard rule: customer-id confidence

The upstream customer-id resolver MUST have returned confidence ≥ 0.9 before this tool is called. If the resolver flagged escalate=True, surface candidates to the owner and wait. Wrong customer → wrong recalled feedback → wrong margin applied. Worst possible failure mode (CLAUDE.md non-negotiable #4).

## Output

```json
{
  "customer_id": "aerospace_customer",
  "customer_known": true,
  "customer_display_name": "Aerospace Customer",
  "context_key": null,
  "match_count": 1,
  "corrections": [
    {
      "correction_id": "F-1018",
      "rule_text": "They always pay slow. Add 8 percent.",
      "margin_pct_delta": 8.0,
      "lead_delta_days": null,
      "applies_when": "always",
      "is_active": true
    }
  ]
}
```

## How shop-compose-quote consumes this

Pass `corrections` through verbatim as `personality_corrections` to compose. Compose sums the `margin_pct_delta` and `lead_delta_days` across all corrections and applies them to the quote, ON TOP of the steering profile delta.

## Hard rule: cite OR don't apply (no in-between)

If you cite a correction in the quote's reasoning field but pass `margin_pct_delta=0, lead_delta_days=0` for it, the displayed price will not move. That breaks owner trust ("you said you applied my correction but the number didn't change"). Either translate the rule into real deltas or do not cite it.
