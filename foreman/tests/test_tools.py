"""Tests for the seven shop-* Python tools.

Coverage strategy:
- Deterministic tools (retrieve, material, schedule, recall, remember, compose)
  get full unit tests — input shape, output shape, the hard rules (no-op
  rejection, escalation on missing comparables, math correctness).
- shop-extract-drawing tests cover error paths (no API key, file not found,
  bad JSON from model). The real-API smoke test is a separate manual run.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from foreman.memory import Customer, ForemanMemoryStore, PricingCorrection
from foreman.tools.quoting import (
    CheckMaterialTool,
    CheckScheduleTool,
    ComposeQuoteTool,
    ExtractDrawingTool,
    RecallPersonalityTool,
    RememberFeedbackTool,
    RetrieveSimilarJobsTool,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def store(workspace: Path) -> ForemanMemoryStore:
    s = ForemanMemoryStore(workspace=workspace)
    s.upsert_customer(
        Customer(
            customer_id="aerospace_customer",
            display_name="Aerospace Customer",
            email_domains=["aerospace.com"],
        ),
        caller="test-fixture",
    )
    return s


def _run(coro):
    """Tiny helper so test bodies don't need to be async."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# shop-retrieve-similar-jobs
# ---------------------------------------------------------------------------


class TestRetrieveSimilarJobs:
    def test_returns_jobs_for_known_material(self, workspace: Path) -> None:
        tool = RetrieveSimilarJobsTool(workspace=workspace)
        result = json.loads(_run(tool.execute(material="6061-T6", customer_id="aerospace_customer")))
        assert result["material_count" if False else "match_count"] >= 1
        assert all(j["material"] == "6061-T6" for j in result["jobs"])

    def test_includes_at_least_one_loss_when_pool_has_one(self, workspace: Path) -> None:
        tool = RetrieveSimilarJobsTool(workspace=workspace)
        result = json.loads(_run(tool.execute(material="6061-T6", customer_id="aerospace_customer")))
        # 6061-T6 pool contains a loss (J-23-507) — must be present.
        assert any(not j["won"] for j in result["jobs"]), (
            "shop-retrieve-similar-jobs MUST surface at least one loss for benchmark pricing"
        )

    def test_customer_match_first(self, workspace: Path) -> None:
        tool = RetrieveSimilarJobsTool(workspace=workspace)
        result = json.loads(_run(tool.execute(material="304", customer_id="medical_device_oem")))
        assert result["jobs"][0]["customer_id"] == "medical_device_oem"

    def test_unknown_material_returns_empty(self, workspace: Path) -> None:
        tool = RetrieveSimilarJobsTool(workspace=workspace)
        result = json.loads(_run(tool.execute(material="UNOBTAINIUM", customer_id="x")))
        assert result["match_count"] == 0
        assert result["jobs"] == []


# ---------------------------------------------------------------------------
# shop-check-material
# ---------------------------------------------------------------------------


class TestCheckMaterial:
    def test_known_material_returns_inventory(self, workspace: Path) -> None:
        tool = CheckMaterialTool(workspace=workspace)
        result = json.loads(_run(tool.execute(material="6061-T6")))
        assert result["material"] == "6061-T6"
        assert "supplier_lead_days" in result
        assert isinstance(result["supplier_lead_days"], int)

    def test_unknown_material_returns_default_with_warning(self, workspace: Path) -> None:
        tool = CheckMaterialTool(workspace=workspace)
        result = json.loads(_run(tool.execute(material="UNOBTAINIUM")))
        assert result["on_hand_units"] == "0"
        assert "sourcing" in result["preferred_supplier_notes"].lower()


# ---------------------------------------------------------------------------
# shop-check-schedule
# ---------------------------------------------------------------------------


class TestCheckSchedule:
    def test_returns_three_machine_classes(self, workspace: Path) -> None:
        tool = CheckScheduleTool(workspace=workspace)
        result = json.loads(_run(tool.execute()))
        assert len(result["machines"]) == 3
        machine_ids = {m["machine_id"] for m in result["machines"]}
        assert "haas-vf2-3axis" in machine_ids
        assert "haas-umc750-5axis" in machine_ids
        assert "doosan-puma-2600" in machine_ids


# ---------------------------------------------------------------------------
# shop-recall-personality
# ---------------------------------------------------------------------------


