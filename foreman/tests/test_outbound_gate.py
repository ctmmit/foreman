"""Tests for ForemanMessageTool: the outbound-send approval gate."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from foreman.memory import ForemanMemoryStore
from foreman.security.network import apply_policy
from foreman.security.outbound_gate import ForemanMessageTool
from foreman.security.policy import (
    AuditPolicy,
    NetworkPolicy,
    OutboundSendPolicy,
    Policy,
    SandboxPolicy,
)


@pytest.fixture(autouse=True)
def _reset_policy() -> None:
    import foreman.security.network as fnet
    fnet._current_policy = None
    yield
    fnet._current_policy = None


def _policy(*, require_approval: bool, auto_approve: list[str] | None = None) -> Policy:
    return Policy(
        name="managed-cloud",
        network=NetworkPolicy(),
        outbound_send=OutboundSendPolicy(
            require_human_approval=require_approval,
            auto_approve_channels=auto_approve or [],
        ),
        sandbox=SandboxPolicy(),
        audit=AuditPolicy(),
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Gate behavior
# ---------------------------------------------------------------------------


class TestApprovalGate:
    def test_blocks_send_when_approval_required(self, tmp_path: Path) -> None:
        apply_policy(_policy(require_approval=True))
        send_mock = AsyncMock()
        tool = ForemanMessageTool(
            send_callback=send_mock,
            default_channel="email",
            default_chat_id="owner@shop.com",
            workspace=tmp_path,
            foreman_workspace=tmp_path,
        )
        result = _run(tool.execute(content="Quote attached", channel="email", chat_id="buyer@x.com"))
        assert "queued for owner approval" in result
        assert "queue_id=" in result
        send_mock.assert_not_called()

    def test_passes_through_when_approval_not_required(self, tmp_path: Path) -> None:
        apply_policy(_policy(require_approval=False))
        send_mock = AsyncMock()
        tool = ForemanMessageTool(
            send_callback=send_mock,
            default_channel="email",
            default_chat_id="owner@shop.com",
            workspace=tmp_path,
            foreman_workspace=tmp_path,
        )
        result = _run(tool.execute(content="hi", channel="email", chat_id="x@y.com"))
        assert "Message sent" in result
        send_mock.assert_called_once()

    def test_auto_approve_channel_bypasses_gate(self, tmp_path: Path) -> None:
        apply_policy(_policy(require_approval=True, auto_approve=["slack"]))
        send_mock = AsyncMock()
        tool = ForemanMessageTool(
            send_callback=send_mock,
            default_channel="slack",
            default_chat_id="C123",
            workspace=tmp_path,
            foreman_workspace=tmp_path,
        )
        result = _run(tool.execute(content="hello", channel="slack", chat_id="C123"))
        assert "Message sent" in result
        send_mock.assert_called_once()

    def test_email_still_gated_when_only_slack_auto_approved(self, tmp_path: Path) -> None:
        apply_policy(_policy(require_approval=True, auto_approve=["slack"]))
        send_mock = AsyncMock()
        tool = ForemanMessageTool(
            send_callback=send_mock,
            default_channel="email",
            default_chat_id="owner@shop.com",
            workspace=tmp_path,
            foreman_workspace=tmp_path,
        )
        result = _run(tool.execute(content="quote", channel="email", chat_id="x@y.com"))
        assert "queued for owner approval" in result
        send_mock.assert_not_called()

    def test_default_no_policy_fails_closed(self, tmp_path: Path) -> None:
        """No policy loaded ⇒ require_outbound_approval defaults True ⇒ block."""
        send_mock = AsyncMock()
        tool = ForemanMessageTool(
            send_callback=send_mock,
            default_channel="email",
            default_chat_id="owner@shop.com",
            workspace=tmp_path,
            foreman_workspace=tmp_path,
        )
        result = _run(tool.execute(content="hello", channel="email", chat_id="x@y.com"))
        assert "queued for owner approval" in result
        send_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Queue file + audit log
# ---------------------------------------------------------------------------


class TestQueueAndAudit:
    def test_blocked_send_writes_queue_entry(self, tmp_path: Path) -> None:
        apply_policy(_policy(require_approval=True))
        tool = ForemanMessageTool(
            send_callback=AsyncMock(),
            default_channel="email",
            default_chat_id="owner@shop.com",
            workspace=tmp_path,
            foreman_workspace=tmp_path,
        )
        _run(tool.execute(content="quote draft", channel="email", chat_id="buyer@x.com"))
        queue_file = tmp_path / "personality" / "outbound_queue.jsonl"
        assert queue_file.exists()
        lines = queue_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["status"] == "pending_owner_approval"
        assert record["channel"] == "email"
        assert record["chat_id"] == "buyer@x.com"
        assert record["content"] == "quote draft"

    def test_blocked_send_writes_audit_entry(self, tmp_path: Path) -> None:
        apply_policy(_policy(require_approval=True))
        tool = ForemanMessageTool(
            send_callback=AsyncMock(),
            default_channel="email",
            default_chat_id="owner@shop.com",
            workspace=tmp_path,
            foreman_workspace=tmp_path,
        )
        _run(tool.execute(content="quote draft", channel="email", chat_id="buyer@x.com"))
        store = ForemanMemoryStore(workspace=tmp_path)
        entries = store.list_audit_entries(slot="outbound_send")
        assert len(entries) == 1
        assert entries[0].caller == "foreman-message-tool"
        assert entries[0].operation == "insert"
        assert "queue_id" in entries[0].delta_payload

    def test_passthrough_send_does_not_write_queue(self, tmp_path: Path) -> None:
        apply_policy(_policy(require_approval=False))
        tool = ForemanMessageTool(
            send_callback=AsyncMock(),
            default_channel="email",
            default_chat_id="owner@shop.com",
            workspace=tmp_path,
            foreman_workspace=tmp_path,
        )
        _run(tool.execute(content="hi", channel="email", chat_id="x@y.com"))
        queue_file = tmp_path / "personality" / "outbound_queue.jsonl"
        assert not queue_file.exists()
