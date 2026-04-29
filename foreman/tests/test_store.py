"""Tests for ForemanMemoryStore: CRUD, audit-log-on-write, atomic writes, reversal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> ForemanMemoryStore:
    """Fresh store rooted in a per-test tmp workspace."""
    return ForemanMemoryStore(workspace=tmp_path)


def _sample_customer(customer_id: str = "boeing") -> Customer:
    return Customer(
        customer_id=customer_id,
        display_name="Boeing Co.",
        aliases=["Boeing", "The Boeing Company"],
        email_domains=["boeing.com"],
        email_addresses=["buyer@boeing.com"],
        payment_terms="Net 60",
        payment_behavior="pays slow",
    )


def _sample_correction(customer_id: str = "boeing", rule: str = "pays slow, +8%") -> PricingCorrection:
    return PricingCorrection(
        correction_id="",  # store generates if empty
        customer_id=customer_id,
        rule_text=rule,
        margin_pct_delta=8.0,
        created_by="shop-remember-feedback",
    )


# ---------------------------------------------------------------------------
# Personality directory creation is lazy
# ---------------------------------------------------------------------------


def test_personality_dir_not_created_until_first_write(store: ForemanMemoryStore) -> None:
    assert not store.personality_dir.exists()
    assert store.list_customers() == {}
    assert not store.personality_dir.exists()  # reads should not create the dir


def test_personality_dir_created_on_first_write(store: ForemanMemoryStore) -> None:
    store.upsert_customer(_sample_customer(), caller="test")
    assert store.personality_dir.is_dir()


# ---------------------------------------------------------------------------
# Shop profile (singleton)
# ---------------------------------------------------------------------------


def test_shop_profile_round_trip(store: ForemanMemoryStore) -> None:
    assert store.get_shop_profile() is None

    profile = ShopProfile(
        manufactures=["precision CNC machining"],
        certifications=["AS9100", "ISO 9001"],
        location="Pennsylvania, US",
        employee_count=12,
    )
    store.set_shop_profile(profile, caller="onboarding-wizard")

    loaded = store.get_shop_profile()
    assert loaded is not None
    assert loaded.manufactures == ["precision CNC machining"]
    assert loaded.certifications == ["AS9100", "ISO 9001"]
    assert loaded.employee_count == 12


def test_shop_profile_audit_insert_then_update(store: ForemanMemoryStore) -> None:
    store.set_shop_profile(ShopProfile(manufactures=["CNC"]), caller="onboarding-wizard")
    store.set_shop_profile(ShopProfile(manufactures=["CNC", "EDM"]), caller="owner-cli")

    audit = store.list_audit_entries(slot="shop_profile")
    assert len(audit) == 2
    assert audit[0].operation == "update"  # newest first
    assert audit[0].caller == "owner-cli"
    assert audit[1].operation == "insert"


# ---------------------------------------------------------------------------
# Equipment, customers, materials, routing — collections share the same shape
# ---------------------------------------------------------------------------


def test_customer_upsert_round_trip(store: ForemanMemoryStore) -> None:
    c = _sample_customer()
    store.upsert_customer(c, caller="test")
    loaded = store.get_customer("boeing")
    assert loaded is not None
    assert loaded.display_name == "Boeing Co."
    assert "Boeing" in loaded.aliases


def test_customer_upsert_twice_updates_in_place(store: ForemanMemoryStore) -> None:
    c1 = _sample_customer()
    store.upsert_customer(c1, caller="test")
    c2 = c1.model_copy(update={"payment_behavior": "always on time"})
    store.upsert_customer(c2, caller="test")

    loaded = store.get_customer("boeing")
    assert loaded.payment_behavior == "always on time"
    assert len(store.list_customers()) == 1  # not 2 records


def test_equipment_with_envelope_round_trip(store: ForemanMemoryStore) -> None:
    eq = Equipment(
        machine_id="haas-vf2",
        name="Haas VF-2",
        manufacturer="Haas",
        envelope=EquipmentEnvelope(axes=3, max_workpiece_size_mm=762, tolerance_class="±0.005"),
    )
    store.upsert_equipment(eq, caller="onboarding")
    loaded = store.get_equipment("haas-vf2")
    assert loaded.envelope.axes == 3
    assert loaded.envelope.max_workpiece_size_mm == 762.0


def test_material_and_routing_round_trip(store: ForemanMemoryStore) -> None:
    store.upsert_material(
        Material(material_code="6061-T6", typical_lead_time_days=5, scrap_factor=1.10),
        caller="test",
    )
    store.upsert_routing(
        RoutingMemoryEntry(
            process="anodize",
            material="6061-T6",
            trusted_processors=["AnodizingPro"],
            typical_turnaround_days=4,
        ),
        caller="test",
    )
    assert store.get_material("6061-T6").scrap_factor == 1.10
    routing = store.get_routing("anodize", "6061-T6")
    assert routing is not None
    assert routing.trusted_processors == ["AnodizingPro"]


# ---------------------------------------------------------------------------
# Pricing corrections + reversal
# ---------------------------------------------------------------------------


def test_pricing_correction_append_assigns_id(store: ForemanMemoryStore) -> None:
    c = _sample_correction()
    store.append_pricing_correction(c, caller="shop-remember-feedback")
    assert c.correction_id  # populated by store
    loaded = store.get_pricing_correction(c.correction_id)
    assert loaded is not None
    assert loaded.is_active


def test_pricing_correction_duplicate_id_raises(store: ForemanMemoryStore) -> None:
    c = _sample_correction()
    c.correction_id = "fixed-id"
    store.append_pricing_correction(c, caller="test")
    duplicate = _sample_correction()
    duplicate.correction_id = "fixed-id"
    with pytest.raises(ValueError, match="already exists"):
        store.append_pricing_correction(duplicate, caller="test")


def test_pricing_correction_reverse_marks_inactive(store: ForemanMemoryStore) -> None:
    c = _sample_correction()
    store.append_pricing_correction(c, caller="shop-remember-feedback")
    cid = c.correction_id
    store.reverse_pricing_correction(cid, caller="owner-cli")
    loaded = store.get_pricing_correction(cid)
    assert loaded.reversed_at is not None
    assert not loaded.is_active


def test_pricing_correction_double_reverse_raises(store: ForemanMemoryStore) -> None:
    c = _sample_correction()
    store.append_pricing_correction(c, caller="test")
    store.reverse_pricing_correction(c.correction_id, caller="test")
    with pytest.raises(ValueError, match="already reversed"):
        store.reverse_pricing_correction(c.correction_id, caller="test")


def test_list_pricing_corrections_filters_by_customer_and_active(store: ForemanMemoryStore) -> None:
    a = _sample_correction(customer_id="boeing", rule="A")
    b = _sample_correction(customer_id="boeing", rule="B")
    c = _sample_correction(customer_id="bosch", rule="C")
    for corr in (a, b, c):
        store.append_pricing_correction(corr, caller="test")
    store.reverse_pricing_correction(a.correction_id, caller="test")

    boeing_active = store.list_pricing_corrections(customer_id="boeing", active_only=True)
    assert len(boeing_active) == 1
    assert boeing_active[0].rule_text == "B"

    boeing_all = store.list_pricing_corrections(customer_id="boeing", active_only=False)
    assert len(boeing_all) == 2


# ---------------------------------------------------------------------------
# Audit log — the non-negotiable
# ---------------------------------------------------------------------------


def test_every_mutating_call_writes_an_audit_entry(store: ForemanMemoryStore) -> None:
    store.set_shop_profile(ShopProfile(), caller="t1")
    store.upsert_customer(_sample_customer(), caller="t2")
    store.upsert_equipment(Equipment(machine_id="m", name="M"), caller="t3")
    store.upsert_material(Material(material_code="x"), caller="t4")
    store.upsert_routing(RoutingMemoryEntry(process="p", material="x"), caller="t5")
    c = _sample_correction()
    store.append_pricing_correction(c, caller="t6")
    store.reverse_pricing_correction(c.correction_id, caller="t7")

    entries = store.list_audit_entries()
    assert len(entries) == 7
    callers = {e.caller for e in entries}
    assert callers == {"t1", "t2", "t3", "t4", "t5", "t6", "t7"}


def test_audit_entries_are_newest_first(store: ForemanMemoryStore) -> None:
    store.upsert_customer(_sample_customer("a"), caller="first")
    store.upsert_customer(_sample_customer("b"), caller="second")
    entries = store.list_audit_entries()
    assert entries[0].caller == "second"
    assert entries[1].caller == "first"


def test_audit_log_filter_by_slot(store: ForemanMemoryStore) -> None:
    store.upsert_customer(_sample_customer(), caller="t")
    store.upsert_material(Material(material_code="x"), caller="t")
    customer_entries = store.list_audit_entries(slot="customers")
    assert len(customer_entries) == 1
    assert customer_entries[0].slot == "customers"


# ---------------------------------------------------------------------------
# Atomic writes — file is never half-written
# ---------------------------------------------------------------------------


def test_persisted_files_are_valid_json(store: ForemanMemoryStore) -> None:
    """Atomic write guarantee: every persisted file parses cleanly."""
    store.upsert_customer(_sample_customer(), caller="t")
    store.upsert_material(Material(material_code="x"), caller="t")

    for filename in ("customers.json", "materials.json"):
        path = store.personality_dir / filename
        assert path.exists()
        json.loads(path.read_text(encoding="utf-8"))  # raises if malformed


def test_no_tmp_files_left_after_successful_writes(store: ForemanMemoryStore) -> None:
    store.upsert_customer(_sample_customer(), caller="t")
    leftover_tmps = list(store.personality_dir.glob("*.tmp"))
    assert leftover_tmps == []


# ---------------------------------------------------------------------------
# Parent (nanobot.MemoryStore) features still work
# ---------------------------------------------------------------------------


def test_parent_history_append_still_works(store: ForemanMemoryStore) -> None:
    """Subclassing must not break nanobot's append_history."""
    cursor = store.append_history("hello world")
    assert cursor >= 1
    entries = store.read_unprocessed_history(since_cursor=0)
    assert any(e["content"] == "hello world" for e in entries)
