"""Tests for the shop-knowledge onboarding flow.

Coverage strategy:
- Non-interactive (commit_from_dict / commit_from_yaml) gets full unit
  tests — this is the data-correctness boundary.
- Interactive (run_interactive) is not unit-tested directly because the
  questionary prompts are hard to drive headlessly without ad-hoc mocks
  that would just verify questionary's behavior, not ours. The shared
  commit path is exercised by the dict tests below.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from foreman.installer.onboard_shop import (
    CALLER,
    OnboardResult,
    commit_from_dict,
    commit_from_yaml,
)
from foreman.memory import ForemanMemoryStore


@pytest.fixture
def store(tmp_path: Path) -> ForemanMemoryStore:
    return ForemanMemoryStore(workspace=tmp_path)


# ---------------------------------------------------------------------------
# Smallest viable payload
# ---------------------------------------------------------------------------


class TestSmallestPayload:
    def test_empty_payload_commits_nothing(self, store: ForemanMemoryStore) -> None:
        result = commit_from_dict({}, store)
        assert result.total_records() == 0
        assert result.skipped == []

    def test_only_shop_profile(self, store: ForemanMemoryStore) -> None:
        result = commit_from_dict(
            {"shop_profile": {"manufactures": ["CNC"], "employee_count": 5}},
            store,
        )
        assert result.shop_profile_set is True
        assert store.get_shop_profile().employee_count == 5

    def test_only_one_machine(self, store: ForemanMemoryStore) -> None:
        result = commit_from_dict(
            {
                "equipment": [
                    {
                        "machine_id": "m1",
                        "name": "Mill 1",
                        "envelope": {"axes": 3},
                    }
                ]
            },
            store,
        )
        assert result.equipment_added == 1
        assert store.get_equipment("m1").envelope.axes == 3


# ---------------------------------------------------------------------------
# Full payload — every slot
# ---------------------------------------------------------------------------


def _full_payload() -> dict:
    return {
        "shop_profile": {
            "manufactures": ["precision CNC machining"],
            "certifications": ["AS9100"],
            "capabilities": ["5-axis CNC"],
            "location": "Allentown, PA",
            "employee_count": 12,
            "established_year": 1987,
        },
        "equipment": [
            {
                "machine_id": "haas-vf2",
                "name": "Haas VF-2",
                "manufacturer": "Haas",
                "envelope": {"axes": 3, "max_workpiece_size_mm": 762},
            },
            {
                "machine_id": "haas-umc750",
                "name": "Haas UMC-750",
                "manufacturer": "Haas",
                "envelope": {"axes": 5},
            },
        ],
        "customers": [
            {
                "customer_id": "aerospace",
                "display_name": "Aerospace Customer",
                "email_domains": ["aerospace.com"],
                "payment_terms": "Net 60",
                "payment_behavior": "pays slow",
            }
        ],
        "materials": [
            {"material_code": "6061-T6", "typical_lead_time_days": 3, "scrap_factor": 1.10}
        ],
        "routing_memory": [
            {
                "process": "anodize",
                "material": "6061-T6",
                "trusted_processors": ["AnodizingPro"],
                "typical_turnaround_days": 4,
            }
        ],
        "pricing_corrections": [
            {
                "customer_id": "aerospace",
                "rule_text": "pays slow, +8%",
                "margin_pct_delta": 8.0,
            }
        ],
    }


class TestFullPayload:
    def test_commits_every_slot(self, store: ForemanMemoryStore) -> None:
        result = commit_from_dict(_full_payload(), store)
        assert result.shop_profile_set is True
        assert result.equipment_added == 2
        assert result.customers_added == 1
        assert result.materials_added == 1
        assert result.routing_added == 1
        assert result.pricing_corrections_added == 1
        assert result.skipped == []

    def test_records_actually_in_store(self, store: ForemanMemoryStore) -> None:
        commit_from_dict(_full_payload(), store)
        assert store.get_shop_profile().certifications == ["AS9100"]
        assert len(store.list_equipment()) == 2
        assert store.get_customer("aerospace").payment_behavior == "pays slow"
        assert store.get_material("6061-T6").scrap_factor == 1.10
        assert store.get_routing("anodize", "6061-T6").trusted_processors == ["AnodizingPro"]
        corrections = store.list_pricing_corrections(customer_id="aerospace")
        assert len(corrections) == 1
        assert corrections[0].margin_pct_delta == 8.0


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class TestAuditLog:
    def test_every_record_writes_an_audit_entry(self, store: ForemanMemoryStore) -> None:
        commit_from_dict(_full_payload(), store)
        entries = store.list_audit_entries(caller=CALLER)
        # 1 shop_profile + 2 equipment + 1 customer + 1 material + 1 routing + 1 pricing_correction = 7
        assert len(entries) == 7

    def test_audit_caller_overridable(self, store: ForemanMemoryStore) -> None:
        commit_from_dict(
            {"shop_profile": {"manufactures": ["x"]}},
            store,
            caller="test-suite",
        )
        entries = store.list_audit_entries(caller="test-suite")
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Validation: dangling pricing-correction customer_id
# ---------------------------------------------------------------------------


class TestDanglingReferences:
    def test_pricing_correction_with_unknown_customer_is_skipped(self, store: ForemanMemoryStore) -> None:
        result = commit_from_dict(
            {
                "pricing_corrections": [
                    {
                        "customer_id": "ghost",
                        "rule_text": "this should not commit",
                        "margin_pct_delta": 5.0,
                    }
                ]
            },
            store,
        )
        assert result.pricing_corrections_added == 0
        assert any("ghost" in s for s in result.skipped)
        # Nothing in the store
        assert store.list_pricing_corrections(customer_id="ghost") == []

    def test_pricing_correction_committed_when_customer_added_first(self, store: ForemanMemoryStore) -> None:
        # Same payload but with the customer present
        payload = {
            "customers": [{"customer_id": "real", "display_name": "Real Co."}],
            "pricing_corrections": [
                {
                    "customer_id": "real",
                    "rule_text": "ok",
                    "margin_pct_delta": 3.0,
                }
            ],
        }
        result = commit_from_dict(payload, store)
        assert result.pricing_corrections_added == 1
        assert len(store.list_pricing_corrections(customer_id="real")) == 1


# ---------------------------------------------------------------------------
# Unknown top-level keys are surfaced (not silently dropped)
# ---------------------------------------------------------------------------


class TestUnknownKeys:
    def test_unknown_key_recorded_in_skipped(self, store: ForemanMemoryStore) -> None:
        result = commit_from_dict({"departments": ["sales"]}, store)
        assert any("departments" in s for s in result.skipped)

    def test_underscore_keys_treated_as_metadata(self, store: ForemanMemoryStore) -> None:
        """Keys starting with _ are intentionally tolerated for YAML comment metadata."""
        result = commit_from_dict({"_comment": "anything", "_version": "1"}, store)
        assert result.skipped == []


# ---------------------------------------------------------------------------
# YAML wrapper
# ---------------------------------------------------------------------------


class TestYamlLoader:
    def test_commit_from_yaml_loads_and_commits(self, tmp_path: Path, store: ForemanMemoryStore) -> None:
        path = tmp_path / "shop.yaml"
        path.write_text(yaml.safe_dump(_full_payload()), encoding="utf-8")
        result = commit_from_yaml(path, store)
        assert result.total_records() == 7

    def test_commit_from_yaml_missing_file_raises(self, tmp_path: Path, store: ForemanMemoryStore) -> None:
        with pytest.raises(FileNotFoundError):
            commit_from_yaml(tmp_path / "nope.yaml", store)

    def test_shipped_example_yaml_validates(self, store: ForemanMemoryStore) -> None:
        """The example YAML in installer/defaults/ must round-trip cleanly."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        example = repo_root / "installer" / "defaults" / "shop_knowledge.example.yaml"
        assert example.exists(), f"example YAML missing: {example}"
        result = commit_from_yaml(example, store)
        # shop_profile + 3 equipment + 3 customers + 4 materials + 3 routing + 2 corrections = 16
        assert result.total_records() == 16
        assert result.skipped == []


# ---------------------------------------------------------------------------
# Idempotency: re-running the same payload updates in place, not duplicates
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_re_commit_same_payload_does_not_duplicate_collections(self, store: ForemanMemoryStore) -> None:
        commit_from_dict(_full_payload(), store)
        commit_from_dict(_full_payload(), store)
        # Collections are upserts → no dupes
        assert len(store.list_equipment()) == 2
        assert len(store.list_customers()) == 1
        assert len(store.list_materials()) == 1
        # Pricing corrections ARE additive — second run adds another (different
        # auto-id). This is intentional: re-running onboarding shouldn't lose
        # historical corrections; if you want to replace, reverse the old ones.
        assert len(store.list_pricing_corrections(customer_id="aerospace")) == 2