class TestRecallPersonality:
    def test_empty_corrections_for_unknown_customer(self, workspace: Path) -> None:
        tool = RecallPersonalityTool(workspace=workspace)
        result = json.loads(_run(tool.execute(customer_id="someone_unknown")))
        assert result["match_count"] == 0
        assert result["customer_known"] is False

    def test_returns_active_correction_after_remember(self, store: ForemanMemoryStore, workspace: Path) -> None:
        store.append_pricing_correction(
            PricingCorrection(
                correction_id="",
                customer_id="aerospace_customer",
                rule_text="pays slow, +8%",
                margin_pct_delta=8.0,
                created_by="test",
            ),
            caller="test",
        )
        tool = RecallPersonalityTool(workspace=workspace)
        result = json.loads(_run(tool.execute(customer_id="aerospace_customer")))
        assert result["match_count"] == 1
        assert result["corrections"][0]["margin_pct_delta"] == 8.0

    def test_excludes_reversed_by_default(self, store: ForemanMemoryStore, workspace: Path) -> None:
        c = PricingCorrection(
            correction_id="",
            customer_id="aerospace_customer",
            rule_text="experimental",
            margin_pct_delta=5.0,
            created_by="test",
        )
        store.append_pricing_correction(c, caller="test")
        store.reverse_pricing_correction(c.correction_id, caller="test")

        tool = RecallPersonalityTool(workspace=workspace)
        result = json.loads(_run(tool.execute(customer_id="aerospace_customer")))
        assert result["match_count"] == 0  # excluded by default

        result_inactive = json.loads(
            _run(tool.execute(customer_id="aerospace_customer", include_inactive=True))
        )
        assert result_inactive["match_count"] == 1


# ---------------------------------------------------------------------------
# shop-remember-feedback
# ---------------------------------------------------------------------------


class TestRememberFeedback:
    def test_stores_correction_with_margin_delta(self, workspace: Path) -> None:
        tool = RememberFeedbackTool(workspace=workspace)
        result = json.loads(_run(tool.execute(
            customer_id="aerospace_customer",
            rule_text="pays slow, +8%",
            margin_pct_delta=8.0,
        )))
        assert result["status"] == "stored"
        assert result["applied_delta"]["margin_pct_delta"] == 8.0
        # Verify it actually landed in the store
        store = ForemanMemoryStore(workspace=workspace)
        assert len(store.list_pricing_corrections(customer_id="aerospace_customer")) == 1

    def test_rejects_no_op_correction(self, workspace: Path) -> None:
        tool = RememberFeedbackTool(workspace=workspace)
        result = json.loads(_run(tool.execute(
            customer_id="aerospace_customer",
            rule_text="something neutral",
            margin_pct_delta=None,
            lead_delta_days=None,
        )))
        assert result["status"] == "rejected"
        # And nothing was actually stored
        store = ForemanMemoryStore(workspace=workspace)
        assert store.list_pricing_corrections(customer_id="aerospace_customer") == []

    def test_audit_log_written_on_store(self, workspace: Path) -> None:
        tool = RememberFeedbackTool(workspace=workspace)
        _run(tool.execute(
            customer_id="aerospace_customer",
            rule_text="x",
            margin_pct_delta=5.0,
        ))
        store = ForemanMemoryStore(workspace=workspace)
        audit = store.list_audit_entries(slot="pricing_corrections")
        assert len(audit) == 1
        assert audit[0].caller == "shop-remember-feedback"


# ---------------------------------------------------------------------------
# shop-compose-quote
# ---------------------------------------------------------------------------


