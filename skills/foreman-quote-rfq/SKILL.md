---
name: foreman-quote-rfq
description: Produce a draft quote for an inbound machine-shop RFQ. Reads the drawing, retrieves comparable historical jobs, checks material inventory and machine schedule in parallel, recalls prior owner feedback for the customer, composes a steered draft quote with personality deltas applied, and persists any subsequent owner correction. Wraps the seven shop-* sub-skills as one callable capability. Returns a structured quote the owner reviews and sends. Never sends autonomously.
version: 0.1.0
triggers:
  - inbound RFQ email with a drawing attachment
  - explicit ask to "quote this part" or "price this drawing"
  - external agent calls foreman-quote-rfq(drawing, customer, quantity, profile) via MCP (Phase Three)
inputs:
  drawing: path or URL to a single-part drawing (PDF, DWG, or scan)
  customer: customer identifier resolved by upstream email-id resolution
  quantity: integer
  profile: conservative | balanced | aggressive (default: balanced)
  due_date: optional ISO date the buyer requested
outputs:
  quote: { unit_price, total, lead_days, currency, confidence }
  reasoning: structured trace citing recalled feedback, comparable jobs, schedule slack, math
  clarifying_questions: list of items to confirm with the buyer before sending
  human_approval_required: true
---

# Foreman: quote an inbound RFQ

