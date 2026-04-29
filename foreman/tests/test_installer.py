"""Tests for the install wizard: resolution, rendering, runtime-config writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreman.installer import (
    ResolvedConfig,
    render_outputs,
    run_wizard,
    write_runtime_config,
)
from foreman.installer.wizard import EmailConfig


# ---------------------------------------------------------------------------
# Non-interactive resolution
# ---------------------------------------------------------------------------


def _minimum_defaults() -> dict:
    return {
        "deployment_target": "docker",
        "policy_target": "managed-cloud",
        "owner_email": "owner@acmeshop.com",
        "llm_provider": "anthropic",
        "llm_api_key": "sk-ant-fake",
    }


class TestResolution:
    def test_minimum_defaults_resolve(self) -> None:
        config = run_wizard(non_interactive=True, defaults=_minimum_defaults())
        assert isinstance(config, ResolvedConfig)
        assert config.deployment_target == "docker"
        assert config.llm_model == "claude-opus-4-7"  # provider-default

    def test_missing_required_raises(self) -> None:
        with pytest.raises(ValueError, match="non-interactive wizard requires"):
            run_wizard(non_interactive=True, defaults={"deployment_target": "docker"})

    def test_email_config_inferred_unconfigured_when_blank(self) -> None:
        config = run_wizard(non_interactive=True, defaults=_minimum_defaults())
        assert config.email.configured is False

    def test_email_configured_when_hosts_present(self) -> None:
        d = {**_minimum_defaults(), "email_imap_host": "mail.x", "email_smtp_host": "mail.x", "email_imap_user": "u"}
        config = run_wizard(non_interactive=True, defaults=d)
        assert config.email.configured is True


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def _docker_config() -> ResolvedConfig:
    return run_wizard(
        non_interactive=True,
        defaults={**_minimum_defaults(), "deployment_target": "docker"},
    )


class TestRendering:
    def test_renders_docker_compose_overlay(self, tmp_path: Path) -> None:
        config = _docker_config()
        rendered = render_outputs(config, output_dir=tmp_path)
        assert "docker-compose.foreman.yml" in rendered
        text = rendered["docker-compose.foreman.yml"].read_text(encoding="utf-8")
        assert "FOREMAN_POLICY_TARGET" in text
        assert "managed-cloud" in text
        assert str(config.workspace_dir) in text

    def test_renders_systemd_unit(self, tmp_path: Path) -> None:
        config = run_wizard(
            non_interactive=True,
            defaults={**_minimum_defaults(), "deployment_target": "systemd"},
        )
        rendered = render_outputs(config, output_dir=tmp_path)
        assert "foreman.service" in rendered
        text = rendered["foreman.service"].read_text(encoding="utf-8")
        assert "[Service]" in text
        assert "ExecStart=" in text
        assert "FOREMAN_POLICY_TARGET=managed-cloud" in text

    def test_renders_launchd_plist(self, tmp_path: Path) -> None:
        config = run_wizard(
            non_interactive=True,
            defaults={**_minimum_defaults(), "deployment_target": "launchd"},
        )
        rendered = render_outputs(config, output_dir=tmp_path)
        assert "com.foreman.agent.plist" in rendered
        text = rendered["com.foreman.agent.plist"].read_text(encoding="utf-8")
        assert "<key>Label</key>" in text
        assert "com.foreman.agent" in text

    def test_renders_windows_nssm_script(self, tmp_path: Path) -> None:
        config = run_wizard(
            non_interactive=True,
            defaults={**_minimum_defaults(), "deployment_target": "windows"},
        )
        rendered = render_outputs(config, output_dir=tmp_path)
        assert "install_foreman_service.ps1" in rendered
        text = rendered["install_foreman_service.ps1"].read_text(encoding="utf-8")
        assert "nssm install" in text
        assert "FOREMAN_POLICY_TARGET" in text


# ---------------------------------------------------------------------------
# Runtime config + .env
# ---------------------------------------------------------------------------


class TestRuntimeConfig:
    def test_writes_config_json(self, tmp_path: Path) -> None:
        config = _docker_config()
        config.env_file_path = tmp_path / ".env"
        written = write_runtime_config(config, foreman_home=tmp_path)
        assert written["config_json"].exists()
        payload = json.loads(written["config_json"].read_text(encoding="utf-8"))
        assert payload["agents"]["defaults"]["model"] == "anthropic/claude-opus-4-7"
        assert payload["providers"]["anthropic"]["api_key"] == "${ANTHROPIC_API_KEY}"

    def test_writes_env_file_with_api_key(self, tmp_path: Path) -> None:
        config = _docker_config()
        config.env_file_path = tmp_path / ".env"
        written = write_runtime_config(config, foreman_home=tmp_path)
        env_text = written["env_file"].read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY=sk-ant-fake" in env_text
        assert "FOREMAN_POLICY_TARGET=managed-cloud" in env_text

    def test_secrets_never_inlined_in_config_json(self, tmp_path: Path) -> None:
        """The api_key should be a ${VAR} interpolation, not the actual key value."""
        config = _docker_config()
        config.env_file_path = tmp_path / ".env"
        written = write_runtime_config(config, foreman_home=tmp_path)
        text = written["config_json"].read_text(encoding="utf-8")
        assert "sk-ant-fake" not in text, (
            "config.json must use ${ANTHROPIC_API_KEY} interpolation, not inline secrets"
        )

    def test_local_provider_uses_custom_endpoint(self, tmp_path: Path) -> None:
        config = run_wizard(
            non_interactive=True,
            defaults={
                **_minimum_defaults(),
                "llm_provider": "ollama",
                "llm_api_key": None,
            },
        )
        config.env_file_path = tmp_path / ".env"
        written = write_runtime_config(config, foreman_home=tmp_path)
        payload = json.loads(written["config_json"].read_text(encoding="utf-8"))
        assert "custom" in payload["providers"]
        assert "11434" in payload["providers"]["custom"]["api_base"]

    def test_email_block_added_when_configured(self, tmp_path: Path) -> None:
        d = {
            **_minimum_defaults(),
            "email_imap_host": "imap.acmeshop.com",
            "email_imap_user": "foreman@acmeshop.com",
            "email_imap_pass": "secret",
            "email_smtp_host": "smtp.acmeshop.com",
            "email_smtp_user": "foreman@acmeshop.com",
            "email_smtp_pass": "secret",
            "email_allow_from": ["acmeshop.com"],
        }
        config = run_wizard(non_interactive=True, defaults=d)
        config.env_file_path = tmp_path / ".env"
        written = write_runtime_config(config, foreman_home=tmp_path)
        payload = json.loads(written["config_json"].read_text(encoding="utf-8"))
        assert payload["channels"]["email"]["enabled"] is True
        assert payload["channels"]["email"]["imap_password"] == "${FOREMAN_EMAIL_IMAP_PASS}"
        env_text = written["env_file"].read_text(encoding="utf-8")
        assert "FOREMAN_EMAIL_IMAP_PASS=secret" in env_text
