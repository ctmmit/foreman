"""Outbound-queue store.

Owner-facing read/write API on top of workspace/personality/outbound_queue.jsonl
(written by foreman.security.outbound_gate.ForemanMessageTool when a send is
blocked by the human-approval gate).

Public API:
    QueueEntry — one queued message (Pydantic).
    QueueStore — load/list/get/approve/reject + audit hooks.

Status lifecycle:
    pending_owner_approval  ->  approved          (via QueueStore.approve)
                            ->  rejected          (via QueueStore.reject)
"""

from foreman.queue.store import (
    QueueEntry,
    QueueStatus,
    QueueStore,
    QueueEntryNotFound,
)

__all__ = [
    "QueueEntry",
    "QueueEntryNotFound",
    "QueueStatus",
    "QueueStore",
]
