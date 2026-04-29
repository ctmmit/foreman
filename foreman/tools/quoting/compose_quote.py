"""shop-compose-quote: final draft quote orchestrator.

Takes the structured outputs of the upstream five tools and produces the draft
quote object the owner reviews. Three core moves:

1. Establish baseline unit price from comparable historical jobs (median of
   won-jobs preferred; mean of all comparables as fallback).
2. Apply the steering-profile delta (conservative / balanced / aggressive).
3. Apply personality deltas from shop-recall-personality on top.

The pricing math is deterministic (no LLM call) so every quote is auditable
against the inputs. The reasoning field surfaces the math step by step.

Hard rule from foreman-quote-rfq SKILL.md: if the agent passed personality
corrections AND the deltas are zero, the price won't move and we MUST flag
that as a bug rather than silently ship a quote that "looks adjusted" but
isn't.
"""

from __future__ import annotations

import json
import statistics
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from foreman.tools.quoting.profiles import get_profile
from nanobot.agent.tools.base import Tool, tool_parameters


# Default lead components when inputs are missing — conservative bias.
_DEFAULT_PROCESSING_DAYS = 4
_DEFAULT_LEAD_DAYS = 10


def _baseline_unit_price(comparable_jobs: list[dict[str, Any]]) -> tuple[float, str]:
    """Return (price, source) — median of won jobs preferred, else mean of all."""
    if not comparable_jobs:
        return 0.0, "no_comparables"
    won = [j for j in comparable_jobs if j.get("won")]
    pool = won if won else comparable_jobs
    prices = [float(j["unit_price"]) for j in pool if j.get("unit_price") is not None]
    if not prices:
        return 0.0, "no_prices"
    return float(statistics.median(prices)), (
        f"median_of_{len(won)}_won_jobs" if won else f"mean_of_{len(pool)}_comparable_jobs"
    )


