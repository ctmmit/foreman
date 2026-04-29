"""Synthetic seed data for the four mocked retrieval tools.

Used by retrieve_similar_jobs / check_material / check_schedule when no real
ERP adapter is wired up. CLAUDE.md "Limitations" notes this is a Phase One
placeholder; real shops wire ERP via foreman/adapters/erp/ in a later phase.

The seed shape mirrors what a thin ERP adapter would return so swapping in
ProShop / JobBOSS / E2 later is mostly a matter of changing the data source,
not the tool's interface.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Historical jobs (~8 across 3 materials)
# ---------------------------------------------------------------------------

_HISTORICAL_JOBS: list[dict[str, Any]] = [
    # 6061-T6 (aluminum, common)
    {
        "job_id": "J-23-441",
        "material": "6061-T6",
        "customer_id": "aerospace_customer",
        "part_description": "150-pc bracket, 5-axis, ±0.005 tolerance",
        "quantity": 150,
        "unit_price": 32.10,
        "total": 4815.00,
        "lead_days": 7,
        "won": True,
        "completed_at": "2025-09-12",
    },
    {
        "job_id": "J-23-507",
        "material": "6061-T6",
        "customer_id": "aerospace_customer",
        "part_description": "200-pc housing, 3-axis",
        "quantity": 200,
        "unit_price": 28.40,
        "total": 5680.00,
        "lead_days": 9,
        "won": False,
        "completed_at": "2025-10-04",
        "loss_reason": "lost on price; competitor at $24.80",
    },
    {
        "job_id": "J-24-122",
        "material": "6061-T6",
        "customer_id": "industrial_distributor",
        "part_description": "50-pc spacer, simple turn",
        "quantity": 50,
        "unit_price": 18.50,
        "total": 925.00,
        "lead_days": 5,
        "won": True,
        "completed_at": "2026-01-18",
    },
    # 1018 steel
    {
        "job_id": "J-23-389",
        "material": "1018",
        "customer_id": "industrial_distributor",
        "part_description": "300-pc shaft, OD turn + 2 keyways",
        "quantity": 300,
        "unit_price": 14.20,
        "total": 4260.00,
        "lead_days": 8,
        "won": True,
        "completed_at": "2025-08-22",
    },
    {
        "job_id": "J-24-205",
        "material": "1018",
        "customer_id": "ag_equipment",
        "part_description": "75-pc bushing, ±0.002 ID",
        "quantity": 75,
        "unit_price": 22.50,
        "total": 1687.50,
        "lead_days": 6,
        "won": False,
        "completed_at": "2026-02-09",
        "loss_reason": "lost on lead time; customer wanted 3 days",
    },
    # 304 stainless
    {
        "job_id": "J-23-471",
        "material": "304",
        "customer_id": "medical_device_oem",
        "part_description": "60-pc fitting, electropolish, full traceability",
        "quantity": 60,
        "unit_price": 78.00,
        "total": 4680.00,
        "lead_days": 14,
        "won": True,
        "completed_at": "2025-09-30",
    },
    {
        "job_id": "J-24-031",
        "material": "304",
        "customer_id": "medical_device_oem",
        "part_description": "120-pc bracket, mirror finish",
        "quantity": 120,
        "unit_price": 64.20,
        "total": 7704.00,
        "lead_days": 12,
        "won": True,
        "completed_at": "2025-12-05",
    },
    # AISI D-2 tool steel (Bosch demo)
    {
        "job_id": "J-23-512",
        "material": "AISI D-2",
        "customer_id": "bosch_frenos",
        "part_description": "10-pc punch, 60-62 HRC",
        "quantity": 10,
        "unit_price": 245.00,
        "total": 2450.00,
        "lead_days": 18,
        "won": True,
        "completed_at": "2025-11-14",
    },
]


def get_similar_jobs(material: str, customer_id: str, limit: int = 3) -> list[dict[str, Any]]:
    """Top-N historical jobs for material+customer, with at least one loss for benchmarking."""
    matches = [
        j for j in _HISTORICAL_JOBS
        if j["material"].lower() == material.lower()
    ]
    # Sort: customer-match first, then most recent
    customer_match = [j for j in matches if j["customer_id"] == customer_id]
    other_match = [j for j in matches if j["customer_id"] != customer_id]
    customer_match.sort(key=lambda j: j["completed_at"], reverse=True)
    other_match.sort(key=lambda j: j["completed_at"], reverse=True)
    pool = customer_match + other_match

    # Ensure at least one loss in the result if any exists in the pool
    out = pool[:limit]
    if not any(not j["won"] for j in out):
        loss = next((j for j in pool if not j["won"]), None)
        if loss and loss not in out:
            out = out[: limit - 1] + [loss]

    return out


# ---------------------------------------------------------------------------
# Raw-material inventory + supplier lead time
# ---------------------------------------------------------------------------

_INVENTORY: dict[str, dict[str, Any]] = {
    "6061-T6": {
        "on_hand_units": "1200 in (bar stock, 2.5\" diameter); 18 sheets (12x24x0.25\")",
        "supplier": "Metal Supermarket / Online Metals",
        "supplier_lead_days": 3,
        "preferred_supplier_notes": "Stable; both vendors confirmed in last 90 days.",
    },
    "1018": {
        "on_hand_units": "850 in (bar stock, 1.5\" diameter)",
        "supplier": "Online Metals",
        "supplier_lead_days": 4,
        "preferred_supplier_notes": "OK on standard sizes; 2-week minimum on cold-drawn rounds over 4\"",
    },
    "304": {
        "on_hand_units": "60 in (round bar, 1\" diameter); 4 sheets (12x24x0.125\")",
        "supplier": "OnlineMetals + Industrial Metal Supply",
        "supplier_lead_days": 5,
        "preferred_supplier_notes": "OnlineMetals stable; IMS occasionally short on small quantities.",
    },
    "AISI D-2": {
        "on_hand_units": "0 (sourced per-job)",
        "supplier": "Tool Steel Co",
        "supplier_lead_days": 10,
        "preferred_supplier_notes": "Specialty supplier; 2-week minimum, expedite +50%",
    },
}


def get_inventory(material: str) -> dict[str, Any]:
    return _INVENTORY.get(material, {
        "on_hand_units": "0",
        "supplier": "unknown",
        "supplier_lead_days": 14,
        "preferred_supplier_notes": (
            f"No standing supplier for {material}; needs sourcing call. "
            "Default lead estimate is 14 days; confirm before quoting."
        ),
    })


# ---------------------------------------------------------------------------
# Machine schedule (simple slack model)
# ---------------------------------------------------------------------------


def get_schedule_slack(today: date | None = None) -> dict[str, Any]:
    """Return a simple machine-floor slack snapshot.

    For Phase 3 this is fixed: 'we have 2 days of slack on the 5-axis cell,
    1 day on the 3-axis, and the lathe is open.' Real shops wire this from
    their ERP's open-jobs view.
    """
    base = today or date.today()
    earliest_start = base + timedelta(days=2)
    return {
        "as_of": base.isoformat(),
        "machines": [
            {
                "machine_id": "haas-vf2-3axis",
                "name": "Haas VF-2 (3-axis)",
                "slack_days": 1,
                "earliest_open_slot": (base + timedelta(days=1)).isoformat(),
            },
            {
                "machine_id": "haas-umc750-5axis",
                "name": "Haas UMC-750 (5-axis)",
                "slack_days": 2,
                "earliest_open_slot": earliest_start.isoformat(),
            },
            {
                "machine_id": "doosan-puma-2600",
                "name": "Doosan Puma 2600 (turning)",
                "slack_days": 0,
                "earliest_open_slot": base.isoformat(),
            },
        ],
        "shop_capacity_summary": (
            "Lathe is open today; 3-axis cell has 1 day of slack; "
            "5-axis has 2 days. New jobs requiring 5-axis can start by "
            f"{earliest_start.isoformat()}."
        ),
    }
