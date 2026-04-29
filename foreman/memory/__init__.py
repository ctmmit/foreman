"""Foreman memory layer.

Extends nanobot's MemoryStore with structured personality slots specific to a
machine shop: shop_profile, equipment, customers, materials, routing_memory,
pricing_corrections, audit_log.

Public API:
    ForemanMemoryStore — subclass of nanobot.agent.memory.MemoryStore, adds
        per-slot CRUD methods on top of nanobot's free-form history/MEMORY.md.
    Customer, Material, Equipment, ShopProfile, RoutingMemoryEntry,
    PricingCorrection, AuditEntry — Pydantic models for the slots.
    resolve_customer — customer-id lookup with confidence-gated escalation.
"""

from foreman.memory.models import (
    AuditEntry,
    Customer,
    Equipment,
    EquipmentEnvelope,
    Material,
    PricingCorrection,
    RoutingMemoryEntry,
    ShopProfile,
)
from foreman.memory.resolver import CustomerResolution, resolve_customer
from foreman.memory.store import ForemanMemoryStore

__all__ = [
    "AuditEntry",
    "Customer",
    "CustomerResolution",
    "Equipment",
    "EquipmentEnvelope",
    "ForemanMemoryStore",
    "Material",
    "PricingCorrection",
    "RoutingMemoryEntry",
    "ShopProfile",
    "resolve_customer",
]
