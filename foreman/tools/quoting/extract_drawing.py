"""shop-extract-drawing: PDF drawing → structured schema via Anthropic vision.

Highest-risk tool in the bundle. A tolerance misread can scrap a $50K part
and end the pilot. Per CLAUDE.md, the configured precision floor on tolerance
fields is 0.95 — when overall confidence is below that, this tool flags the
extraction and the orchestrator must escalate to the owner instead of
proceeding to compose.

Phase 3 implementation: real Anthropic vision API call (per the user's locked
decision). No mock fallback. Requires ANTHROPIC_API_KEY in env.

Output JSON shape — keep stable; downstream tools consume it:
    {
        "material": str,
        "material_confidence": float (0-1),
        "tolerances": [{"dimension": str, "value": str, "confidence": float}, ...],
        "features": [str, ...],
        "finish": str | null,
        "threads": [str, ...],
        "quantity_breaks": [{"qty": int, "note": str}, ...] | null,
        "overall_confidence": float (0-1),
        "notes_for_human": str,
        "human_review_required": bool,
        "drawing_path": str,
        "error": str | null
    }
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters


# Tolerance-field confidence floor below which we MUST escalate to the owner.
# CLAUDE.md → Hard rules in skills/foreman-quote-rfq/SKILL.md.
CONFIDENCE_FLOOR: float = 0.95

# Anthropic model — claude-opus-4-7 per user's CLAUDE.md preference for
# latest and most capable model on high-stakes tasks.
DEFAULT_MODEL: str = "claude-opus-4-7"

EXTRACTION_PROMPT = """You are an expert at reading mechanical engineering drawings for a US machine shop.

Extract the following fields from this drawing as STRICT JSON. Do not include any prose outside the JSON object. Do not wrap in markdown code fences. If a field is not present or unreadable, use null and explain in `notes_for_human`.

Schema:
{
  "material": "string, e.g., '6061-T6', 'AISI D-2', '304 stainless'",
  "material_confidence": "float 0-1; how confident in the material call",
  "tolerances": [
    {"dimension": "string identifying which dimension, e.g., '1.250 OD' or 'M6 thread depth'",
     "value": "string, e.g., '±0.005' or '+0.002/-0.001'",
     "confidence": "float 0-1"}
  ],
  "features": ["string list of features, e.g., 'four through-holes', 'M6x1.0 thread', 'chamfer 45deg'"],
  "finish": "string or null, e.g., 'anodize black', 'mirror polish', 'as machined'",
  "threads": ["string list of thread callouts, e.g., 'M6x1.0', '1/4-20 UNC'"],
  "quantity_breaks": [{"qty": "integer", "note": "string"}] or null,
  "overall_confidence": "float 0-1; honest summary across all fields",
  "notes_for_human": "string; anything ambiguous, missing, or worth flagging to the shop owner",
  "human_review_required": "boolean; set true if any tolerance confidence < 0.95 OR overall_confidence < 0.95 OR you noticed something unusual"
}

Be conservative on confidence. If a tolerance callout is ambiguous (e.g., printed faintly, partially obscured, or uses non-standard notation), confidence should be below 0.95 and `human_review_required` MUST be true. A tolerance misread on a 0.0005 vs 0.005 ends the pilot. When in doubt, flag for review.

Drawings may be in Spanish (common from Bosch and Latin American suppliers); translate dimension callouts but preserve units as printed.

