"""Foreman security: policies, egress allowlist, outbound-send gate.

Builds on nanobot's SSRF defense (nanobot/security/network.py) which blocks
private networks by default. This module adds:

- A strict outbound HOST allowlist (only configured LLM provider, email
  server, and explicitly enumerated MCP servers can be reached).
- The outbound_send.require_human_approval gate from CLAUDE.md
  Non-negotiable #1 (Phase One: agent never sends without owner click-through).
- Policy loader for the three deployment-target YAML files in policies/.
"""

from foreman.security.bootstrap import bootstrap_policy, resolve_policy_path
from foreman.security.network import (
    EgressDenied,
    PolicyNotLoaded,
    apply_policy,
    current_policy,
    is_channel_auto_approved,
    require_outbound_approval,
    validate_egress,
)
from foreman.security.policy import (
    NetworkPolicy,
    OutboundSendPolicy,
    Policy,
    SandboxPolicy,
    load_policy,
)

__all__ = [
    "EgressDenied",
    "NetworkPolicy",
    "OutboundSendPolicy",
    "Policy",
    "PolicyNotLoaded",
    "SandboxPolicy",
    "apply_policy",
    "bootstrap_policy",
    "current_policy",
    "is_channel_auto_approved",
    "load_policy",
    "require_outbound_approval",
    "resolve_policy_path",
    "validate_egress",
]