def _baseline_lead_days(material_inventory: dict[str, Any], machine_schedule: dict[str, Any]) -> int:
    """Return supplier-lead + processing-buffer estimate."""
    supplier = material_inventory.get("supplier_lead_days") if material_inventory else None
    if supplier is None:
        return _DEFAULT_LEAD_DAYS

    schedule_buffer = 0
    if machine_schedule and machine_schedule.get("machines"):
        slacks = [int(m.get("slack_days", 0) or 0) for m in machine_schedule["machines"]]
        # If every machine class has zero slack, add an extra day for queueing.
        if slacks and all(s == 0 for s in slacks):
            schedule_buffer = 1

    return int(supplier) + _DEFAULT_PROCESSING_DAYS + schedule_buffer


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "material": {"type": "string"},
            "quantity": {"type": "integer", "minimum": 1},
            "customer_id": {"type": "string"},
            "profile_name": {
                "type": "string",
                "enum": ["conservative", "balanced", "aggressive"],
                "description": "Steering profile. Default: balanced.",
            },
            "comparable_jobs": {
                "type": "array",
                "description": (
                    "Output of shop-retrieve-similar-jobs.jobs — the agent "
                    "passes these through verbatim."
                ),
                "items": {"type": "object"},
            },
            "material_inventory": {
                "type": "object",
                "description": "Output of shop-check-material.",
            },
            "machine_schedule": {
                "type": "object",
                "description": "Output of shop-check-schedule.",
            },
            "personality_corrections": {
                "type": "array",
                "description": (
                    "List of corrections from shop-recall-personality.corrections. "
                    "Each item must have margin_pct_delta and/or lead_delta_days "
                    "populated. Pass an empty list when there are no recalled "
                    "corrections."
                ),
                "items": {"type": "object"},
            },
            "extraction_notes": {
                "type": "string",
                "description": (
                    "Optional: notes_for_human from shop-extract-drawing. "
                    "Surfaced in clarifying_questions when present."
                ),
                "nullable": True,
            },
            "due_date": {
                "type": "string",
                "description": (
                    "Optional ISO date the buyer requested. If provided, the "
                    "quote includes a 'meets_due_date' boolean."
                ),
                "nullable": True,
            },
        },
        "required": [
            "material",
            "quantity",
            "customer_id",
            "comparable_jobs",
            "material_inventory",
            "machine_schedule",
            "personality_corrections",
        ],
    }
)
class ComposeQuoteTool(Tool):
    """shop-compose-quote: deterministic quote synthesis."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)

    @property
    def name(self) -> str:
        return "shop-compose-quote"

    @property
    def description(self) -> str:
        return (
            "Synthesize a draft quote from upstream tool outputs (extraction, "
            "comparable jobs, inventory, schedule, recalled personality). "
            "Pricing is deterministic and auditable: median of won comparable "
            "jobs as baseline; steering profile delta; then personality "
            "deltas. Returns the structured quote object specified in "
            "skills/foreman-quote-rfq/SKILL.md, with human_approval_required "
            "always true (Phase One non-negotiable: agent never sends "
            "autonomously)."
        )

    @property
    def read_only(self) -> bool:
        return True  # quote is just data; no shop state mutated

    async def execute(
        self,
        material: str,
        quantity: int,
        customer_id: str,
        comparable_jobs: list[dict[str, Any]],
        material_inventory: dict[str, Any],
        machine_schedule: dict[str, Any],
        personality_corrections: list[dict[str, Any]],
        profile_name: str = "balanced",
        extraction_notes: str | None = None,
        due_date: str | None = None,
        **_: Any,
    ) -> str:
        profile = get_profile(profile_name)

        # ---- Baseline unit price ------------------------------------------
        base_price, baseline_source = _baseline_unit_price(comparable_jobs)
        if base_price <= 0:
            return json.dumps({
                "status": "escalate",
                "reason": (
                    f"No comparable historical jobs for material={material!r}. "
                    "Cannot produce a baseline price; ask the owner for a "
                    "manual estimate or accept a wider error band."
                ),
                "human_approval_required": True,
            })

        # ---- Steering profile delta ---------------------------------------
        steering_margin_pct = profile.margin_pct_delta
        steering_lead = profile.lead_delta_days

        # ---- Personality deltas -------------------------------------------
        personality_margin_total = 0.0
        personality_lead_total = 0
        applied: list[dict[str, Any]] = []
        for corr in personality_corrections:
            margin = corr.get("margin_pct_delta")
            lead = corr.get("lead_delta_days")
            if margin in (None, 0) and lead in (None, 0):
                # Cited but doesn't move — flag.
                applied.append({
                    "correction_id": corr.get("correction_id"),
                    "rule_text": corr.get("rule_text"),
                    "applied_delta": {"margin_pct": 0, "lead_delta_days": 0},
                    "warning": (
                        "Correction was passed in but both deltas are zero; "
                        "the price will not move. Verify the agent intended "
                        "to apply this correction."
                    ),
                })
                continue
            if margin not in (None, 0):
                personality_margin_total += float(margin)
            if lead not in (None, 0):
                personality_lead_total += int(lead)
            applied.append({
                "correction_id": corr.get("correction_id"),
                "rule_text": corr.get("rule_text"),
                "applied_delta": {
                    "margin_pct": margin,
                    "lead_delta_days": lead,
                },
            })

        # ---- Final math ---------------------------------------------------
        total_margin_pct = steering_margin_pct + personality_margin_total
        adjusted_unit_price = base_price * (1.0 + total_margin_pct / 100.0)
        adjusted_unit_price = round(adjusted_unit_price, 2)
        total = round(adjusted_unit_price * quantity, 2)

        baseline_lead = _baseline_lead_days(material_inventory, machine_schedule)
        lead_days = max(1, baseline_lead + steering_lead + personality_lead_total)

        # ---- Math trace (auditable) ---------------------------------------
        math_trace_lines = [
            f"Baseline unit price ({baseline_source}): ${base_price:.2f}",
            (
                f"Profile '{profile.name}' ({profile.display_label}): "
                f"{steering_margin_pct:+.1f}% margin, {steering_lead:+d}d lead"
            ),
        ]
        if personality_margin_total or personality_lead_total:
            math_trace_lines.append(
                f"Personality deltas: {personality_margin_total:+.1f}% margin, "
                f"{personality_lead_total:+d}d lead "
                f"(from {len(applied)} cited correction(s))"
            )
        math_trace_lines.append(
            f"Final: ${adjusted_unit_price:.2f}/u × {quantity} = ${total:.2f}, "
            f"{lead_days} days"
        )
        math_trace = "\n".join(math_trace_lines)

        # ---- Clarifying questions -----------------------------------------
        clarifying_questions: list[str] = []
        if profile.always_ask_clarifying:
            clarifying_questions.append(
                "Conservative profile: confirm tolerances, finish, and any "
                "non-standard callouts before sending."
            )
        if extraction_notes:
            clarifying_questions.append(extraction_notes)

        # ---- Comparable-jobs summary for reasoning ------------------------
        comparable_summary = [
            {
                "job_id": j.get("job_id"),
                "won": j.get("won"),
                "unit_price": j.get("unit_price"),
                "quantity": j.get("quantity"),
            }
            for j in comparable_jobs
        ]

        # ---- Due-date check -----------------------------------------------
        meets_due_date = None
        if due_date:
            try:
                target = date.fromisoformat(due_date)
                earliest = date.today() + timedelta(days=lead_days)
                meets_due_date = earliest <= target
            except ValueError:
                meets_due_date = None

        result: dict[str, Any] = {
            "quote": {
                "unit_price": adjusted_unit_price,
                "total": total,
                "lead_days": lead_days,
                "currency": "USD",
                "confidence": 0.85,  # baseline; vision tool pulls down on low-conf extractions
            },
            "reasoning": {
                "baseline_source": baseline_source,
                "baseline_unit_price": base_price,
                "profile": {
                    "name": profile.name,
                    "display_label": profile.display_label,
                    "margin_pct_delta": steering_margin_pct,
                    "lead_delta_days": steering_lead,
                    "description": profile.description,
                },
                "comparable_jobs": comparable_summary,
                "personality_applied": applied,
                "math": math_trace,
            },
            "clarifying_questions": clarifying_questions,
            "human_approval_required": True,
            "meets_due_date": meets_due_date,
            "context": {
                "material": material,
                "quantity": quantity,
                "customer_id": customer_id,
                "due_date": due_date,
            },
        }
        return json.dumps(result, default=str)
