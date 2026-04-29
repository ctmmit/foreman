"""Egress host allowlist + outbound-send gating.

Layered on top of nanobot's existing SSRF defense (nanobot/security/network.py),
which blocks outbound traffic to private/internal networks by default.

Foreman tightens this further: outbound public traffic is restricted to a
fixed allowlist of hostnames declared in the active policy file. Any other
host is denied even if it's a perfectly normal public address. This is what
keeps customer drawings inside the deployment boundary (CLAUDE.md
Non-negotiable #3: drawings never leave the deployment).

Process model:
- At agent boot, the deployment's policy YAML is loaded and apply_policy()
  installs the allowlist + extra SSRF CIDRs into module state.
- Tools that issue outbound HTTP must call validate_egress(url) and respect
  the result. (Today Foreman's only outbound tool is shop-extract-drawing
  which goes to api.anthropic.com; the policy explicitly allows that.)
- If apply_policy is never called, validate_egress fails closed with
  PolicyNotLoaded.
"""

from __future__ import annotations

from urllib.parse import urlparse

from loguru import logger

from foreman.security.policy import Policy
from nanobot.security.network import configure_ssrf_whitelist, validate_url_target


class PolicyNotLoaded(RuntimeError):
    """Raised when egress validation runs before any policy was applied."""


class EgressDenied(RuntimeError):
    """Raised when a URL is blocked by the egress allowlist."""


# Module-state: the active policy. Populated by apply_policy().
_current_policy: Policy | None = None


def apply_policy(policy: Policy) -> None:
    """Apply a loaded Policy to the runtime.

    Side effects:
        - Sets the module-level _current_policy.
        - Forwards extra_ssrf_cidrs to nanobot.security.network.
        - Logs the allowlist for audit.
    """
    global _current_policy
    _current_policy = policy

    if policy.network.extra_ssrf_cidrs:
        configure_ssrf_whitelist(policy.network.extra_ssrf_cidrs)

    logger.info(
        "egress allowlist applied policy={} hosts={}",
        policy.name,
        sorted(policy.network.all_allowed_hosts),
    )


def current_policy() -> Policy | None:
    """Return the currently applied policy, or None if not yet loaded."""
    return _current_policy


def validate_egress(url: str) -> tuple[bool, str]:
    """Validate that *url* is allowed by the active policy.

    Layered check:
        1. URL parses, scheme is http/https. (delegated to nanobot)
        2. Resolved IP is not in nanobot's blocked private nets. (delegated)
        3. Hostname is in the policy's egress allowlist. (Foreman-specific)

    Returns:
        (ok, error_message). When ok is True, error_message is empty.

    Raises:
        PolicyNotLoaded: if apply_policy has not been called. Fail-closed.
    """
    if _current_policy is None:
        raise PolicyNotLoaded(
            "Egress validation called but no policy is loaded. "
            "Call foreman.security.apply_policy() at agent boot."
        )

    # Step 1+2: nanobot's SSRF check (private nets blocked)
    ok, msg = validate_url_target(url)
    if not ok:
        return False, msg

    # Step 3: host allowlist
    try:
        host = urlparse(url).hostname
    except Exception as e:
        return False, f"Invalid URL: {e}"

    if not host:
        return False, "Missing hostname"

    allowed = _current_policy.network.all_allowed_hosts
    host_lower = host.lower()
    if host_lower in {h.lower() for h in allowed}:
        return True, ""

    if _current_policy.audit.log_egress_denials:
        logger.warning(
            "egress denied url={} host={} policy={}",
            url,
            host,
            _current_policy.name,
        )

    return False, (
        f"Host {host!r} not in egress allowlist for policy "
        f"{_current_policy.name!r}. Allowed: {sorted(allowed)}"
    )


def require_outbound_approval() -> bool:
    """Return True if outbound user-visible sends require explicit owner approval.

    Defaults to True if no policy is loaded — fail closed.
    """
    if _current_policy is None:
        return True
    return _current_policy.outbound_send.require_human_approval


def is_channel_auto_approved(channel: str) -> bool:
    """Return True if *channel* is exempted from the approval gate.

    Defaults to False (gate enforced) if no policy is loaded — fail closed.
    """
    if _current_policy is None:
        return False
    return channel in _current_policy.outbound_send.auto_approve_channels