The public quoting capability of Foreman. A caller (the inbound-email handler, the owner via CLI, or in Phase Three a partner shop's agent over MCP) hands the LLM agent a drawing, a customer, and a quantity. This SKILL.md is the orchestration recipe: it tells the agent which Python tools to call, in what order, and how to combine their results. The agent loop produces a draft quote. The owner clicks send. Nothing leaves the shop without that click.

## How this skill is wired

This SKILL.md is the LLM-facing guide. The seven `shop-*` capabilities it references are **registered Python tools** in `foreman/tools/` (see `foreman/tools/__init__.py` for the registry). Nanobot's `SkillsLoader` summarizes available skills in the agent's system prompt; when the agent decides to follow this recipe, it `read_file`s the SKILL.md and then calls each tool through nanobot's tool-call protocol. There is no subprocess execution — every step below is the agent issuing a structured tool call to a Python function.

## When to use

An RFQ arrives by email with a drawing attached. The owner pastes a drawing path into chat and says "quote this." A partner shop's Foreman calls this skill with a policy-gated permission grant.

## When NOT to use

The drawing is for an assembly or BOM, not a single part: escalate to owner. The customer is not in the personality store and the inbound email identity is ambiguous: escalate before guessing. Drawing-extraction confidence on tolerance fields is below the configured floor (default 0.95): return the partial extraction with `confidence: low` and let the owner correct before quoting. Any field implies regulated work the shop is not certified for (ITAR-flagged, AS9100-required customer when the shop has no certification): refuse and notify owner.

## How it works

The agent calls the seven `shop-*` tools in this fixed order. The order matters: every tool before `shop-compose-quote` exists to load the context that compose needs.

1. **`shop-extract-drawing`** — drawing to structured schema (material, tolerances, features, finish, threads, quantity breaks if present), with a per-field confidence. If confidence on tolerance fields is below the configured floor (default 0.95), halt the loop and surface the partial extraction to the owner. Do not proceed to compose.
2. **`shop-retrieve-similar-jobs`** — top-3 historical jobs for material plus customer, including at least one loss for benchmark pricing.
3. **`shop-check-material` and `shop-check-schedule`** — call in parallel (the agent issues both tool calls in one turn). Returns raw-material inventory, supplier lead time, machine slack, and earliest available production slot.
4. **`shop-recall-personality`** — customer-gated retrieval of prior owner feedback. Always called. If matches are non-empty, pass the raw matches to compose AND translate each one into numeric deltas before calling compose:
   - "add 8%" / "+8%" / "pays slow, bump margin" → `margin_pct=8`
   - "give 2 extra days" / "never rush them" → `lead_delta_days=+2`
   - "tighten by 10% to keep them" → `margin_pct=-10`
   If feedback is cited but deltas are zero, the displayed price will not move. That breaks owner trust. Do not do it.
5. **`shop-compose-quote`** — final draft under the requested steering profile, with personality deltas applied on top of the profile-chosen base. Returns the structured quote object below.

## After the loop: the learning hook

If the owner replies to the draft with a correction, preference, or rule ("too high", "add 8% for this customer", "never quote under $Y"), call **`shop-remember-feedback`** immediately. No "remember this" instruction required. The tool writes through `ForemanMemoryStore.append_pricing_correction()` and the corresponding `audit_log` entry is created automatically by the `after_iteration` AgentHook. The correction is retrievable on the next matching RFQ via `shop-recall-personality`. This is the hero behavior. Verify it works end-to-end before declaring the skill ready in any deployment.

## Steering profiles

Set in `~/.foreman/config.yaml` under `agents.quoting.profile`. The owner flips it at any time via the CLI or WebUI; the change takes effect on the next RFQ. Same drawing under three profiles produces visibly different quotes; on the hero demo (150-piece 6061 bracket) the swing is roughly $1,070.

| Profile | Use when |
|---|---|
| `conservative` (Hold the line) | New customer, tight tolerances, mixed units, capacity tight |
| `balanced` (Book rate) | Default. Established customer, normal job. |
| `aggressive` (Win it) | Slack on the floor, want to take share, willing to undercut |

Stored personality deltas apply on top of the steering-chosen base. Steering sets the curve, personality bends it.

## Returned quote shape

```json
{
  "quote": {
    "unit_price": 31.00,
    "total": 4650.00,
    "lead_days": 7,
    "currency": "USD",
    "confidence": 0.9
  },
  "reasoning": {
    "extraction": { "material": "6061-T6", "tolerances": [], "finish": null },
    "comparable_jobs": [
      { "job_id": "J-23-441", "won": true, "unit_price": 32.10 },
      { "job_id": "J-23-507", "won": false, "unit_price": 28.40 }
    ],
    "personality_applied": [
      {
        "feedback_id": "F-1018",
        "rule": "Aerospace customer pays slow, +8% margin",
        "applied_delta": { "margin_pct": 8 }
      }
    ],
    "math": "neutral $63.75/u → +8% margin → $68.85/u"
  },
  "clarifying_questions": [
    "Confirm tolerance ±0.005 on the 1.250 dimension (drawing shows ambiguous callout)."
  ],
  "human_approval_required": true
}
```

## Hard rules

- `human_approval_required` is always true in Phase One. The skill never sends a quote autonomously, regardless of caller. The orchestrating agent surfaces the draft to the owner inbox.
- Every personality write goes through the audit log with caller identity, timestamp, and the delta applied. The owner can reverse any entry. The agent's authority comes from being correctable.
- Drawings never leave the deployment boundary. Outbound traffic from this skill is restricted to the LLM provider and (optionally) the drawing-extraction service named in `policies/default.yaml`. No silent upload of customer drawings to anything else.
- If customer-id resolution is ambiguous (same buyer from two domains, RFQ forwarded by an assistant, broker-relayed), ask the owner to resolve before calling `shop-recall-personality`. Wrong customer retrieves the wrong feedback applies the wrong margin. Worst possible failure mode.

## Examples

### Example 1: standard quote

```bash
foreman quote --drawing demo_1.pdf \
  --customer "Aerospace Customer" \
  --quantity 150 \
  --profile balanced
```

Returns: $31.00/unit, $4,650 total, 7 days, confidence 0.9, no clarifying questions.

### Example 2: real Bosch drawing (Spanish, AISI D-2 tool steel)

```bash
foreman quote --drawing bosch-punzon.pdf \
  --customer "Bosch Frenos" \
  --quantity 8 \
  --profile conservative
```

Reads the pre-staged extraction, notices the 60-62 HRC hardness spec, asks a clarifying question on ambiguous tolerance markings, quotes with the conservative-profile cushion applied.

### Example 3: the learning loop end-to-end

```bash
# t=0: initial quote, no prior feedback for this customer
foreman quote --drawing demo_1.pdf --customer "Aerospace Customer" --quantity 150
# → $31.00/u

# t=1: owner correction (any prose works)
foreman feedback --customer "Aerospace Customer" \
  --note "They always pay slow. Add 8 percent."
# Skill calls shop-remember-feedback. Persisted to personality.jsonl.

# t=2: a different drawing for the same customer
foreman quote --drawing demo_3.pdf --customer "Aerospace Customer" --quantity 80
# → $68.85/u (was $63.75 neutral, +8% applied)
# Reasoning cites the earlier feedback verbatim and shows the math.
```

## Configuration

What the agent and the seven tools read at runtime:

- `~/.foreman/config.yaml` → `agents.quoting.profile` — default steering profile (`conservative` / `balanced` / `aggressive`) when the caller does not pass one.
- `~/.foreman/config.yaml` → `providers.<name>` — LLM provider config (Anthropic / OpenAI / Ollama / vLLM); see [`nanobot/providers/factory.py`](https://github.com/HKUDS/nanobot/blob/main/nanobot/providers/factory.py).
- `personality/` directory under the persistent volume — structured slots managed by `ForemanMemoryStore` (subclass of nanobot's `MemoryStore`). Holds `customers/`, `pricing_corrections/`, `audit_log.jsonl`, etc.
- The active `policies/*.yaml` (one of `managed-cloud.yaml` / `single-tenant-cloud.yaml` / `on-prem.yaml`) — outbound network allowlist and the `outbound_send.require_human_approval: true` gate.
- The seven `shop-*` Python tools must be registered with the agent in `foreman/tools/__init__.py`. The skill fails closed if any are missing at startup.

## Test set

Every change to this skill or any of the seven sub-skills must pass:

- 20 real drawings with hand-labeled tolerance fields, scored on precision and recall against the configured floor.
- 5 multilingual drawings (Spanish minimum; German and Japanese as added).
- 5 owner-correction round-trips: correction persisted, recalled on the next matching RFQ, cited in reasoning, numeric delta applied.
- 1 ambiguous customer-id case: must escalate, must not guess.
- 1 below-confidence-floor case: must escalate to owner, must not quote.

## Naming

The seven granular tools use the `shop-*` prefix because they are the building blocks the agent composes during a quote. This meta-skill uses the `foreman-*` prefix because it is the orchestration recipe and, in Phase Three, the publicly MCP-exposed surface that external callers (a buyer's procurement agent, a partner shop's Foreman) invoke. `shop-*` is the kitchen, `foreman-*` is the menu.
