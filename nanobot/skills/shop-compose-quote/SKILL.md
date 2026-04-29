---
name: shop-compose-quote
description: Synthesize the final draft quote object from the upstream tool outputs (extraction, comparable jobs, inventory, schedule, recalled personality). Pricing math is deterministic and auditable. Returns the structured quote per skills/foreman-quote-rfq/SKILL.md spec, with human_approval_required always true.
version: 0.1.0
triggers:
  - last step of the foreman-quote-rfq orchestration, after the upstream five tools
---

# shop-compose-quote

The orchestrator's final step. Takes the structured outputs of the previous five tools and produces the draft quote the owner reviews.

## Pricing math (deterministic, auditable)

```
baseline_unit_price = median( comparable_jobs.unit_price WHERE won )
                      OR mean( comparable_jobs.unit_price ) if no wons

steering_margin_pct = profile.margin_pct_delta            // -8 / 0 / +15
steering_lead       = profile.lead_delta_days             // -1 / 0 / +3

personality_margin_pct = sum( corrections.margin_pct_delta )
personality_lead       = sum( corrections.lead_delta_days )

final_unit_price = baseline_unit_price * (1 + (steering_margin_pct + personality_margin_pct) / 100)
final_total      = final_unit_price * quantity

baseline_lead    = supplier_lead_days + 4 (+ 1 if every machine class has 0 slack)
final_lead_days  = max(1, baseline_lead + steering_lead + personality_lead)
```

Every input is explicit; the math trace is included in the output's `reasoning.math` field.

## Inputs

```json
{
  "material": "6061-T6",
  "quantity": 150,
  "customer_id": "aerospace_customer",
  "profile_name": "balanced",            // conservative / balanced / aggressive
  "comparable_jobs": [...],              // from shop-retrieve-similar-jobs.jobs
  "material_inventory": {...},           // from shop-check-material
  "machine_schedule": {...},             // from shop-check-schedule
  "personality_corrections": [...],      // from shop-recall-personality.corrections
  "extraction_notes": "...",             // optional, from shop-extract-drawing.notes_for_human
  "due_date": "2026-05-15"               // optional ISO date
}
```

## Output

```json
{
  "quote": {
    "unit_price": 31.00,
    "total": 4650.00,
    "lead_days": 7,
    "currency": "USD",
    "confidence": 0.85
  },
  "reasoning": {
    "baseline_source": "median_of_2_won_jobs",
    "baseline_unit_price": 32.10,
    "profile": {"name": "balanced", "display_label": "Book rate", ...},
    "comparable_jobs": [...],
    "personality_applied": [
      {"correction_id": "F-1018", "rule_text": "...", "applied_delta": {"margin_pct": 8.0}}
    ],
    "math": "Baseline unit price (median_of_2_won_jobs): $32.10\n..."
  },
  "clarifying_questions": [...],
  "human_approval_required": true,
  "meets_due_date": true,
  "context": {...}
}
```

## Hard rules

- `human_approval_required` is always `true`. Phase One non-negotiable: the agent never sends a quote autonomously, regardless of caller. The orchestrator surfaces the draft to the owner inbox.
- If `personality_corrections` is non-empty AND the cumulative deltas come out to zero, compose includes a `warning` in the corresponding `personality_applied` entry. Citing feedback without moving the number is the kind of bug that breaks owner trust.
- If no comparable jobs exist for the material, compose returns `status: "escalate"` instead of guessing a price. Ask the owner for a manual estimate.

## Conservative-profile clarifying question

When `profile_name="conservative"`, compose always includes a clarifying question prompting the owner to confirm tolerances, finish, and any non-standard callouts before sending. Per profile.always_ask_clarifying.