Return only the JSON object."""


def _strip_code_fences(text: str) -> str:
    """Some models still wrap JSON in ```json ... ``` despite instructions."""
    fence = re.match(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", text, re.DOTALL)
    return fence.group(1) if fence else text


def _resolve_drawing_path(drawing_path: str, workspace: Path) -> Path:
    """Resolve a drawing path. Accepts absolute paths, workspace-relative, or
    bare filenames (looks in workspace/inbound/ and a few common locations).
    """
    p = Path(drawing_path).expanduser()
    if p.is_absolute() and p.exists():
        return p

    # Try workspace-relative
    candidate = workspace / drawing_path
    if candidate.exists():
        return candidate

    # Try common inbound locations
    for sub in ("inbound", "media/inbound", "drawings"):
        candidate = workspace / sub / Path(drawing_path).name
        if candidate.exists():
            return candidate

    # Last resort: return whatever was passed and let the open() call fail loud
    return p


def _build_error(drawing_path: str, error: str) -> dict[str, Any]:
    return {
        "material": None,
        "material_confidence": 0.0,
        "tolerances": [],
        "features": [],
        "finish": None,
        "threads": [],
        "quantity_breaks": None,
        "overall_confidence": 0.0,
        "notes_for_human": f"Extraction failed: {error}",
        "human_review_required": True,
        "drawing_path": drawing_path,
        "error": error,
    }


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "drawing_path": {
                "type": "string",
                "description": (
                    "Path to the drawing PDF. Accepts absolute paths, "
                    "workspace-relative paths, or bare filenames (the tool "
                    "looks in workspace/inbound/, workspace/drawings/, and "
                    "workspace/media/inbound/ for bare filenames)."
                ),
            },
            "customer_id_hint": {
                "type": "string",
                "description": (
                    "Optional resolved customer_id for log/trace context. "
                    "Does not affect extraction."
                ),
                "nullable": True,
            },
        },
        "required": ["drawing_path"],
    }
)
class ExtractDrawingTool(Tool):
    """shop-extract-drawing: PDF → structured schema via Anthropic vision."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)

    @property
    def name(self) -> str:
        return "shop-extract-drawing"

    @property
    def description(self) -> str:
        return (
            "Extract structured fields (material, tolerances, features, finish, "
            "threads, quantity breaks) from a mechanical drawing PDF. Returns "
            "JSON with per-field and overall confidence. If overall_confidence "
            "or any tolerance confidence is below 0.95, human_review_required "
            "is true and the orchestrator MUST escalate to the owner instead "
            "of proceeding to compose."
        )

    @property
    def read_only(self) -> bool:
        # Pure read on the drawing + outbound API call; no shop state mutated.
        return True

    async def execute(
        self,
        drawing_path: str,
        customer_id_hint: str | None = None,
        **_: Any,
    ) -> str:
        resolved = _resolve_drawing_path(drawing_path, self.workspace)
        if not resolved.exists():
            return json.dumps(_build_error(drawing_path, f"file not found at {resolved}"))

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return json.dumps(
                _build_error(
                    drawing_path,
                    "ANTHROPIC_API_KEY not set; cannot call vision API. "
                    "Set the env var and retry, or have the owner extract by hand.",
                )
            )

        try:
            pdf_bytes = resolved.read_bytes()
        except OSError as e:
            return json.dumps(_build_error(drawing_path, f"failed to read PDF: {e}"))

        if customer_id_hint:
            logger.info(
                "shop-extract-drawing path={} customer_hint={}",
                resolved,
                customer_id_hint,
            )

        try:
            from anthropic import Anthropic  # local import keeps tool importable without anthropic
        except ImportError:
            return json.dumps(_build_error(drawing_path, "anthropic SDK not installed"))

        client = Anthropic(api_key=api_key)

        b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")
        try:
            response = client.messages.create(
                model=DEFAULT_MODEL,
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": b64,
                                },
                            },
                            {"type": "text", "text": EXTRACTION_PROMPT},
                        ],
                    }
                ],
            )
        except Exception as e:
            logger.exception("Anthropic vision call failed for {}", resolved)
            return json.dumps(_build_error(drawing_path, f"Anthropic API error: {e}"))

        text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        raw_text = "\n".join(text_blocks).strip()
        cleaned = _strip_code_fences(raw_text)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            return json.dumps(
                _build_error(
                    drawing_path,
                    f"model returned non-JSON: {e}; raw={cleaned[:300]}",
                )
            )

        parsed["drawing_path"] = str(resolved)
        parsed.setdefault("error", None)

        # Belt-and-suspenders: if overall_confidence is missing, derive worst case.
        if "overall_confidence" not in parsed or parsed["overall_confidence"] is None:
            confidences = [parsed.get("material_confidence", 0.0)]
            confidences.extend(t.get("confidence", 0.0) for t in parsed.get("tolerances", []))
            parsed["overall_confidence"] = min(confidences) if confidences else 0.0

        # Enforce human_review_required if any signal is below the floor.
        below_floor = (
            parsed["overall_confidence"] < CONFIDENCE_FLOOR
            or any(
                t.get("confidence", 0.0) < CONFIDENCE_FLOOR
                for t in parsed.get("tolerances", [])
            )
        )
        if below_floor:
            parsed["human_review_required"] = True

        return json.dumps(parsed)
