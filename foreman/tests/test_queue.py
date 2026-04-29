"""Tests for QueueStore: list/get/approve/reject + audit hooks."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from foreman.memory import ForemanMemoryStore
from foreman.queue import QueueEntryNotFound, QueueStore


def _write_queue(workspace: Path, entries: list[dict]) -> Path:
    path = workspace / "personality" / "outbound_queue.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


def _entry(queue_id: str, **overrides) -> dict:
    base = {
        "queue_id": queue_id,
        "queued_at": datetime.now().isoformat(),
        "channel": "email",
        "chat_id": "buyer@x.com",
        "content": f"draft quote for {queue_id}",
        "media": [],
        "buttons": [],
        "status": "pending_owner_approval",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


class TestList:
    def test_empty_queue_returns_empty_list(self, tmp_path: Path) -> None:
        store = QueueStore(workspace=tmp_path)
        assert store.list_entries() == []

    def test_lists_entries_newest_first_by_default(self, tmp_path: Path) -> None:
        _write_queue(tmp_path, [_entry("first"), _entry("second")])
        store = QueueStore(workspace=tmp_path)
        entries = store.list_entries()
        assert [e.queue_id for e in entries] == ["second", "first"]

    def test_filter_by_status(self, tmp_path: Path) -> None:
        _write_queue(
            tmp_path,
            [
                _entry("a", status="pending_owner_approval"),
                _entry("b", status="approved"),
                _entry("c", status="rejected"),
            ],
        )
        store = QueueStore(workspace=tmp_path)
        assert {e.queue_id for e in store.list_entries(status="pending_owner_approval")} == {"a"}
        assert {e.queue_id for e in store.list_entries(status="approved")} == {"b"}
        assert {e.queue_id for e in store.list_entries(status="rejected")} == {"c"}

    def test_get_returns_match(self, tmp_path: Path) -> None:
        _write_queue(tmp_path, [_entry("alpha"), _entry("beta")])
        store = QueueStore(workspace=tmp_path)
        assert store.get("alpha").queue_id == "alpha"

    def test_get_raises_when_missing(self, tmp_path: Path) -> None:
        store = QueueStore(workspace=tmp_path)
        with pytest.raises(QueueEntryNotFound):
            store.get("missing")


# ---------------------------------------------------------------------------
# Approve / Reject transitions
# ---------------------------------------------------------------------------


class TestTransitions:
    def test_approve_marks_status_and_records_decider(self, tmp_path: Path) -> None:
        _write_queue(tmp_path, [_entry("alpha")])
        store = QueueStore(workspace=tmp_path)
        updated = store.approve("alpha", decided_by="colin", note="looks good")
        assert updated.status == "approved"
        assert updated.decided_by == "colin"
        assert updated.decision_note == "looks good"
        assert updated.decided_at is not None

    def test_reject_marks_status(self, tmp_path: Path) -> None:
        _write_queue(tmp_path, [_entry("alpha")])
        store = QueueStore(workspace=tmp_path)
        updated = store.reject("alpha", decided_by="colin", note="wrong customer")
        assert updated.status == "rejected"
        assert updated.decision_note == "wrong customer"

    def test_already_decided_entry_cannot_be_re_decided(self, tmp_path: Path) -> None:
        _write_queue(tmp_path, [_entry("alpha", status="approved")])
        store = QueueStore(workspace=tmp_path)
        with pytest.raises(ValueError, match="already"):
            store.approve("alpha", decided_by="colin")
        with pytest.raises(ValueError, match="already"):
            store.reject("alpha", decided_by="colin")

    def test_unknown_id_raises_not_found(self, tmp_path: Path) -> None:
        _write_queue(tmp_path, [_entry("alpha")])
        store = QueueStore(workspace=tmp_path)
        with pytest.raises(QueueEntryNotFound):
            store.approve("ghost", decided_by="colin")

    def test_status_change_persists_to_disk(self, tmp_path: Path) -> None:
        _write_queue(tmp_path, [_entry("alpha"), _entry("beta")])
        store = QueueStore(workspace=tmp_path)
        store.approve("alpha", decided_by="colin")

        # New store reading the same file sees the new status
        store2 = QueueStore(workspace=tmp_path)
        assert store2.get("alpha").status == "approved"
        # Other entry untouched
        assert store2.get("beta").status == "pending_owner_approval"


# ---------------------------------------------------------------------------
# Audit-log integration
# ---------------------------------------------------------------------------


class TestAuditIntegration:
    def test_approve_writes_audit_entry(self, tmp_path: Path) -> None:
        _write_queue(tmp_path, [_entry("alpha")])
        store = QueueStore(workspace=tmp_path)
        store.approve("alpha", decided_by="colin", note="ok")

        mem = ForemanMemoryStore(workspace=tmp_path)
        entries = mem.list_audit_entries(slot="outbound_send")
        approve_entries = [e for e in entries if "colin" in e.caller]
        assert len(approve_entries) == 1
        assert approve_entries[0].operation == "update"
        assert approve_entries[0].delta_payload["new_status"] == "approved"
        assert approve_entries[0].delta_payload["decided_by"] == "colin"

    def test_reject_writes_audit_entry(self, tmp_path: Path) -> None:
        _write_queue(tmp_path, [_entry("alpha")])
        store = QueueStore(workspace=tmp_path)
        store.reject("alpha", decided_by="colin", note="wrong customer")

        mem = ForemanMemoryStore(workspace=tmp_path)
        entries = mem.list_audit_entries(slot="outbound_send")
        assert any(e.delta_payload.get("new_status") == "rejected" for e in entries)
