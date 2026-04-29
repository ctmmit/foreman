"""ForemanMessageTool: gates outbound sends behind the human-approval policy.

Subclass of nanobot's MessageTool. Behavior:

- If require_outbound_approval() is False, OR the target channel is in
  auto_approve_channels: forward to the parent execute() (send normally).
- Otherwise: do NOT send. Instead, append the would-be OutboundMessage to
  workspace/personality/outbound_queue.jsonl and return a clear LLM-facing
  string explaining the message is queued for owner approval. The agent
  must NOT silently retry; the owner is the only mechanism by which a
  queued message becomes a real send.

Also writes an audit_log entry (slot="outbound_send") so every blocked
attempt is traceable. Per CLAUDE.md non-negotiable #1.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from foreman.memory import ForemanMemoryStore
from foreman.memory.models import AuditEntry
from foreman.security.network import (
    is_channel_auto_approved,
    require_outbound_approval,
)
from nanobot.agent.tools.message import MessageTool


_QUEUE_FILE = "outbound_queue.jsonl"


class ForemanMessageTool(MessageTool):
    """MessageTool with the human-approval gate enforced."""

    def __init__(self, *args: Any, foreman_workspace: Path | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # The parent stores its own _workspace; we capture an explicit one so
        # the queue file path is unambiguous even when the parent's resolution
        # differs from what the policy expects.
        self._foreman_workspace: Path = (
            Path(foreman_workspace).expanduser()
            if foreman_workspace is not None
            else Path(self._workspace)
        )

    async def execute(
        self,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        media: list[str] | None = None,
        buttons: list[list[str]] | None = None,
        **kwargs: Any,
    ) -> str:
        # Resolve the effective channel the same way the parent does.
        effective_channel = channel or self._default_channel.get()

        # Approval gate (CLAUDE.md non-negotiable #1).
        if require_outbound_approval() and not is_channel_auto_approved(effective_channel):
            return self._queue_and_explain(
                content=content,
                channel=effective_channel,
                chat_id=chat_id or self._default_chat_id.get(),
                media=media or [],
                buttons=buttons or [],
            )

        return await super().execute(
            content=content,
            channel=channel,
            chat_id=chat_id,
            message_id=message_id,
            media=media,
            buttons=buttons,
            **kwargs,
        )

    # ----------------------------------------------------------------------
    # Queue + audit
    # ----------------------------------------------------------------------

    def _queue_and_explain(
        self,
        *,
        content: str,
        channel: str,
        chat_id: str,
        media: list[str],
        buttons: list[list[str]],
    ) -> str:
        queue_id = str(uuid.uuid4())
        queued_at = datetime.now().isoformat()
        record = {
            "queue_id": queue_id,
            "queued_at": queued_at,
            "channel": channel or "",
            "chat_id": chat_id or "",
            "content": content,
            "media": media,
            "buttons": buttons,
            "status": "pending_owner_approval",
        }

        path = self._queue_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Audit-log the blocked attempt.
        self._write_audit(
            queue_id=queue_id,
            channel=channel,
            chat_id=chat_id,
            preview=content[:200],
        )

        logger.info(
            "outbound send blocked queue_id={} channel={} chat_id={}",
            queue_id,
            channel,
            chat_id,
        )

        return (
            f"Message queued for owner approval (queue_id={queue_id}, "
            f"channel={channel!r}). The owner must approve via the "
            "outbound queue before this message is sent. Do NOT retry; "
            "the agent has no mechanism to bypass the approval gate."
        )

    def _queue_path(self) -> Path:
        return self._foreman_workspace / "personality" / _QUEUE_FILE

    def _write_audit(self, *, queue_id: str, channel: str, chat_id: str, preview: str) -> None:
        try:
            store = ForemanMemoryStore(workspace=self._foreman_workspace)
            store.append_audit_entry(
                AuditEntry(
                    entry_id=str(uuid.uuid4()),
                    timestamp=datetime.now(),
                    caller="foreman-message-tool",
                    slot="outbound_send",
                    operation="insert",
                    target_id=queue_id,
                    delta_summary=(
                        f"Queued outbound message for owner approval "
                        f"(channel={channel!r}, chat_id={chat_id!r}): "
                        f"{preview!r}"
                    ),
                    delta_payload={
                        "queue_id": queue_id,
                        "channel": channel,
                        "chat_id": chat_id,
                        "preview": preview,
                    },
                )
            )
        except Exception:
            # Audit failure must not block the queue write itself; surface
            # in logs only.
            logger.exception("failed to write outbound-send audit entry")
