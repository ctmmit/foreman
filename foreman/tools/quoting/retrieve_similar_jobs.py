"""shop-retrieve-similar-jobs: top-N historical jobs for a material+customer.

Phase 3 implementation: synthetic seed data (foreman/tools/quoting/seeds.py).
A real shop deployment swaps this for an ERP adapter that hits ProShop /
JobBOSS / E2 / Global Shop. The interface stays the same.

Per CLAUDE.md: results MUST include at least one loss when one exists, so the
agent has a competitive benchmark to reason against, not just a sample of
won-bid optimism.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from foreman.tools.quoting.seeds import get_similar_jobs
from nanobot.agent.tools.base import Tool, tool_parameters


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "material": {
                "type": "string",
                "description": (
                    "Material code from shop-extract-drawing, e.g., '6061-T6' "
                    "or 'AISI D-2'. Matched case-insensitively."
                ),
            },
            "customer_id": {
                "type": "string",
                "description": (
                    "Resolved customer_id from upstream resolution. "
                    "Customer-matching jobs are returned first."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max jobs to return; default 3.",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["material", "customer_id"],
    }
)
class RetrieveSimilarJobsTool(Tool):
    """shop-retrieve-similar-jobs: historical jobs for a material+customer."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)

    @property
    def name(self) -> str:
        return "shop-retrieve-similar-jobs"

    @property
    def description(self) -> str:
        return (
            "Return up to N historical jobs (default 3) for a given material "
            "and customer. Customer-matching jobs are surfaced first. The "
            "result always includes at least one LOSS when one exists in the "
            "pool, so the agent has a competitive benchmark. Phase 3 returns "
            "synthetic seed data; a real shop deployment wires this to its ERP."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        material: str,
        customer_id: str,
        limit: int = 3,
        **_: Any,
    ) -> str:
        jobs = get_similar_jobs(material=material, customer_id=customer_id, limit=limit)
        result: dict[str, Any] = {
            "material": material,
            "customer_id": customer_id,
            "match_count": len(jobs),
            "jobs": jobs,
            "data_source": "synthetic-seed",
            "note": (
                "Phase 3 placeholder data. Replace with an ERP adapter "
                "(foreman/adapters/erp/*) once Omar picks the target ERP."
            ),
        }
        return json.dumps(result)
