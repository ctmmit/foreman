"""Foreman install wizard.

Drives a non-technical shop from "we have a machine" to "Foreman is reading
our email" via six prompts. Generates platform-specific deployment files
(Docker compose / systemd unit / LaunchAgent plist / Windows NSSM script),
the runtime config at ~/.foreman/config.json, and the per-deployment .env
holding the provider key and email creds.

Public API:
    ResolvedConfig — answers from the wizard, ready for rendering.
    run_wizard() — interactive prompt loop; returns ResolvedConfig.
    render_outputs() — render platform templates with the resolved config.
    write_runtime_config() — write config.json and .env to ~/.foreman/.

The CLI entry is `foreman install` (registered from foreman/cli/install.py
into the nanobot Typer app).
"""

from foreman.installer.wizard import (
    DeploymentTarget,
    ResolvedConfig,
    render_outputs,
    run_wizard,
    write_runtime_config,
)

__all__ = [
    "DeploymentTarget",
    "ResolvedConfig",
    "render_outputs",
    "run_wizard",
    "write_runtime_config",
]
