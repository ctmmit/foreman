---
name: shop-extract-drawing
description: Extract material, tolerances, features, finish, threads, and quantity breaks from a mechanical drawing PDF using a vision-capable LLM. Returns per-field and overall confidence; flags for human review when any tolerance confidence or overall confidence is below 0.95. First step in the foreman-quote-rfq orchestration.
version: 0.1.0
triggers:
  - inbound RFQ with a drawing PDF attached
  - explicit ask to "extract this drawing" or "read this print"
---

# shop-extract-drawing

Read a mechanical engineering drawing PDF and return structured fields (material, tolerances, features, finish, threads, optional quantity breaks). The corresponding tool calls a vision-capable Claude model and returns JSON with per-field confidence.

## When to call

- First tool in the `foreman-quote-rfq` orchestration. Always called before anything else.
- Direct owner request: "what does this drawing say?"

## Inputs

```json
{
  "drawing_path": "demo_1.pdf",        // bare filename, workspace-relative, or absolute
  "customer_id_hint": "boeing"         // optional, for log/trace context only
}
```

The tool resolves bare filenames against `workspace/inbound/`, `workspace/drawings/`, and `workspace/media/inbound/` in that order.

## Output shape

```json
{
  "material": "6061-T6",
  "material_confidence": 0.98,
  "tolerances": [
    {"dimension": "1.250 OD", "value": "±0.005", "confidence": 0.96}
  ],
  "features": ["four through-holes", "M6x1.0 thread", "chamfer 45deg"],
  "finish": "anodize black",
  "threads": ["M6x1.0"],
  "quantity_breaks": null,
  "overall_confidence": 0.96,
  "notes_for_human": "",
  "human_review_required": false,
  "drawing_path": "/abs/path/to/demo_1.pdf",
  "error": null
}
```

## Hard rule: confidence floor

If `overall_confidence < 0.95` OR any tolerance `confidence < 0.95` OR `human_review_required` is true: **stop the orchestration and surface to the owner**. Do not proceed to `shop-compose-quote`. A 0.0005 vs 0.005 tolerance misread scraps a $50K part and ends the pilot.

## Failure modes

- `error: "ANTHROPIC_API_KEY not set"` — set the key or have the owner extract by hand.
- `error: "file not found at <path>"` — drawing is missing; ask the buyer to resend.
- `error: "model returned non-JSON"` — retry once; if it still fails, escalate.

In all error cases, `overall_confidence` is 0.0 and `human_review_required` is true.
