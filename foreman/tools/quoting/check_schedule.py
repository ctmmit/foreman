"""shop-check-schedule: machine-floor slack and earliest open production slot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from foreman.tools.quoting.seeds import get_schedule_slack
from nanobot.agent.tools.base import Tool, tool_parameters


@tool_parameters(
    {
        "type": "object",
        "properties": {},
    }
)
class CheckScheduleTool(Tool):
    """shop-check-schedule: machine slack + earliest open slot."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)

    @property
    def name(self) -> str:
        return "shop-check-schedule"

    @property
    def description(self) -> str:
        return (
            "Return machine-floor slack and the earliest open production slot "
            "for each machine class (3-axis, 5-axis, turning). Used by "
            "shop-compose-quote to determine quoted lead times. Phase 3 "
            "returns synthetic seed data; production reads from the ERP's "
            "open-jobs view."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **_: Any) -> str:
        return json.dumps(get_schedule_slack())
