"""Pydantic models for the seven Foreman personality slots.

Slot taxonomy (from CLAUDE.md → Personality store schema):
    shop_profile          — singleton: what the shop manufactures
    equipment             — collection: machines on the floor
    customers             — collection (keyed by customer_id)
    materials             — collection (keyed by material_code)
    routing_memory        — collection (keyed by process+material)
    pricing_corrections   — collection (keyed by correction_id)
    audit_log             — append-only: one entry per personality write
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Shop profile (singleton)
# ---------------------------------------------------------------------------


class ShopProfile(BaseModel):
    """What the shop manufactures, how it positions itself.

    Set once during onboarding; updated rarely.
    """

    model_config = ConfigDict(extra="forbid")

    manufactures: list[str] = Field(
        default_factory=list,
        description='What the shop produces, e.g., ["precision CNC machining", "tool & die"].',
    )
    certifications: list[str] = Field(
        default_factory=list,
        description='Held certifications, e.g., ["AS9100", "ISO 9001", "ITAR registered"].',
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description='Capability tags, e.g., ["5-axis CNC", "Swiss turning", "EDM"].',
    )
    location: str | None = Field(default=None, description="Geographic position, free-form.")
    employee_count: int | None = Field(default=None, ge=0)
    established_year: int | None = Field(default=None, ge=1800)
    notes: str = ""


# ---------------------------------------------------------------------------
# Equipment (collection)
# ---------------------------------------------------------------------------


class EquipmentEnvelope(BaseModel):
    """Capability envelope for a single machine."""

    model_config = ConfigDict(extra="forbid")

    max_workpiece_size_mm: float | None = Field(default=None, gt=0)
    axes: int | None = Field(default=None, ge=2, le=12)
    tolerance_class: str | None = Field(default=None, description='e.g., "IT6", "±0.005"')
    tooling: list[str] = Field(default_factory=list)


class Equipment(BaseModel):
    """A single machine on the shop floor."""

    model_config = ConfigDict(extra="forbid")

    machine_id: str = Field(description="Stable shop-internal identifier.")
    name: str
    manufacturer: str | None = None
    model: str | None = None
    envelope: EquipmentEnvelope = Field(default_factory=EquipmentEnvelope)
    notes: str = ""


# ---------------------------------------------------------------------------
# Customer (collection)
# ---------------------------------------------------------------------------


class Customer(BaseModel):
    """A customer of the shop."""

    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(description="Stable internal id (slug).")
    display_name: str = Field(description='Human-readable name, e.g., "Boeing Frenos S.A."')
    aliases: list[str] = Field(
        default_factory=list,
        description="Alternate names used in correspondence; used by resolver fuzzy match.",
    )
    email_domains: list[str] = Field(
        default_factory=list,
        description='Owned email domains, e.g., ["boeing.com", "boeing.com.mx"].',
    )
    email_addresses: list[str] = Field(
        default_factory=list,
        description="Specific contacts at the customer; used by resolver exact-address match.",
    )
    payment_terms: str | None = Field(default=None, description='e.g., "Net 30", "Net 60", "COD".')
    payment_behavior: str | None = Field(
        default=None,
        description='Owner-observed behavior, e.g., "pays slow", "always on time".',
    )
    quality_expectations: str | None = None
    certifications_required: list[str] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# Material (collection)
# ---------------------------------------------------------------------------


class Material(BaseModel):
    """A material the shop sources or uses."""

    model_config = ConfigDict(extra="forbid")

    material_code: str = Field(description='e.g., "6061-T6", "AISI D-2", "316L".')
    preferred_suppliers: list[str] = Field(default_factory=list)
    typical_lead_time_days: int | None = Field(default=None, ge=0)
    scrap_factor: float = Field(
        default=1.0,
        ge=1.0,
        le=2.0,
        description="Multiplier on raw material to cover waste, e.g., 1.10 = 10% buffer.",
    )
    margin_default_pct: float | None = Field(
        default=None,
        description="Default margin override for this material, in percent (e.g., 22.5).",
    )
    notes: str = ""


# ---------------------------------------------------------------------------
# Routing memory (collection)
# ---------------------------------------------------------------------------


class RoutingMemoryEntry(BaseModel):
    """Outside-process routing knowledge for a (process, material) combination."""

    model_config = ConfigDict(extra="forbid")

    process: str = Field(description='e.g., "heat-treat", "anodize", "passivate", "grinding".')
    material: str = Field(description='Matches Material.material_code.')
    trusted_processors: list[str] = Field(
        default_factory=list,
        description="Suppliers known to handle this combination well.",
    )
    typical_turnaround_days: int | None = Field(default=None, ge=0)
    quality_outcomes: str = Field(default="", description="Free-form owner notes.")


# ---------------------------------------------------------------------------
# Pricing correction (collection)
# ---------------------------------------------------------------------------


class PricingCorrection(BaseModel):
    """An owner override on prior quoting behavior, persisted by shop-remember-feedback.

    The hero learning loop reads these via shop-recall-personality on every
    matching RFQ and applies the deltas to the composed quote.

    Reversal model: corrections are never edited in place. To reverse one, the
    owner issues a new correction that nulls or overrides the prior delta;
    `reversed_at` and `reversed_by_correction_id` link the chain.
    """

    model_config = ConfigDict(extra="forbid")

    correction_id: str = Field(description="UUID-style unique id.")
    customer_id: str = Field(description="Foreign key into customers.")
    context_key: str = Field(
        default="default",
        description='Discriminator within a customer, e.g., "default", "rush_orders", "below_$5k".',
    )
    rule_text: str = Field(
        description='The owner\'s verbatim prose, e.g., "Boeing pays slow, add 8%".',
    )
    margin_pct_delta: float | None = Field(
        default=None,
        description="Margin adjustment in percentage points (e.g., 8.0 means +8% margin).",
    )
    lead_delta_days: int | None = Field(
        default=None,
        description="Lead-time adjustment in days (e.g., 2 means +2 days).",
    )
    applies_when: str = Field(
        default="always",
        description='Free-form scope, e.g., "always", "first 6 months", "rush orders only".',
    )
    created_at: datetime = Field(default_factory=datetime.now)
    created_by: str = Field(
        description='Caller identity, e.g., "shop-remember-feedback" or "owner-cli".',
    )
    reversed_at: datetime | None = None
    reversed_by_correction_id: str | None = None

    @property
    def is_active(self) -> bool:
        return self.reversed_at is None


# ---------------------------------------------------------------------------
# Audit log (append-only)
# ---------------------------------------------------------------------------


AuditOperation = Literal["insert", "update", "reverse", "delete"]


class AuditEntry(BaseModel):
    """One personality write, one audit entry. Append-only.

    Reversal of a prior write is itself a new audit entry (operation="reverse"),
    not an edit. The owner can trace any change through the chain.
    """

    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(description="UUID-style unique id.")
    timestamp: datetime = Field(default_factory=datetime.now)
    caller: str = Field(
        description='Tool name or hook that triggered the write, e.g., "shop-remember-feedback".',
    )
    slot: str = Field(
        description='Slot name written, e.g., "customers", "pricing_corrections".',
    )
    operation: AuditOperation
    target_id: str | None = Field(
        default=None,
        description='Key into the slot (customer_id, material_code, correction_id, etc.).',
    )
    delta_summary: str = Field(
        description='Human-readable summary, e.g., "Added pricing correction +8% for Boeing".',
    )
    delta_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw delta for forensics; not surfaced to the LLM by default.",
    )
