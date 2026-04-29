"""shop-check-material: raw-material inventory and supplier lead time."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from foreman.tools.quoting.seeds import get_inventory
from nanobot.agent.tools.base import Tool, tool_parameters


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "material": {
                "type": "string",
                "description": "Material code, e.g., '6061-T6'.",
            },
        },
        "required": ["material"],
    }
)
class CheckMaterialTool(Tool):
    """shop-check-material: raw material inventory and supplier lead time."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)

    @property
    def name(self) -> str:
        return "shop-check-material"

    @property
    def description(self) -> str:
        return (
            "Return raw-material inventory on hand and the supplier lead time "
            "for the given material code. Phase 3 returns synthetic seed data; "
            "production deployments pull from the shop's inventory system."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, material: str, **_: Any) -> str:
        inv = get_inventory(material)
        result: dict[str, Any] = {
            "material": material,
            **inv,
            "data_source": "synthetic-seed",
        }
        return json.dumps(result)
