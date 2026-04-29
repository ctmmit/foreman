"""shop-remember-feedback: persist an owner correction to the personality store.

Called automatically when the owner gives a verbal correction in plain English
("too low", "add 8% for this customer", "never quote under $Y"). No "remember
this" instruction required — the agent recognizes the correction and calls
this tool. This is the hero-loop write side; shop-recall-personality is the
read side.

The actual write goes through ForemanMemoryStore.append_pricing_correction(),
which writes both the correction AND its audit-log entry atomically. The
caller identity is stamped into both records.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from foreman.memory import ForemanMemoryStore
from foreman.memory.models import PricingCorrection
from nanobot.agent.tools.base import Tool, tool_parameters


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "Resolved customer_id this correction applies to.",
            },
            "rule_text": {
                "type": "string",
                "description": (
                    "The owner's prose verbatim, e.g., "
                    "'Boeing pays slow, add 8%'. Stored as-is and surfaced "
                    "in the reasoning field of future quotes."
                ),
            },
            "margin_pct_delta": {
                "type": "number",
                "description": (
                    "Margin adjustment in percentage points (e.g., 8.0 means "
                    "+8% margin; -10.0 means -10%). Pass null if the "
                    "correction does not affect margin."
                ),
                "nullable": True,
            },
            "lead_delta_days": {
                "type": "integer",
                "description": (
                    "Lead-time adjustment in days (e.g., 2 means +2 days; "
                    "-1 means tighten by 1 day). Pass null if the correction "
                    "does not affect lead time."
                ),
                "nullable": True,
            },
            "context_key": {
                "type": "string",
                "description": (
                    "Optional discriminator for when the correction applies "
                    "(e.g., 'rush_orders', 'below_$5k'). Default 'default'."
                ),
                "nullable": True,
            },
            "applies_when": {
                "type": "string",
                "description": (
                    "Free-form scope, e.g., 'always', 'first 6 months', "
                    "'rush orders only'. Default 'always'."
                ),
                "nullable": True,
            },
        },
        "required": ["customer_id", "rule_text"],
    }
)
class RememberFeedbackTool(Tool):
    """shop-remember-feedback: persist an owner correction."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)

    @property
    def name(self) -> str:
        return "shop-remember-feedback"

    @property
    def description(self) -> str:
        return (
            "Persist an owner correction (margin and/or lead-time adjustment) "
            "for a customer. Called automatically when the owner replies to a "
            "draft quote with a correction, preference, or rule. The "
            "correction is retrievable via shop-recall-personality on the "
            "next matching RFQ. Every write also creates an audit-log entry."
        )

    @property
    def read_only(self) -> bool:
        return False  # mutates personality store

    async def execute(
        self,
        customer_id: str,
        rule_text: str,
        margin_pct_delta: float | None = None,
        lead_delta_days: int | None = None,
        context_key: str | None = None,
        applies_when: str | None = None,
        **_: Any,
    ) -> str:
        store = ForemanMemoryStore(workspace=self.workspace)

        # Reject zero-delta corrections that would cite feedback but not move
        # the displayed numbers — that's the "looks adjusted but isn't" bug
        # that breaks owner trust (per foreman-quote-rfq SKILL.md hard rules).
        if (margin_pct_delta in (None, 0.0)) and (lead_delta_days in (None, 0)):
            return json.dumps({
                "status": "rejected",
                "reason": (
                    "Both margin_pct_delta and lead_delta_days are zero/null. "
                    "A correction that doesn't move price OR lead can't be "
                    "applied; ask the owner what they want changed."
                ),
            })

        correction = PricingCorrection(
            correction_id="",  # store assigns
            customer_id=customer_id,
            context_key=context_key or "default",
            rule_text=rule_text,
            margin_pct_delta=margin_pct_delta,
            lead_delta_days=lead_delta_days,
            applies_when=applies_when or "always",
            created_at=datetime.now(),
            created_by="shop-remember-feedback",
        )
        store.append_pricing_correction(correction, caller="shop-remember-feedback")

        return json.dumps({
            "status": "stored",
            "correction_id": correction.correction_id,
            "customer_id": customer_id,
            "rule_text": rule_text,
            "applied_delta": {
                "margin_pct_delta": margin_pct_delta,
                "lead_delta_days": lead_delta_days,
            },
            "context_key": correction.context_key,
            "applies_when": correction.applies_when,
            "note": (
                "Correction persisted to personality store. The next matching "
                "RFQ for this customer will retrieve this via "
                "shop-recall-personality and apply the deltas in compose."
            ),
        })
