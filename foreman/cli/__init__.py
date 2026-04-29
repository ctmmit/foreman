"""Foreman CLI extensions plugged into nanobot's Typer app."""

from foreman.cli.install import register_install_command
from foreman.cli.queue import register_queue_commands

__all__ = ["register_install_command", "register_queue_commands"]
