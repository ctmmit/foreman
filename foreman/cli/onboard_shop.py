"""`foreman onboard-shop` — populate the personality store with what Foreman needs to know.

Two modes:

    foreman onboard-shop                         # interactive interview
    foreman onboard-shop --from <shop.yaml>      # non-interactive, idempotent
    foreman onboard-shop --from <shop.yaml> --interactive  # mix: prompt for missing pieces

Outputs land in the active workspace's ForemanMemoryStore (default
~/.foreman/workspace/personality/). Every record committed generates an
audit_log entry stamped caller="foreman-onboard-shop", so an owner can
always see what onboarding wrote.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from foreman.installer.onboard_shop import (
    OnboardResult,
    commit_from_yaml,
    run_interactive,
)
from foreman.memory import ForemanMemoryStore


_console = Console()


def _resolve_workspace(workspace: Path | None) -> Path:
    if workspace is not None:
        return workspace.expanduser()
    return Path.home() / ".foreman" / "workspace"


def onboard_shop_command(
    from_file: Path | None = typer.Option(
        None,
        "--from",
        "-f",
        help="YAML file with shop knowledge (non-interactive).",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Force interactive mode even if --from is provided (--from runs first, then prompts).",
    ),
    workspace: Path = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Foreman workspace dir (defaults to ~/.foreman/workspace).",
    ),
) -> None:
    """Populate the Foreman personality store with shop knowledge."""
    ws = _resolve_workspace(workspace)
    store = ForemanMemoryStore(workspace=ws)

    combined = OnboardResult()

    if from_file is not None:
        try:
            yaml_result = commit_from_yaml(from_file, store)
        except FileNotFoundError as e:
            _console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1)
        combined = _merge(combined, yaml_result)
        _console.print(
            f"[green]Loaded {yaml_result.total_records()} record(s) from {from_file}.[/green]"
        )

    if interactive or from_file is None:
        try:
            iv_result = run_interactive(store)
        except KeyboardInterrupt:
            _console.print("\n[yellow]Onboarding interrupted by user.[/yellow]")
            _print_summary(combined, ws)
            raise typer.Exit(code=130)
        combined = _merge(combined, iv_result)

    _print_summary(combined, ws)


def _merge(a: OnboardResult, b: OnboardResult) -> OnboardResult:
    return OnboardResult(
        shop_profile_set=a.shop_profile_set or b.shop_profile_set,
        equipment_added=a.equipment_added + b.equipment_added,
        customers_added=a.customers_added + b.customers_added,
        materials_added=a.materials_added + b.materials_added,
        routing_added=a.routing_added + b.routing_added,
        pricing_corrections_added=a.pricing_corrections_added + b.pricing_corrections_added,
        skipped=a.skipped + b.skipped,
    )


def _print_summary(result: OnboardResult, workspace: Path) -> None:
    _console.print()
    _console.print("[bold green]Shop knowledge committed.[/bold green]")
    _console.print(f"  Workspace:           {workspace / 'personality'}")
    if result.shop_profile_set:
        _console.print(f"  Shop profile:        [cyan]set[/cyan]")
    _console.print(f"  Equipment added:     {result.equipment_added}")
    _console.print(f"  Customers added:     {result.customers_added}")
    _console.print(f"  Materials added:     {result.materials_added}")
    _console.print(f"  Routing entries:     {result.routing_added}")
    _console.print(f"  Pricing corrections: {result.pricing_corrections_added}")
    if result.skipped:
        _console.print()
        _console.print("[yellow]Skipped (review):[/yellow]")
        for s in result.skipped:
            _console.print(f"  • {s}")
    _console.print()
    _console.print("[dim]Every commit is in the audit log:[/dim]")
    _console.print('[dim]  python -c "from foreman.memory import ForemanMemoryStore; from pathlib import Path; '
                  'store = ForemanMemoryStore(Path.home()/\'.foreman/workspace\'); '
                  'print(store.list_audit_entries(caller=\'foreman-onboard-shop\'))"[/dim]')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_onboard_shop_command(app: typer.Typer) -> None:
    app.command(
        name="onboard-shop",
        help="Populate the Foreman personality store with shop knowledge (interview or YAML).",
    )(onboard_shop_command)
