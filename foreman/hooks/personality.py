"""PersonalityWriteHook: observe and log every personality-mutating tool call.

This hook is observability, not correctness. The audit log itself is written
at the data layer (ForemanMemoryStore) so it cannot be skipped by an
unregistered hook. What this hook adds:

- A structured loguru line per personality-mutating call, useful for live
  debugging and monitoring without grepping the audit_log.jsonl.
- A hook-side counter for metrics (tools per iteration, mutating-call rate).
- A future home for owner notifications ("a personality write just happened
  on customer X — review here") when those land in Phase 4.

A "personality-mutating tool call" is any call whose name starts with one of
the prefixes in `PERSONALITY_WRITE_PREFIXES`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext


PERSONALITY_WRITE_PREFIXES: tuple[str, ...] = (
    "shop-remember-",
    "shop-set-",
    "shop-update-",
    "shop-reverse-",
)


@dataclass
class PersonalityWriteCounters:
    """In-process counters surfaced for tests and metrics endpoints."""

    iterations_observed: int = 0
    mutating_calls_observed: int = 0
    by_tool: dict[str, int] = field(default_factory=dict)

    def reset(self) -> None:
        self.iterations_observed = 0
        self.mutating_calls_observed = 0
        self.by_tool.clear()


class PersonalityWriteHook(AgentHook):
    """Logs personality-write tool calls; counters exposed for tests/metrics."""

    def __init__(self) -> None:
        super().__init__()
        self.counters = PersonalityWriteCounters()

    async def after_iteration(self, context: AgentHookContext) -> None:
        self.counters.iterations_observed += 1
        for call in context.tool_calls:
            tool_name = self._tool_name(call)
            if not tool_name or not self._is_personality_write(tool_name):
                continue
            self.counters.mutating_calls_observed += 1
            self.counters.by_tool[tool_name] = self.counters.by_tool.get(tool_name, 0) + 1
            logger.info(
                "personality-write tool fired iteration={} tool={} args={}",
                context.iteration,
                tool_name,
                self._safe_args_summary(call),
            )

    @staticmethod
    def _is_personality_write(tool_name: str) -> bool:
        return any(tool_name.startswith(p) for p in PERSONALITY_WRITE_PREFIXES)

    @staticmethod
    def _tool_name(call: object) -> str | None:
        """Defensive accessor — ToolCallRequest field name has shifted across nanobot revs."""
        for attr in ("name", "tool_name", "function_name"):
            value = getattr(call, attr, None)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _safe_args_summary(call: object) -> str:
        """Compact representation of the call arguments suitable for a log line."""
        for attr in ("arguments", "args", "input"):
            value = getattr(call, attr, None)
            if value is None:
                continue
            text = str(value)
            return text if len(text) <= 200 else text[:197] + "..."
        return "<no-args>"
