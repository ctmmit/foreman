"""Foreman agent hooks.

Hooks plug into nanobot's AgentHook lifecycle (before_iteration / on_stream /
after_iteration / etc.) for cross-cutting observability and policy concerns
that don't belong at the tool level.

Audit logging itself happens at the data layer (ForemanMemoryStore writes an
audit entry inside every mutating method) so it cannot be forgotten when a
hook is unregistered.
"""

from foreman.hooks.personality import PersonalityWriteHook

__all__ = ["PersonalityWriteHook"]
