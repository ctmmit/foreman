"""`foreman install` — interactive (or scripted) wizard that gets a shop running.

Six prompts, then renders the platform-specific deployment file (Docker
compose / systemd unit / LaunchAgent plist / Windows NSSM script), writes
~/.foreman/config.json, and writes a per-deployment .env with the API keys.

Usage:
    foreman install                        # interactive
    foreman install --target docker        # interactive, target preselected
    foreman install --non-interactive \\   # scripted (CI / re-deploy)
        --defaults config.yaml             # see installer README for shape
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console

from foreman.installer import (
    ResolvedConfig,
    render_outputs,
    run_wizard,
    write_runtime_config,
)


_console = Console()


def install_command(
    target: str | None = typer.Option(
        None,
        "--target",
        "-t",
        help="Deployment target: docker | systemd | launchd | windows.",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Skip prompts; require all answers in --defaults.",
    ),
    defaults_file: Path | None = typer.Option(
        None,
        "--defaults",
        help="YAML file of default answers; in interactive mode pre-fills, in --non-interactive mode required.",
    ),
    output_dir: Path = typer.Option(
        Path.cwd() / "foreman-install",
        "--output-dir",
        "-o",
        help="Directory to write the generated deployment file(s) into.",
    ),
    skip_runtime_config: bool = typer.Option(
        False,
        "--skip-runtime-config",
        help="Render deployment file(s) only; do NOT write ~/.foreman/config.json or the .env.",
    ),
) -> None:
    """Run the Foreman install wizard."""
    defaults: dict[str, Any] = {}
    if defaults_file:
        defaults = yaml.safe_load(defaults_file.read_text(encoding="utf-8")) or {}
    if target:
        defaults["deployment_target"] = target

    try:
        config = run_wizard(non_interactive=non_interactive, defaults=defaults)
    except ValueError as e:
        _console.print(f"[red]Wizard failed: {e}[/red]")
        raise typer.Exit(code=1)

    rendered = render_outputs(config, output_dir=output_dir)

    runtime: dict[str, Path] = {}
    if not skip_runtime_config:
        runtime = write_runtime_config(config)

    _print_summary(config, rendered, runtime)


def _print_summary(
    config: ResolvedConfig,
    rendered: dict[str, Path],
    runtime: dict[str, Path],
) -> None:
    _console.print()
    _console.print(f"[green]Foreman install wizard complete.[/green]")
    _console.print(f"  Deployment target: [cyan]{config.deployment_target}[/cyan]")
    _console.print(f"  Policy:            [cyan]{config.policy_target}[/cyan]")
    _console.print(f"  Workspace:         {config.workspace_dir}")
    _console.print()
    _console.print("[bold]Deployment files:[/bold]")
    for name, path in rendered.items():
        _console.print(f"  • {name}: {path}")
    if runtime:
        _console.print()
        _console.print("[bold]Runtime files:[/bold]")
        for kind, path in runtime.items():
            _console.print(f"  • {kind}: {path}")
    _console.print()
    _console.print("[bold]Next steps:[/bold]")
    _console.print(_next_steps_for(config.deployment_target))


_NEXT_STEPS: dict[str, str] = {
    "docker": (
        "  docker compose -f docker-compose.yml \\\n"
        "    -f {generated_path} up -d\n"
        "  docker logs -f foreman"
    ),
    "systemd": (
        "  sudo cp {generated_path} /etc/systemd/system/foreman.service\n"
        "  sudo systemctl daemon-reload\n"
        "  sudo systemctl enable --now foreman\n"
        "  journalctl -u foreman -f"
    ),
    "launchd": (
        "  cp {generated_path} ~/Library/LaunchAgents/com.foreman.agent.plist\n"
        "  launchctl load -w ~/Library/LaunchAgents/com.foreman.agent.plist\n"
        "  tail -f ~/Library/Logs/Foreman/foreman.out.log"
    ),
    "windows": (
        "  Run the generated PowerShell script as Administrator:\n"
        "    powershell -ExecutionPolicy Bypass -File {generated_path}\n"
        "  Then check the service: nssm status Foreman"
    ),
}


def _next_steps_for(target: str) -> str:
    template = _NEXT_STEPS.get(target, "  See installer/README.md")
    return template


# ---------------------------------------------------------------------------
# Registration into nanobot's Typer app
# ---------------------------------------------------------------------------


def register_install_command(app: typer.Typer) -> None:
    """Add `foreman install` to the existing Typer app."""
    app.command(
        name="install",
        help="Run the Foreman install wizard (six prompts → ready-to-deploy files).",
    )(install_command)
