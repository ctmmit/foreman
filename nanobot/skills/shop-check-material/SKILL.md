---
name: shop-check-material
description: Return raw-material on-hand inventory and supplier lead time for a given material code. Used by shop-compose-quote to determine the supplier-lead component of the quoted lead time. Phase 3 returns synthetic seed data; production reads from the shop's inventory system.
version: 0.1.0
triggers:
  - after shop-extract-drawing returns a material; agent needs to know if material is on hand
---

# shop-check-material

Look up raw-material inventory on hand and the supplier lead time for a material code. Called in parallel with `shop-check-schedule`.

## Inputs

```json
{"material": "6061-T6"}
```

## Output

```json
{
  "material": "6061-T6",
  "on_hand_units": "1200 in (bar stock, 2.5\" diameter); 18 sheets (12x24x0.25\")",
  "supplier": "Metal Supermarket / Online Metals",
  "supplier_lead_days": 3,
  "preferred_supplier_notes": "Stable; both vendors confirmed in last 90 days.",
  "data_source": "synthetic-seed"
}
```

## How shop-compose-quote consumes this

`supplier_lead_days` becomes the supplier-lead component of the quoted lead time. The compose tool adds a processing buffer on top.

## Behavior on unknown materials

For materials not in the seed set, the tool returns `on_hand_units: "0"`, a 14-day default supplier_lead, and a note that the material needs sourcing. The agent should surface this to the owner before quoting — unknown supply chain is a risk worth flagging.
