"""Tests for the Foreman policy / egress / approval-gate stack."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

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
    AuditPolicy,
    NetworkPolicy,
    OutboundSendPolicy,
    Policy,
    SandboxPolicy,
    load_policy,
)
from foreman.security.bootstrap import (
    bootstrap_policy,
    resolve_policy_path,
)


# Reset module-state between tests so one test's apply_policy doesn't leak.
@pytest.fixture(autouse=True)
def _reset_policy() -> None:
    import foreman.security.network as fnet
    fnet._current_policy = None
    yield
    fnet._current_policy = None


def _make_policy(
    name: str = "managed-cloud",
    *,
    llm_hosts: list[str] | None = None,
    email_hosts: list[str] | None = None,
    mcp_hosts: list[str] | None = None,
    require_approval: bool = True,
    auto_approve: list[str] | None = None,
) -> Policy:
    return Policy(
        name=name,  # type: ignore[arg-type]
        network=NetworkPolicy(
            llm_provider_hosts=llm_hosts or ["api.anthropic.com"],
            email_servers=email_hosts or [],
            mcp_servers=mcp_hosts or [],
        ),
        outbound_send=OutboundSendPolicy(
            require_human_approval=require_approval,
            auto_approve_channels=auto_approve or [],
        ),
        sandbox=SandboxPolicy(),
        audit=AuditPolicy(),
    )


# ---------------------------------------------------------------------------
# Policy file loading
# ---------------------------------------------------------------------------


class TestPolicyFiles:
    def test_three_shipped_policies_load(self) -> None:
        """All three shipped policy YAMLs must validate cleanly."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        for name in ("managed-cloud", "single-tenant-cloud", "on-prem"):
            path = repo_root / "policies" / f"{name}.yaml"
            assert path.exists(), f"shipped policy missing: {path}"
            policy = load_policy(path)
            assert policy.name == name

    def test_all_policies_require_human_approval(self) -> None:
        """CLAUDE.md non-negotiable #1 — every shipped policy must have it."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        for name in ("managed-cloud", "single-tenant-cloud", "on-prem"):
            policy = load_policy(repo_root / "policies" / f"{name}.yaml")
            assert policy.outbound_send.require_human_approval, (
                f"{name} policy must keep require_human_approval: true"
            )

    def test_on_prem_has_smallest_default_egress(self) -> None:
        """On-prem default ships with no cloud LLM hosts (assumes local inference)."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        on_prem = load_policy(repo_root / "policies" / "on-prem.yaml")
        assert on_prem.network.llm_provider_hosts == []

    def test_unknown_policy_field_rejected(self, tmp_path: Path) -> None:
        """Pydantic 'extra=forbid' should reject typo'd fields — defensive on policy edits."""
        bad = tmp_path / "bad.yaml"
        bad.write_text("name: managed-cloud\nnetwerk:\n  llm_provider_hosts: []\n")
        with pytest.raises(Exception):
            load_policy(bad)


# ---------------------------------------------------------------------------
# Egress allowlist
# ---------------------------------------------------------------------------


class TestEgress:
    def test_validate_egress_fails_when_no_policy_loaded(self) -> None:
        with pytest.raises(PolicyNotLoaded):
            validate_egress("https://api.anthropic.com/v1/messages")

    def test_allowed_host_passes(self) -> None:
        apply_policy(_make_policy(llm_hosts=["api.anthropic.com"]))
        ok, msg = validate_egress("https://api.anthropic.com/v1/messages")
        assert ok, msg

    def test_unallowed_host_denied(self) -> None:
        apply_policy(_make_policy(llm_hosts=["api.anthropic.com"]))
        ok, msg = validate_egress("https://example.com/api")
        assert not ok
        assert "not in egress allowlist" in msg

    def test_email_server_added_to_allowlist(self) -> None:
        apply_policy(_make_policy(email_hosts=["mail.acmeshop.com"]))
        ok, _ = validate_egress("https://mail.acmeshop.com/imap")
        assert ok

    def test_case_insensitive_host_match(self) -> None:
        apply_policy(_make_policy(llm_hosts=["API.Anthropic.com"]))
        ok, _ = validate_egress("https://api.anthropic.com/v1")
        assert ok

    def test_private_ip_blocked_even_if_in_allowlist(self) -> None:
        """nanobot's SSRF check fires before the host allowlist; private nets blocked."""
        apply_policy(_make_policy(llm_hosts=["localhost"]))
        ok, msg = validate_egress("http://127.0.0.1:8080")
        assert not ok

    def test_apply_policy_sets_current_policy(self) -> None:
        assert current_policy() is None
        p = _make_policy()
        apply_policy(p)
        assert current_policy() is p


# ---------------------------------------------------------------------------
# Outbound-send approval gate
# ---------------------------------------------------------------------------


class TestApprovalGate:
    def test_default_require_approval_when_no_policy(self) -> None:
        """Fail-closed: if no policy loaded, treat as require-approval."""
        assert require_outbound_approval() is True
        assert is_channel_auto_approved("email") is False

    def test_require_approval_reflects_policy(self) -> None:
        apply_policy(_make_policy(require_approval=True))
        assert require_outbound_approval() is True

        apply_policy(_make_policy(require_approval=False))
        assert require_outbound_approval() is False

    def test_auto_approve_channels_respected(self) -> None:
        apply_policy(_make_policy(auto_approve=["slack"]))
        assert is_channel_auto_approved("slack") is True
        assert is_channel_auto_approved("email") is False


# ---------------------------------------------------------------------------
# Bootstrap resolution
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_resolve_path_uses_explicit_env_var(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom.yaml"
        custom.write_text("name: managed-cloud\n")
        with patch.dict(os.environ, {"FOREMAN_POLICY_FILE": str(custom)}, clear=False):
            assert resolve_policy_path() == custom

    def test_resolve_path_uses_target_env_var(self) -> None:
        """FOREMAN_POLICY_TARGET resolves to <repo>/policies/<target>.yaml."""
        with patch.dict(os.environ, {"FOREMAN_POLICY_TARGET": "on-prem"}, clear=False):
            os.environ.pop("FOREMAN_POLICY_FILE", None)
            path = resolve_policy_path()
        assert path.name == "on-prem.yaml"
        assert path.parent.name == "policies"

    def test_resolve_path_default_is_managed_cloud(self) -> None:
        """No env vars → default to managed-cloud.yaml."""
        with patch.dict(os.environ, {}, clear=False):
            for var in ("FOREMAN_POLICY_FILE", "FOREMAN_POLICY_TARGET"):
                os.environ.pop(var, None)
            path = resolve_policy_path()
        assert path.name == "managed-cloud.yaml"

    def test_bootstrap_loads_and_applies(self) -> None:
        """End-to-end: bootstrap finds the shipped managed-cloud policy and installs it."""
        with patch.dict(os.environ, {}, clear=False):
            for var in ("FOREMAN_POLICY_FILE", "FOREMAN_POLICY_TARGET"):
                os.environ.pop(var, None)
            policy = bootstrap_policy()
        assert policy.name == "managed-cloud"
        assert current_policy() is not None
        # And the egress check should now work.
        ok, _ = validate_egress("https://api.anthropic.com/v1/messages")
        assert ok

    def test_bootstrap_fails_loud_on_missing_file(self, tmp_path: Path) -> None:
        ghost = tmp_path / "does-not-exist.yaml"
        with patch.dict(os.environ, {"FOREMAN_POLICY_FILE": str(ghost)}, clear=False):
            with pytest.raises(FileNotFoundError):
                bootstrap_policy()
