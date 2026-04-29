"""Shop-knowledge onboarding: populate the ForemanMemoryStore from interview or YAML.

`foreman install` configures Foreman to RUN. `foreman onboard-shop` configures
Foreman to KNOW THIS SHOP. The two are intentionally separate commands because:
- `install` is run once by whoever sets up the box (could be IT, could be a
  consultant); shop-knowledge questions don't fit there.
- `onboard-shop` is run by the owner sitting next to Foreman, with their
  customer list / equipment list / pricing rules to hand. Interactive.

Two execution modes:
- Non-interactive: load a YAML file and commit each section to the store.
  Test-friendly; also the "redeploy a known shop" path.
- Interactive: walk the owner through five sections via questionary, with
  loop-until-done patterns for the collections.

The five sections (in order):
    1. shop_profile (singleton)
    2. equipment[]            — the floor
    3. customers[]            — known buyers (basic seeding only; ERP / email
                                history scan are deferred to roadmap §1)
    4. materials[]            — what you stock and source
    5. routing_memory[]       — trusted outside processors per (process, material)
    6. pricing_corrections[]  — owner's legacy pricing rules

All commits go through the ForemanMemoryStore mutating methods, which means
every entry generates an audit_log entry stamped caller="foreman-onboard-shop".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from foreman.memory import (
    Customer,
    Equipment,
    EquipmentEnvelope,
    ForemanMemoryStore,
    Material,
    PricingCorrection,
    RoutingMemoryEntry,
    ShopProfile,
)


CALLER = "foreman-onboard-shop"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class OnboardResult:
    """What the onboarding committed, for printing back to the owner."""

    shop_profile_set: bool = False
    equipment_added: int = 0
    customers_added: int = 0
    materials_added: int = 0
    routing_added: int = 0
    pricing_corrections_added: int = 0
    skipped: list[str] = field(default_factory=list)

    def total_records(self) -> int:
        return (
            int(self.shop_profile_set)
            + self.equipment_added
            + self.customers_added
            + self.materials_added
            + self.routing_added
            + self.pricing_corrections_added
        )


# ---------------------------------------------------------------------------
# Non-interactive (YAML) path — the testable core
# ---------------------------------------------------------------------------


def commit_from_dict(
    data: dict[str, Any],
    store: ForemanMemoryStore,
    *,
    caller: str = CALLER,
) -> OnboardResult:
    """Commit a shop-knowledge dict to the store. Pure data → audited writes.

    The dict shape is documented in installer/defaults/shop_knowledge.example.yaml.
    Unknown top-level keys are recorded in result.skipped (not an error — the
    spec is permissive so we can grow without breaking existing files).
    """
    result = OnboardResult()

    if "shop_profile" in data and data["shop_profile"] is not None:
        profile = ShopProfile.model_validate(data["shop_profile"])
        store.set_shop_profile(profile, caller=caller)
        result.shop_profile_set = True

    for raw in data.get("equipment", []) or []:
        envelope_raw = raw.pop("envelope", None) if isinstance(raw, dict) else None
        equipment = Equipment.model_validate({
            **raw,
            "envelope": EquipmentEnvelope.model_validate(envelope_raw or {}),
        })
        store.upsert_equipment(equipment, caller=caller)
        result.equipment_added += 1

    for raw in data.get("customers", []) or []:
        customer = Customer.model_validate(raw)
        store.upsert_customer(customer, caller=caller)
        result.customers_added += 1

    for raw in data.get("materials", []) or []:
        material = Material.model_validate(raw)
        store.upsert_material(material, caller=caller)
        result.materials_added += 1

    for raw in data.get("routing_memory", []) or []:
        entry = RoutingMemoryEntry.model_validate(raw)
        store.upsert_routing(entry, caller=caller)
        result.routing_added += 1

    for raw in data.get("pricing_corrections", []) or []:
        # Validate customer_id exists; skip-and-warn on dangling refs so a
        # typo doesn't quietly create a correction the recall path will never
        # match.
        customer_id = raw.get("customer_id")
        if customer_id and store.get_customer(customer_id) is None:
            result.skipped.append(
                f"pricing_correction with unknown customer_id={customer_id!r} "
                f"(rule={raw.get('rule_text', '')!r}); add the customer first"
            )
            continue
        correction = PricingCorrection.model_validate({
            **raw,
            "correction_id": raw.get("correction_id", ""),
            "created_by": raw.get("created_by", caller),
        })
        store.append_pricing_correction(correction, caller=caller)
        result.pricing_corrections_added += 1

    # Surface unknown top-level keys for visibility.
    known = {
        "shop_profile",
        "equipment",
        "customers",
        "materials",
        "routing_memory",
        "pricing_corrections",
    }
    for key in data:
        if key not in known and not key.startswith("_"):
            result.skipped.append(f"unknown top-level key: {key!r}")

    return result


def commit_from_yaml(
    path: str | Path,
    store: ForemanMemoryStore,
    *,
    caller: str = CALLER,
) -> OnboardResult:
    """Convenience wrapper: load YAML, then commit_from_dict."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"shop-knowledge YAML not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return commit_from_dict(data, store, caller=caller)