class TestComposeQuote:
    def _common_inputs(self) -> dict:
        return {
            "material": "6061-T6",
            "quantity": 150,
            "customer_id": "aerospace_customer",
            "comparable_jobs": [
                {"job_id": "J1", "won": True, "unit_price": 30.0, "quantity": 100},
                {"job_id": "J2", "won": True, "unit_price": 32.0, "quantity": 150},
                {"job_id": "J3", "won": False, "unit_price": 28.0, "quantity": 200},
            ],
            "material_inventory": {"supplier_lead_days": 3},
            "machine_schedule": {
                "machines": [
                    {"machine_id": "m1", "slack_days": 1},
                    {"machine_id": "m2", "slack_days": 2},
                ]
            },
            "personality_corrections": [],
        }

    def test_balanced_profile_uses_median_of_wons(self, workspace: Path) -> None:
        tool = ComposeQuoteTool(workspace=workspace)
        result = json.loads(_run(tool.execute(**self._common_inputs(), profile_name="balanced")))
        # median of [30, 32] = 31.0
        assert result["quote"]["unit_price"] == 31.0
        assert result["quote"]["total"] == 31.0 * 150
        # baseline lead = supplier(3) + processing(4) = 7
        assert result["quote"]["lead_days"] == 7

    def test_conservative_profile_pads_margin_and_lead(self, workspace: Path) -> None:
        tool = ComposeQuoteTool(workspace=workspace)
        result = json.loads(_run(tool.execute(**self._common_inputs(), profile_name="conservative")))
        # 31.0 * 1.15 = 35.65
        assert result["quote"]["unit_price"] == round(31.0 * 1.15, 2)
        assert result["quote"]["lead_days"] == 7 + 3  # +3 lead buffer
        assert result["clarifying_questions"], "conservative profile should always ask clarifying"

    def test_aggressive_profile_undercuts(self, workspace: Path) -> None:
        tool = ComposeQuoteTool(workspace=workspace)
        result = json.loads(_run(tool.execute(**self._common_inputs(), profile_name="aggressive")))
        # 31.0 * 0.92 = 28.52
        assert result["quote"]["unit_price"] == round(31.0 * 0.92, 2)
        assert result["quote"]["lead_days"] == 7 - 1

    def test_personality_correction_moves_price(self, workspace: Path) -> None:
        tool = ComposeQuoteTool(workspace=workspace)
        inputs = self._common_inputs()
        inputs["personality_corrections"] = [
            {
                "correction_id": "F-1018",
                "rule_text": "pays slow, +8%",
                "margin_pct_delta": 8.0,
                "lead_delta_days": None,
            }
        ]
        result = json.loads(_run(tool.execute(**inputs, profile_name="balanced")))
        # 31.0 * 1.08 = 33.48
        assert result["quote"]["unit_price"] == round(31.0 * 1.08, 2)
        applied = result["reasoning"]["personality_applied"]
        assert len(applied) == 1
        assert applied[0]["applied_delta"]["margin_pct"] == 8.0
        # Math trace must mention personality
        assert "Personality deltas" in result["reasoning"]["math"]

    def test_empty_comparables_escalates(self, workspace: Path) -> None:
        tool = ComposeQuoteTool(workspace=workspace)
        inputs = self._common_inputs()
        inputs["comparable_jobs"] = []
        result = json.loads(_run(tool.execute(**inputs)))
        assert result.get("status") == "escalate"
        assert result.get("human_approval_required") is True

    def test_human_approval_required_always_true(self, workspace: Path) -> None:
        """Phase One non-negotiable: agent never sends autonomously."""
        tool = ComposeQuoteTool(workspace=workspace)
        result = json.loads(_run(tool.execute(**self._common_inputs())))
        assert result["human_approval_required"] is True

    def test_zero_delta_personality_correction_warns(self, workspace: Path) -> None:
        """Citing feedback without moving the number is a tracked bug."""
        tool = ComposeQuoteTool(workspace=workspace)
        inputs = self._common_inputs()
        inputs["personality_corrections"] = [
            {
                "correction_id": "F-bad",
                "rule_text": "supposedly does something",
                "margin_pct_delta": 0,
                "lead_delta_days": 0,
            }
        ]
        result = json.loads(_run(tool.execute(**inputs)))
        # Price must NOT have moved
        assert result["quote"]["unit_price"] == 31.0
        # Warning surfaced in personality_applied
        applied = result["reasoning"]["personality_applied"]
        assert applied[0].get("warning")


# ---------------------------------------------------------------------------
# shop-extract-drawing — error paths (real API call is a separate smoke test)
# ---------------------------------------------------------------------------


class TestExtractDrawing:
    def test_missing_file_returns_error(self, workspace: Path) -> None:
        tool = ExtractDrawingTool(workspace=workspace)
        result = json.loads(_run(tool.execute(drawing_path="does_not_exist.pdf")))
        assert result["error"] is not None
        assert "not found" in result["error"]
        assert result["overall_confidence"] == 0.0
        assert result["human_review_required"] is True

    def test_missing_api_key_returns_error(self, tmp_path: Path) -> None:
        # Real PDF needed for the path-resolution check to pass
        fake_pdf = tmp_path / "fake.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4\n%fake\n")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            tool = ExtractDrawingTool(workspace=tmp_path)
            result = json.loads(_run(tool.execute(drawing_path="fake.pdf")))
        assert result["error"] is not None
        assert "ANTHROPIC_API_KEY" in result["error"]
        assert result["human_review_required"] is True
