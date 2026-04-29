"""Foreman tool registry.

The seven `shop-*` capabilities are registered here as nanobot Python tools.
The corresponding `SKILL.md` files in `nanobot/skills/shop-*/` tell the LLM
when and how to call each tool. The meta-orchestration is described in
`skills/foreman-quote-rfq/SKILL.md`.

Registration is intentionally a single function so a one-line edit to
`nanobot/agent/loop.py` wires up all seven tools at once.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from foreman.tools.quoting import (
    CheckMaterialTool,
    CheckScheduleTool,
    ComposeQuoteTool,
    ExtractDrawingTool,
    RecallPersonalityTool,
    RememberFeedbackTool,
    RetrieveSimilarJobsTool,
)

if TYPE_CHECKING:
    from nanobot.agent.tools.registry import ToolRegistry


def register_all(registry: "ToolRegistry", *, workspace: Path) -> list[str]:
    """Register the seven shop-* tools with the agent's tool registry.

    Returns the list of tool names registered, for logging/verification.
    """
    tools = [
        ExtractDrawingTool(workspace=workspace),
        RetrieveSimilarJobsTool(workspace=workspace),
        CheckMaterialTool(workspace=workspace),
        CheckScheduleTool(workspace=workspace),
        RecallPersonalityTool(workspace=workspace),
        RememberFeedbackTool(workspace=workspace),
        ComposeQuoteTool(workspace=workspace),
    ]
    for t in tools:
        registry.register(t)
    return [t.name for t in tools]


__all__ = [
    "register_all",
    "CheckMaterialTool",
    "CheckScheduleTool",
    "ComposeQuoteTool",
    "ExtractDrawingTool",
    "RecallPersonalityTool",
    "RememberFeedbackTool",
    "RetrieveSimilarJobsTool",
]
