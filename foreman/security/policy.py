"""Pydantic schema + loader for Foreman deployment policies.

A policy file is a YAML document at policies/<deployment-target>.yaml that
declares the allowed network destinations, sandbox configuration, and
outbound-send gating for a Foreman deployment. The installer picks one of
the three policy files per CLAUDE.md → Deployment targets and feeds it to
the agent at boot.

The three shipped policies:
    managed-cloud.yaml         — multi-tenant SaaS hosted by us
    single-tenant-cloud.yaml   — shop's own cloud account
    on-prem.yaml               — GPU box in shop's server room (strictest)

Schema is conservative. Adding a new outbound host requires editing the
policy file (and per the Working agreements section, security-review by
Colin before merge).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


DeploymentTarget = Literal["managed-cloud", "single-tenant-cloud", "on-prem"]


class NetworkPolicy(BaseModel):
    """Outbound network controls.

    The egress allowlist is the SUM of: llm_provider_hosts + email_servers +
    mcp_servers. Anything else is denied at runtime (Foreman's egress check)
    on top of nanobot's existing default-deny on private networks.
    """

    model_config = ConfigDict(extra="forbid")

    llm_provider_hosts: list[str] = Field(
        default_factory=list,
        description="Hostnames of allowed LLM providers, e.g., 'api.anthropic.com'.",
    )
    email_servers: list[str] = Field(
        default_factory=list,
        description='Hostnames of IMAP/SMTP servers Foreman is configured to reach.',
    )
    mcp_servers: list[str] = Field(
        default_factory=list,
        description='Hostnames of MCP servers explicitly authorized for this deployment.',
    )
    extra_hosts: list[str] = Field(
        default_factory=list,
        description=(
            "Escape hatch for one-off allowed hosts (e.g., a webhook the shop "
            "uses). Use sparingly; every entry is a security-review item."
        ),
    )
    extra_ssrf_cidrs: list[str] = Field(
        default_factory=list,
        description=(
            "CIDR ranges to allow despite nanobot's default-deny on private "
            "networks. Forwarded to nanobot.security.network.configure_ssrf_whitelist. "
            "Common case: a Tailscale range so Foreman can reach an on-prem MCP server."
        ),
    )

    @property
    def all_allowed_hosts(self) -> set[str]:
        return {
            *self.llm_provider_hosts,
            *self.email_servers,
            *self.mcp_servers,
            *self.extra_hosts,
        }


class OutboundSendPolicy(BaseModel):
    """Approval gating for outbound user-visible messages (email, slack, etc.)."""

    model_config = ConfigDict(extra="forbid")

    require_human_approval: bool = Field(
        default=True,
        description=(
            "CLAUDE.md Non-negotiable #1. Phase One: agent never sends a quote "
            "or any external communication without explicit owner approval. "
            "Setting this to false requires a written exception per the "
            "Working Agreements section."
        ),
    )
    auto_approve_channels: list[str] = Field(
        default_factory=list,
        description=(
            "Channels exempted from the human-approval gate. Empty in Phase "
            "One. Could include 'slack' for internal-team-only channels in "
            "later phases, but never for outbound-customer channels like 'email'."
        ),
    )


class SandboxPolicy(BaseModel):
    """Workspace and shell sandboxing knobs."""

    model_config = ConfigDict(extra="forbid")

    workspace_isolation: Literal["bubblewrap", "process", "none"] = Field(
        default="bubblewrap",
        description=(
            "bubblewrap: Linux kernel namespaces (default; matches upstream "
            "nanobot). process: best-effort process isolation (macOS/Windows "
            "fallback). none: no isolation (NEVER use in production)."
        ),
    )
    block_metadata_endpoints: bool = Field(
        default=True,
        description=(
            "Block cloud-metadata endpoints (169.254.169.254 and friends). "
            "Already covered by nanobot's _BLOCKED_NETWORKS but called out "
            "here so on-prem deployments cannot accidentally relax it."
        ),
    )


class AuditPolicy(BaseModel):
    """Audit-log surfaces required for this deployment."""

    model_config = ConfigDict(extra="forbid")

    log_personality_writes: bool = Field(default=True)
    log_outbound_attempts: bool = Field(default=True)
    log_egress_denials: bool = Field(default=True)


class Policy(BaseModel):
    """Top-level policy for a Foreman deployment."""

    model_config = ConfigDict(extra="forbid")

    name: DeploymentTarget
    description: str = ""
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)
    outbound_send: OutboundSendPolicy = Field(default_factory=OutboundSendPolicy)
    sandbox: SandboxPolicy = Field(default_factory=SandboxPolicy)
    audit: AuditPolicy = Field(default_factory=AuditPolicy)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_policy(path: str | Path) -> Policy:
    """Load and validate a policy YAML file."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Policy file not found: {p}")
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Policy.model_validate(data)
