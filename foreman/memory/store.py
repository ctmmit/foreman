"""ForemanMemoryStore: structured personality slots on top of nanobot's MemoryStore.

The parent (nanobot.agent.memory.MemoryStore) handles free-form memory:
history.jsonl, MEMORY.md, SOUL.md, USER.md. We add per-slot CRUD for the
seven Foreman personality slots, with audit-log-on-write at the data layer
so an audit entry cannot be forgotten.

Storage layout under workspace/personality/:
    shop_profile.json           (singleton, optional)
    equipment.json              (dict[machine_id -> Equipment])
    customers.json              (dict[customer_id -> Customer])
    materials.json              (dict[material_code -> Material])
    routing_memory.json         (dict["{process}|{material}" -> RoutingMemoryEntry])
    pricing_corrections.json    (dict[correction_id -> PricingCorrection])
    audit_log.jsonl             (append-only; one AuditEntry per line)

Atomic writes use temp-file + os.replace so a crashed mid-write leaves the
prior good copy intact, not a half-written JSON.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from foreman.memory.models import (
    AuditEntry,
    AuditOperation,
    Customer,
    Equipment,
    Material,
    PricingCorrection,
    RoutingMemoryEntry,
    ShopProfile,
)
from nanobot.agent.memory import MemoryStore
from nanobot.utils.helpers import ensure_dir


# ---------------------------------------------------------------------------
# File names — single source of truth
# ---------------------------------------------------------------------------

_SHOP_PROFILE_FILE = "shop_profile.json"
_EQUIPMENT_FILE = "equipment.json"
_CUSTOMERS_FILE = "customers.json"
_MATERIALS_FILE = "materials.json"
_ROUTING_FILE = "routing_memory.json"
_PRICING_FILE = "pricing_corrections.json"
_AUDIT_FILE = "audit_log.jsonl"


def _routing_key(process: str, material: str) -> str:
    return f"{process}|{material}"


# ---------------------------------------------------------------------------
# ForemanMemoryStore
# ---------------------------------------------------------------------------


class ForemanMemoryStore(MemoryStore):
    """Adds Foreman personality slots to nanobot's MemoryStore.

    Construction is identical to the parent. The personality directory is
    created lazily on first write to avoid making empty dirs on every agent
    bootstrap.
    """

    def __init__(self, workspace: Path, max_history_entries: int = MemoryStore._DEFAULT_MAX_HISTORY) -> None:
        super().__init__(workspace, max_history_entries=max_history_entries)
        self.personality_dir = workspace / "personality"

    # -- file I/O helpers ---------------------------------------------------

    def _path(self, name: str) -> Path:
        return self.personality_dir / name

    def _ensure_dir(self) -> None:
        ensure_dir(self.personality_dir)

    def _load_dict(self, name: str) -> dict[str, Any]:
        path = self._path(name)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load {}: {}; treating as empty.", path, e)
            return {}

    def _save_dict(self, name: str, data: dict[str, Any]) -> None:
        """Atomic write: tmp file + os.replace."""
        self._ensure_dir()
        path = self._path(name)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, path)

    # -- audit log ----------------------------------------------------------

    def append_audit_entry(self, entry: AuditEntry) -> None:
        """Append a single audit entry. Public so hooks and external callers can use it."""
        self._ensure_dir()
        path = self._path(_AUDIT_FILE)
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def _audit(
        self,
        *,
        caller: str,
        slot: str,
        operation: AuditOperation,
        target_id: str | None,
        delta_summary: str,
        delta_payload: dict[str, Any] | None = None,
    ) -> None:
        """Internal: write an audit entry as part of a mutating operation."""
        entry = AuditEntry(
            entry_id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            caller=caller,
            slot=slot,
            operation=operation,
            target_id=target_id,
            delta_summary=delta_summary,
            delta_payload=delta_payload or {},
        )
        self.append_audit_entry(entry)

    def list_audit_entries(
        self,
        *,
        limit: int = 100,
        slot: str | None = None,
        caller: str | None = None,
    ) -> list[AuditEntry]:
        """Read recent audit entries, newest first.

        Filters are applied in-memory; the audit log is small (one line per
        write) so this is cheap until a single shop has millions of corrections,
        which is far beyond Phase One scope.
        """
        path = self._path(_AUDIT_FILE)
        if not path.exists():
            return []
        entries: list[AuditEntry] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(AuditEntry.model_validate_json(line))
                except Exception:
                    continue
        entries.reverse()
        if slot:
            entries = [e for e in entries if e.slot == slot]
        if caller:
            entries = [e for e in entries if e.caller == caller]
        return entries[:limit]

    # -- shop profile (singleton) -------------------------------------------

    def get_shop_profile(self) -> ShopProfile | None:
        path = self._path(_SHOP_PROFILE_FILE)
        if not path.exists():
            return None
        try:
            return ShopProfile.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load shop_profile: {}", e)
            return None

    def set_shop_profile(self, profile: ShopProfile, *, caller: str) -> None:
        """Full replace; equivalent to upsert for a singleton."""
        self._ensure_dir()
        path = self._path(_SHOP_PROFILE_FILE)
        existed = path.exists()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)
        self._audit(
            caller=caller,
            slot="shop_profile",
            operation="update" if existed else "insert",
            target_id=None,
            delta_summary=f"{'Updated' if existed else 'Created'} shop profile.",
            delta_payload=profile.model_dump(),
        )

    # -- equipment (collection) ---------------------------------------------

    def list_equipment(self) -> dict[str, Equipment]:
        raw = self._load_dict(_EQUIPMENT_FILE)
        return {k: Equipment.model_validate(v) for k, v in raw.items()}

    def get_equipment(self, machine_id: str) -> Equipment | None:
        raw = self._load_dict(_EQUIPMENT_FILE).get(machine_id)
        return Equipment.model_validate(raw) if raw else None

    def upsert_equipment(self, equipment: Equipment, *, caller: str) -> None:
        data = self._load_dict(_EQUIPMENT_FILE)
        existed = equipment.machine_id in data
        data[equipment.machine_id] = equipment.model_dump(mode="json")
        self._save_dict(_EQUIPMENT_FILE, data)
        self._audit(
            caller=caller,
            slot="equipment",
            operation="update" if existed else "insert",
            target_id=equipment.machine_id,
            delta_summary=f"{'Updated' if existed else 'Added'} equipment '{equipment.name}'.",
            delta_payload=equipment.model_dump(mode="json"),
        )

    # -- customers (collection) ---------------------------------------------

    def list_customers(self) -> dict[str, Customer]:
        raw = self._load_dict(_CUSTOMERS_FILE)
        return {k: Customer.model_validate(v) for k, v in raw.items()}

    def get_customer(self, customer_id: str) -> Customer | None:
        raw = self._load_dict(_CUSTOMERS_FILE).get(customer_id)
        return Customer.model_validate(raw) if raw else None

    def upsert_customer(self, customer: Customer, *, caller: str) -> None:
        data = self._load_dict(_CUSTOMERS_FILE)
        existed = customer.customer_id in data
        data[customer.customer_id] = customer.model_dump(mode="json")
        self._save_dict(_CUSTOMERS_FILE, data)
        self._audit(
            caller=caller,
            slot="customers",
            operation="update" if existed else "insert",
            target_id=customer.customer_id,
            delta_summary=f"{'Updated' if existed else 'Added'} customer '{customer.display_name}'.",
            delta_payload=customer.model_dump(mode="json"),
        )

    # -- materials (collection) ---------------------------------------------

    def list_materials(self) -> dict[str, Material]:
        raw = self._load_dict(_MATERIALS_FILE)
        return {k: Material.model_validate(v) for k, v in raw.items()}

    def get_material(self, material_code: str) -> Material | None:
        raw = self._load_dict(_MATERIALS_FILE).get(material_code)
        return Material.model_validate(raw) if raw else None

    def upsert_material(self, material: Material, *, caller: str) -> None:
        data = self._load_dict(_MATERIALS_FILE)
        existed = material.material_code in data
        data[material.material_code] = material.model_dump(mode="json")
        self._save_dict(_MATERIALS_FILE, data)
        self._audit(
            caller=caller,
            slot="materials",
            operation="update" if existed else "insert",
            target_id=material.material_code,
            delta_summary=f"{'Updated' if existed else 'Added'} material '{material.material_code}'.",
            delta_payload=material.model_dump(mode="json"),
        )

    # -- routing memory (collection) ----------------------------------------

    def list_routing(self) -> dict[str, RoutingMemoryEntry]:
        raw = self._load_dict(_ROUTING_FILE)
        return {k: RoutingMemoryEntry.model_validate(v) for k, v in raw.items()}

    def get_routing(self, process: str, material: str) -> RoutingMemoryEntry | None:
        key = _routing_key(process, material)
        raw = self._load_dict(_ROUTING_FILE).get(key)
        return RoutingMemoryEntry.model_validate(raw) if raw else None

    def upsert_routing(self, entry: RoutingMemoryEntry, *, caller: str) -> None:
        data = self._load_dict(_ROUTING_FILE)
        key = _routing_key(entry.process, entry.material)
        existed = key in data
        data[key] = entry.model_dump(mode="json")
        self._save_dict(_ROUTING_FILE, data)
        self._audit(
            caller=caller,
            slot="routing_memory",
            operation="update" if existed else "insert",
            target_id=key,
            delta_summary=(
                f"{'Updated' if existed else 'Added'} routing for "
                f"{entry.process} on {entry.material}."
            ),
            delta_payload=entry.model_dump(mode="json"),
        )

    # -- pricing corrections (collection) -----------------------------------

    def list_pricing_corrections(
        self,
        *,
        customer_id: str | None = None,
        active_only: bool = True,
    ) -> list[PricingCorrection]:
        """Return matching corrections, newest first."""
        raw = self._load_dict(_PRICING_FILE)
        out: list[PricingCorrection] = []
        for v in raw.values():
            try:
                c = PricingCorrection.model_validate(v)
            except Exception:
                continue
            if customer_id and c.customer_id != customer_id:
                continue
            if active_only and not c.is_active:
                continue
            out.append(c)
        out.sort(key=lambda c: c.created_at, reverse=True)
        return out

    def get_pricing_correction(self, correction_id: str) -> PricingCorrection | None:
        raw = self._load_dict(_PRICING_FILE).get(correction_id)
        return PricingCorrection.model_validate(raw) if raw else None

    def append_pricing_correction(self, correction: PricingCorrection, *, caller: str) -> None:
        """Append a new correction. Caller is responsible for setting correction_id."""
        if not correction.correction_id:
            correction.correction_id = str(uuid.uuid4())
        data = self._load_dict(_PRICING_FILE)
        if correction.correction_id in data:
            raise ValueError(
                f"correction_id {correction.correction_id} already exists; "
                "use reverse_pricing_correction to supersede."
            )
        data[correction.correction_id] = correction.model_dump(mode="json")
        self._save_dict(_PRICING_FILE, data)
        self._audit(
            caller=caller,
            slot="pricing_corrections",
            operation="insert",
            target_id=correction.correction_id,
            delta_summary=(
                f"Added pricing correction for {correction.customer_id} "
                f"(context={correction.context_key}): {correction.rule_text}"
            ),
            delta_payload=correction.model_dump(mode="json"),
        )

    def reverse_pricing_correction(
        self,
        correction_id: str,
        *,
        caller: str,
        reversed_by_correction_id: str | None = None,
    ) -> None:
        """Mark a prior correction as reversed. Does not edit; sets reversal fields."""
        data = self._load_dict(_PRICING_FILE)
        if correction_id not in data:
            raise KeyError(f"correction_id {correction_id} not found")
        existing = PricingCorrection.model_validate(data[correction_id])
        if existing.reversed_at is not None:
            raise ValueError(f"correction_id {correction_id} is already reversed")
        existing.reversed_at = datetime.now()
        existing.reversed_by_correction_id = reversed_by_correction_id
        data[correction_id] = existing.model_dump(mode="json")
        self._save_dict(_PRICING_FILE, data)
        self._audit(
            caller=caller,
            slot="pricing_corrections",
            operation="reverse",
            target_id=correction_id,
            delta_summary=(
                f"Reversed pricing correction {correction_id} for "
                f"{existing.customer_id}."
            ),
            delta_payload={
                "reversed_at": existing.reversed_at.isoformat(),
                "reversed_by_correction_id": reversed_by_correction_id,
            },
        )