# ---------------------------------------------------------------------------
# Interactive interview
# ---------------------------------------------------------------------------


def run_interactive(store: ForemanMemoryStore) -> OnboardResult:
    """Interactive owner interview. Returns OnboardResult.

    Imports questionary lazily so non-interactive callers don't pay for the
    dependency; same pattern as installer/wizard.py.
    """
    import questionary

    print()
    print("Foreman shop-knowledge onboarding.")
    print("This populates the personality store with what Foreman needs to know")
    print("about your shop, customers, materials, and pricing rules. Every")
    print("answer can be edited later; nothing is sent anywhere.")
    print()

    data: dict[str, Any] = {}

    if questionary.confirm("Set up shop profile (1 minute)?", default=True).ask():
        data["shop_profile"] = _prompt_shop_profile(questionary)

    if questionary.confirm("Add equipment (machines on the floor)?", default=True).ask():
        data["equipment"] = _loop_collection("machine", _prompt_equipment, questionary)

    if questionary.confirm("Add customers (you can ERP-import later)?", default=True).ask():
        data["customers"] = _loop_collection("customer", _prompt_customer, questionary)

    if questionary.confirm("Add materials you stock or commonly source?", default=True).ask():
        data["materials"] = _loop_collection("material", _prompt_material, questionary)

    if questionary.confirm(
        "Add routing memory (trusted outside processors per process+material)?",
        default=True,
    ).ask():
        data["routing_memory"] = _loop_collection("routing entry", _prompt_routing, questionary)

    if questionary.confirm(
        "Seed pricing corrections (owner's standing rules per customer)?",
        default=True,
    ).ask():
        data["pricing_corrections"] = _loop_collection(
            "pricing correction", _prompt_pricing_correction, questionary
        )

    return commit_from_dict(data, store)


# ---------------------------------------------------------------------------
# Interactive sub-prompts (each returns a dict suitable for commit_from_dict)
# ---------------------------------------------------------------------------


def _loop_collection(noun: str, prompt_fn, q) -> list[dict[str, Any]]:
    """Loop a per-item prompt until the owner says done."""
    items: list[dict[str, Any]] = []
    while True:
        item = prompt_fn(q)
        if item is None:
            break
        items.append(item)
        if not q.confirm(f"Add another {noun}?", default=False).ask():
            break
    return items


def _split_csv(s: str | None) -> list[str]:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def _prompt_shop_profile(q) -> dict[str, Any]:
    return {
        "manufactures": _split_csv(q.text(
            "What does the shop manufacture? (comma-separated, e.g., 'precision CNC machining, tool & die')",
        ).ask()),
        "certifications": _split_csv(q.text(
            "Certifications? (e.g., 'AS9100, ISO 9001, ITAR registered')",
        ).ask()),
        "capabilities": _split_csv(q.text(
            "Capabilities? (e.g., '5-axis CNC, Swiss turning, EDM')",
        ).ask()),
        "location": q.text("Location? (free-form, e.g., 'Allentown, PA')").ask() or None,
        "employee_count": _opt_int(q.text("Employee count? (number, blank to skip)").ask()),
        "established_year": _opt_int(q.text("Established year? (e.g., 1987, blank to skip)").ask()),
        "notes": q.text("Notes? (anything else worth knowing)").ask() or "",
    }


def _prompt_equipment(q) -> dict[str, Any] | None:
    name = q.text("Machine name? (e.g., 'Haas VF-2'; blank to stop adding)").ask()
    if not name:
        return None
    machine_id = q.text(
        "Machine id? (slug, e.g., 'haas-vf2'; blank = auto from name)",
    ).ask() or _slugify(name)
    manufacturer = q.text("Manufacturer? (e.g., Haas; blank to skip)").ask() or None
    model = q.text("Model? (e.g., VF-2; blank to skip)").ask() or None
    axes = _opt_int(q.text("Axes? (3, 4, 5; blank to skip)").ask())
    max_size = _opt_float(q.text("Max workpiece size in mm? (blank to skip)").ask())
    tolerance = q.text("Tolerance class? (e.g., '±0.005' or 'IT6'; blank to skip)").ask() or None
    tooling = _split_csv(q.text(
        "Tooling? (comma-separated, e.g., 'live tooling, sub-spindle')",
    ).ask())
    notes = q.text("Notes?").ask() or ""
    return {
        "machine_id": machine_id,
        "name": name,
        "manufacturer": manufacturer,
        "model": model,
        "envelope": {
            "axes": axes,
            "max_workpiece_size_mm": max_size,
            "tolerance_class": tolerance,
            "tooling": tooling,
        },
        "notes": notes,
    }


