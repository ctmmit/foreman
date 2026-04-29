"""`foreman queue ...` — list / show / approve / reject blocked outbound messages.

The companion to ForemanMessageTool. When the agent's send is blocked by the
human-approval gate (CLAUDE.md non-negotiable #1), the message lands in the
outbound queue. These commands give the owner visibility and authority over
that queue.

What this chunk does NOT do (separate follow-up): actually send the approved
entries. Today, approve marks status=approved and writes an audit entry; a
queue processor (forthcoming `foreman queue flush` + a polling loop in the
gateway) is what actually transmits.
"""

from __future__ import annotations

import getpass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from foreman.queue import QueueEntry, QueueEntryNotFound, QueueStatus, QueueStore


_console = Console()


def _resolve_workspace(workspace: Path | None) -> Path:
    """Resolve workspace via flag → config → default ~/.foreman/workspace."""
    if workspace is not None:
        return workspace.expanduser()
    # Mirror the default in installer/wizard.py.
    return Path.home() / ".foreman" / "workspace"


def _format_table(entries: list[QueueEntry]) -> Table:
    table = Table(show_header=True, header_style="bold")
    table.add_column("Queue ID", overflow="fold", max_width=38)
    table.add_column("Status")
    table.add_column("Channel")
    table.add_column("Chat ID", overflow="fold", max_width=24)
    table.add_column("Queued at")
    table.add_column("Preview", overflow="fold", max_width=60)

    for e in entries:
        preview = (e.content or "").replace("\n", " ")
        if len(preview) > 60:
            preview = preview[:57] + "..."
        table.add_row(
            e.queue_id,
            _status_color(e.status),
            e.channel,
            e.chat_id,
            e.queued_at,
            preview,
        )
    return table


def _status_color(status: QueueStatus) -> str:
    if status == "pending_owner_approval":
        return "[yellow]pending[/yellow]"
    if status == "approved":
        return "[green]approved[/green]"
    if status == "rejected":
        return "[red]rejected[/red]"
    return status


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def list_command(
    status: str = typer.Option(
        "pending",
        "--status",
        "-s",
        help='Filter: "pending" (default), "approved", "rejected", or "all".',
    ),
    workspace: Path = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Foreman workspace dir (defaults to ~/.foreman/workspace).",
    ),
) -> None:
    """List outbound queue entries."""
    store = QueueStore(workspace=_resolve_workspace(workspace))
    if status == "all":
        entries = store.list_entries()
    elif status == "pending":
        entries = store.list_entries(status="pending_owner_approval")
    elif status in ("approved", "rejected"):
        entries = store.list_entries(status=status)  # type: ignore[arg-type]
    else:
        _console.print(f"[red]Unknown status filter: {status!r}[/red]")
        raise typer.Exit(code=2)

    if not entries:
        _console.print(f"[dim]No queue entries with status={status!r}.[/dim]")
        return

    _console.print(_format_table(entries))
    _console.print(f"\n[dim]{len(entries)} entry(ies).[/dim]")


def show_command(
    queue_id: str = typer.Argument(..., help="The queue_id (full or unique prefix)."),
    workspace: Path = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Foreman workspace dir.",
    ),
) -> None:
    """Show full content of one queue entry."""
    store = QueueStore(workspace=_resolve_workspace(workspace))
    entry = _resolve_entry(store, queue_id)
    _print_entry_detail(entry)


def approve_command(
    queue_id: str = typer.Argument(..., help="The queue_id (full or unique prefix)."),
    note: str = typer.Option("", "--note", "-n", help="Optional note attached to the decision."),
    decided_by: str = typer.Option(
        "",
        "--decided-by",
        help='Override the recorded decider; defaults to $USER / OS user.',
    ),
    workspace: Path = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Foreman workspace dir.",
    ),
) -> None:
    """Approve a pending queue entry. Marks status=approved + writes an audit entry."""
    _decide(queue_id, target="approved", note=note, decided_by=decided_by, workspace=workspace)


