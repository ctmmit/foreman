"""QueueStore: read/write the outbound queue file with status transitions.

The queue is a JSONL at workspace/personality/outbound_queue.jsonl. Each line
is a QueueEntry. Append-only at the line level — status transitions are
recorded by REWRITING the file in full each time (not edits-in-place; the
write is atomic via tmp + os.replace).

Append-only at the entry level: nothing is ever deleted. Reject just flips
status. This preserves the audit trail; an owner can grep a rejected entry's
content months later if a buyer asks why nothing went out.

Every status transition writes a matching audit_log entry via
ForemanMemoryStore (slot="outbound_send", operation="update").
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from foreman.memory import ForemanMemoryStore
from foreman.memory.models import AuditEntry


_QUEUE_FILE = "outbound_queue.jsonl"

QueueStatus = Literal["pending_owner_approval", "approved", "rejected"]


class QueueEntry(BaseModel):
    """One queued outbound message."""

    model_config = ConfigDict(extra="allow")  # tolerant of older queue files

    queue_id: str
    queued_at: str  # ISO timestamp string
    channel: str
    chat_id: str
    content: str
    media: list[str] = Field(default_factory=list)
    buttons: list[list[str]] = Field(default_factory=list)
    status: QueueStatus = "pending_owner_approval"

    # Decision metadata (populated on approve / reject)
    decided_at: str | None = None
    decided_by: str | None = None
    decision_note: str | None = None


class QueueEntryNotFound(LookupError):
    """No entry with the given queue_id."""


class QueueStore:
    """Read/write the outbound queue file with audit hooks."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)
        self.queue_path = self.workspace / "personality" / _QUEUE_FILE

    # -- read ---------------------------------------------------------------

    def list_entries(
        self,
        *,
        status: QueueStatus | None = None,
        newest_first: bool = True,
    ) -> list[QueueEntry]:
        """Return all entries, optionally filtered by status."""
        if not self.queue_path.exists():
            return []
        entries: list[QueueEntry] = []
        with open(self.queue_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(QueueEntry.model_validate_json(line))
                except Exception:
                    continue
        if status:
            entries = [e for e in entries if e.status == status]
        if newest_first:
            entries.reverse()
        return entries

    def get(self, queue_id: str) -> QueueEntry:
        """Return the entry with the given queue_id, or raise QueueEntryNotFound."""
        for e in self.list_entries():
            if e.queue_id == queue_id:
                return e
        raise QueueEntryNotFound(queue_id)

    # -- write --------------------------------------------------------------

    def approve(
        self,
        queue_id: str,
        *,
        decided_by: str,
        note: str | None = None,
    ) -> QueueEntry:
        """Mark an entry approved. Returns the updated entry.

        Approved entries are now eligible to be sent by the queue processor
        (not yet implemented — that's `foreman queue flush`, a separate piece).
        """
        return self._transition(queue_id, target="approved", decided_by=decided_by, note=note)

    def reject(
        self,
        queue_id: str,
        *,
        decided_by: str,
        note: str | None = None,
    ) -> QueueEntry:
        """Mark an entry rejected. Returns the updated entry. Never sent."""
        return self._transition(queue_id, target="rejected", decided_by=decided_by, note=note)

    # -- internals ----------------------------------------------------------

    def _transition(
        self,
        queue_id: str,
        *,
        target: QueueStatus,
        decided_by: str,
        note: str | None,
    ) -> QueueEntry:
        if target not in ("approved", "rejected"):
            raise ValueError(f"invalid target status: {target!r}")
        entries_oldest_first = self.list_entries(newest_first=False)
        found_idx: int | None = None
        for idx, e in enumerate(entries_oldest_first):
            if e.queue_id == queue_id:
                found_idx = idx
                break
        if found_idx is None:
            raise QueueEntryNotFound(queue_id)

        existing = entries_oldest_first[found_idx]
        if existing.status != "pending_owner_approval":
            raise ValueError(
                f"queue entry {queue_id} is already {existing.status!r}; "
                "only pending entries can be approved/rejected"
            )

        updated = existing.model_copy(update={
            "status": target,
            "decided_at": datetime.now().isoformat(),
            "decided_by": decided_by,
            "decision_note": note,
        })
        entries_oldest_first[found_idx] = updated
        self._rewrite_file(entries_oldest_first)
        self._write_audit(updated, target=target, decided_by=decided_by, note=note)
        return updated

    def _rewrite_file(self, entries: Iterable[QueueEntry]) -> None:
        """Atomic full-file rewrite: tmp + os.replace."""
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.queue_path.with_suffix(self.queue_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(e.model_dump_json() + "\n")
        os.replace(tmp, self.queue_path)

    def _write_audit(
        self,
        entry: QueueEntry,
        *,
        target: QueueStatus,
        decided_by: str,
        note: str | None,
    ) -> None:
        try:
            store = ForemanMemoryStore(workspace=self.workspace)
            store.append_audit_entry(
                AuditEntry(
                    entry_id=str(uuid.uuid4()),
                    timestamp=datetime.now(),
                    caller=f"foreman-queue-cli({decided_by})",
                    slot="outbound_send",
                    operation="update",
                    target_id=entry.queue_id,
                    delta_summary=(
                        f"{target} outbound queue entry {entry.queue_id} "
                        f"(channel={entry.channel!r}, chat_id={entry.chat_id!r})"
                        + (f" — {note}" if note else "")
                    ),
                    delta_payload={
                        "queue_id": entry.queue_id,
                        "new_status": target,
                        "decided_by": decided_by,
                        "decision_note": note,
                    },
                )
            )
        except Exception:
            # Audit failure must not block the status change.
            pass