def _prompt_customer(q) -> dict[str, Any] | None:
    name = q.text("Customer name? (e.g., 'Boeing Frenos S.A.'; blank to stop)").ask()
    if not name:
        return None
    customer_id = q.text(
        "Customer id? (slug; blank = auto from name)",
    ).ask() or _slugify(name)
    return {
        "customer_id": customer_id,
        "display_name": name,
        "aliases": _split_csv(q.text("Alternate names / aliases? (comma-separated)").ask()),
        "email_domains": _split_csv(q.text(
            "Email domains they own? (e.g., 'boeing.com, boeing.com.mx')",
        ).ask()),
        "email_addresses": _split_csv(q.text(
            "Specific contact addresses? (comma-separated, optional)",
        ).ask()),
        "payment_terms": q.text("Payment terms? (e.g., 'Net 30')").ask() or None,
        "payment_behavior": q.text(
            "Payment behavior? (e.g., 'pays slow', 'always on time')",
        ).ask() or None,
        "quality_expectations": q.text("Quality expectations?").ask() or None,
        "certifications_required": _split_csv(q.text(
            "Certifications required by them? (comma-separated)",
        ).ask()),
        "notes": q.text("Notes?").ask() or "",
    }


def _prompt_material(q) -> dict[str, Any] | None:
    code = q.text("Material code? (e.g., '6061-T6'; blank to stop)").ask()
    if not code:
        return None
    return {
        "material_code": code,
        "preferred_suppliers": _split_csv(q.text(
            "Preferred suppliers? (comma-separated)",
        ).ask()),
        "typical_lead_time_days": _opt_int(q.text("Typical supplier lead time in days?").ask()),
        "scrap_factor": _opt_float(q.text(
            "Scrap factor? (e.g., 1.10 for 10% buffer; default 1.0)",
        ).ask()) or 1.0,
        "margin_default_pct": _opt_float(q.text(
            "Default margin override percent? (blank to skip)",
        ).ask()),
        "notes": q.text("Notes?").ask() or "",
    }


def _prompt_routing(q) -> dict[str, Any] | None:
    process = q.text(
        "Process? (e.g., 'heat-treat', 'anodize'; blank to stop)",
    ).ask()
    if not process:
        return None
    material = q.text("Material? (e.g., '6061-T6')").ask() or ""
    if not material:
        return None
    return {
        "process": process,
        "material": material,
        "trusted_processors": _split_csv(q.text(
            "Trusted processors for this combo? (comma-separated)",
        ).ask()),
        "typical_turnaround_days": _opt_int(q.text("Typical turnaround in days?").ask()),
        "quality_outcomes": q.text(
            "Quality outcomes / notes? (free-form)",
        ).ask() or "",
    }


def _prompt_pricing_correction(q) -> dict[str, Any] | None:
    customer_id = q.text(
        "Customer id this rule applies to? (must match a customer added above; blank to stop)",
    ).ask()
    if not customer_id:
        return None
    rule_text = q.text(
        'Rule in your own words? (e.g., "Boeing pays slow, add 8%")',
    ).ask() or ""
    margin = _opt_float(q.text(
        "Margin adjustment in percentage points? (e.g., 8 for +8%; blank if none)",
    ).ask())
    lead = _opt_int(q.text(
        "Lead-time adjustment in days? (e.g., 2 for +2; blank if none)",
    ).ask())
    if margin in (None, 0) and lead in (None, 0):
        print("  (Skipped: a correction with no margin OR lead change has no effect.)")
        return None
    return {
        "customer_id": customer_id,
        "rule_text": rule_text,
        "margin_pct_delta": margin,
        "lead_delta_days": lead,
        "context_key": q.text(
            'Context key? (e.g., "default", "rush_orders"; blank = "default")',
        ).ask() or "default",
        "applies_when": q.text(
            'Applies when? (e.g., "always", "first 6 months"; blank = "always")',
        ).ask() or "always",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _opt_int(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(s.strip())
    except ValueError:
        logger.warning("not an integer: {!r}; treating as null", s)
        return None


def _opt_float(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s.strip())
    except ValueError:
        logger.warning("not a number: {!r}; treating as null", s)
        return None


def _slugify(s: str) -> str:
    out = []
    last_dash = False
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
            last_dash = False
        elif not last_dash:
            out.append("-")
            last_dash = True
    return "".join(out).strip("-")
