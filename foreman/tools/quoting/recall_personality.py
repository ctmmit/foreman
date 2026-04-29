"""shop-recall-personality: customer-gated retrieval of prior owner feedback.

Always called by the agent before shop-compose-quote. If matches are non-empty,
the agent must pass the raw matches to compose AND translate the rule_text +
margin_pct_delta + lead_delta_days fields into concrete numeric deltas the
compose tool applies to the price and lead. See foreman-quote-rfq SKILL.md
"How it works" step 4 for the rule.

The customer-id resolver (foreman.memory.resolver) is the upstream gate: this
tool TRUSTS the customer_id passed in. If the agent gets the customer wrong,
this tool retrieves the wrong feedback and applies the wrong margin — the
worst quoting failure mode. Hence CLAUDE.md non-negotiable #4: when the
upstream resolver returns confidence < 0.9, the agent MUST escalate to the
owner before calling this tool.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from foreman.memory import ForemanMemoryStore
from nanobot.agent.tools.base import Tool, tool_parameters


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": (
                    "Resolved customer_id from upstream resolution. The "
                    "resolver MUST have returned confidence >= 0.9 before "
                    "this tool is called; otherwise escalate to the owner."
                ),
            },
            "context_key": {
                "type": "string",
                "description": (
                    "Optional discriminator within a customer "
                    "(e.g., 'rush_orders'). If omitted, all active "
                    "corrections for the customer are returned."
                ),
                "nullable": True,
            },
            "include_inactive": {
                "type": "boolean",
                "description": (
                    "If true, also return reversed corrections (for audit/"
                    "history view). Default false: only active corrections."
                ),
            },
        },
        "required": ["customer_id"],
    }
)
class RecallPersonalityTool(Tool):
    """shop-recall-personality: prior owner pricing corrections for a customer."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)

    @property
    def name(self) -> str:
        return "shop-recall-personality"

    @property
    def description(self) -> str:
        return (
            "Retrieve prior owner pricing corrections for the given customer "
            "(filtered to active corrections by default). The agent MUST call "
            "this before shop-compose-quote. If the result has non-empty "
            "corrections, the agent MUST translate each one into numeric "
            "deltas (margin_pct_delta, lead_delta_days) and pass them to "
            "compose so the displayed price moves in sync with the cited "
            "feedback. Citing feedback without applying the delta is a bug."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        customer_id: str,
        context_key: str | None = None,
        include_inactive: bool = False,
        **_: Any,
    ) -> str:
        store = ForemanMemoryStore(workspace=self.workspace)
        corrections = store.list_pricing_corrections(
            customer_id=customer_id,
            active_only=not include_inactive,
        )
        if context_key:
            corrections = [c for c in corrections if c.context_key == context_key]

        # Customer record (display_name, payment_terms, etc.) for context.
        customer = store.get_customer(customer_id)

        result: dict[str, Any] = {
            "customer_id": customer_id,
            "customer_known": customer is not None,
            "customer_display_name": customer.display_name if customer else None,
            "context_key": context_key,
            "match_count": len(corrections),
            "corrections": [c.model_dump(mode="json") for c in corrections],
        }
        if not corrections:
            result["note"] = (
                "No active pricing corrections for this customer. The compose "
                "tool should produce a neutral quote under the requested "
                "steering profile, with no personality deltas applied."
            )
        return json.dumps(result, default=str)
