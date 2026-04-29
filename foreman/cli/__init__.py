"""Foreman CLI extensions plugged into nanobot's Typer app."""

from foreman.cli.install import register_install_command

__all__ = ["register_install_command"]