def reject_command(
    queue_id: str = typer.Argument(..., help="The queue_id (full or unique prefix)."),
    note: str = typer.Option("", "--note", "-n", help="Optional note attached to the decision."),
    decided_by: str = typer.Option(
        "",
        "--decided-by",
        help='Override the recorded decider; defaults to $USER / OS user.',
    ),
    workspace: Path = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Foreman workspace dir.",
    ),
) -> None:
    """Reject a pending queue entry. The message will never be sent."""
    _decide(queue_id, target="rejected", note=note, decided_by=decided_by, workspace=workspace)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decide(
    queue_id: str,
    *,
    target: QueueStatus,
    note: str,
    decided_by: str,
    workspace: Path | None,
) -> None:
    store = QueueStore(workspace=_resolve_workspace(workspace))
    entry = _resolve_entry(store, queue_id)
    actor = decided_by or _current_user()
    try:
        if target == "approved":
            updated = store.approve(entry.queue_id, decided_by=actor, note=note or None)
        else:
            updated = store.reject(entry.queue_id, decided_by=actor, note=note or None)
    except ValueError as e:
        _console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    color_target = "green" if target == "approved" else "yellow"
    _console.print(
        f"[{color_target}]{target}[/{color_target}] "
        f"queue_id={updated.queue_id} channel={updated.channel} "
        f"by={actor}"
    )
    if target == "approved":
        _console.print(
            "[dim]Note: approve currently marks status only. The "
            "message is sent the next time `foreman queue flush` runs "
            "(forthcoming) or the gateway picks up approved entries.[/dim]"
        )


def _resolve_entry(store: QueueStore, queue_id: str) -> QueueEntry:
    """Resolve a full or prefix queue_id to one entry, or fail loud on ambiguity."""
    try:
        return store.get(queue_id)
    except QueueEntryNotFound:
        pass

    matches = [e for e in store.list_entries() if e.queue_id.startswith(queue_id)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ids = ", ".join(e.queue_id for e in matches)
        _console.print(f"[red]Ambiguous queue_id prefix {queue_id!r}; matches: {ids}[/red]")
        raise typer.Exit(code=2)
    _console.print(f"[red]No queue entry with id or prefix {queue_id!r}.[/red]")
    raise typer.Exit(code=1)


def _print_entry_detail(entry: QueueEntry) -> None:
    _console.print(f"[bold]Queue ID:[/bold]  {entry.queue_id}")
    _console.print(f"[bold]Status:[/bold]    {_status_color(entry.status)}")
    _console.print(f"[bold]Channel:[/bold]   {entry.channel}")
    _console.print(f"[bold]Chat ID:[/bold]   {entry.chat_id}")
    _console.print(f"[bold]Queued at:[/bold] {entry.queued_at}")
    if entry.decided_at:
        _console.print(f"[bold]Decided:[/bold]   {entry.decided_at} by {entry.decided_by}")
        if entry.decision_note:
            _console.print(f"[bold]Note:[/bold]      {entry.decision_note}")
    _console.print()
    _console.print("[bold]Content:[/bold]")
    _console.print(entry.content)
    if entry.media:
        _console.print()
        _console.print(f"[bold]Media:[/bold] {entry.media}")
    if entry.buttons:
        _console.print(f"[bold]Buttons:[/bold] {entry.buttons}")


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "owner-cli"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_queue_commands(app: typer.Typer) -> None:
    """Add a `queue` sub-app with list/show/approve/reject to the parent Typer app."""
    queue_app = typer.Typer(
        name="queue",
        help="Manage the Foreman outbound queue (blocked sends awaiting owner approval).",
        no_args_is_help=True,
    )
    queue_app.command("list", help="List queue entries (default: pending only).")(list_command)
    queue_app.command("show", help="Show one queue entry's full content.")(show_command)
    queue_app.command("approve", help="Approve a pending entry.")(approve_command)
    queue_app.command("reject", help="Reject a pending entry. Never sent.")(reject_command)
    app.add_typer(queue_app)
