"""The install wizard: six prompts → ResolvedConfig → rendered deployment.

Non-interactive entry points (`run_wizard(non_interactive=True, defaults=...)`)
exist for tests and scripted installs; interactive mode uses `questionary` for
the actual prompts.

Six prompts (per CLAUDE.md → installer):
    1. Deployment target (docker / systemd / launchd / windows)
    2. LLM provider + key (anthropic / openai / ollama / vllm)
    3. Email IMAP/SMTP creds + allowed-from list
    4. Network policy file (managed-cloud / single-tenant-cloud / on-prem)
    5. Personality / workspace path
    6. Owner email for approval-required notifications

The wizard never writes secrets to the repo. The .env file lives at the
deployment-specific path the user picks (default ~/.foreman/.env).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from jinja2 import Template

# Platform of the install ===================================================
DeploymentTarget = Literal["docker", "systemd", "launchd", "windows"]
PolicyTarget = Literal["managed-cloud", "single-tenant-cloud", "on-prem"]
LLMProvider = Literal["anthropic", "openai", "ollama", "vllm"]


_PROVIDER_DEFAULT_MODEL: dict[str, str] = {
    "anthropic": "claude-opus-4-7",
    "openai": "gpt-5.0",
    "ollama": "llama3.1:8b",
    "vllm": "meta-llama/Llama-3.1-8B-Instruct",
}


# ---------------------------------------------------------------------------
# Resolved config
# ---------------------------------------------------------------------------


@dataclass
class EmailConfig:
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_pass: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    allow_from: list[str] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return bool(self.imap_host and self.smtp_host and self.imap_user)


@dataclass
class ResolvedConfig:
    """Complete answer set from the wizard, ready to render templates against."""

    deployment_target: DeploymentTarget
    policy_target: PolicyTarget
    install_dir: Path
    workspace_dir: Path
    env_file_path: Path

    llm_provider: LLMProvider
    llm_api_key: str | None  # None when local provider
    llm_model: str

    email: EmailConfig

    owner_email: str

    shop_name: str = ""
    gateway_port: int = 18790
    home: Path = field(default_factory=Path.home)
    run_user: str = "foreman"
    run_group: str = "foreman"

    @property
    def policy_file_path(self) -> Path:
        """Where the chosen policy YAML lives in the install directory."""
        return self.install_dir / "policies" / f"{self.policy_target}.yaml"

    def template_context(self) -> dict[str, Any]:
        """Flatten + stringify so Jinja templates can consume."""
        ctx = {
            **asdict(self),
            "email_inline": asdict(self.email),
            "policy_file_path": str(self.policy_file_path),
            "install_dir": str(self.install_dir),
            "workspace_dir": str(self.workspace_dir),
            "env_file_path": str(self.env_file_path),
            "home": str(self.home),
        }
        # Inline env vars surfaced to LaunchAgent (key=value pairs that
        # belong inside <EnvironmentVariables>).
        env_inline = {}
        if self.llm_api_key and self.llm_provider in ("anthropic", "openai"):
            env_inline[f"{self.llm_provider.upper()}_API_KEY"] = "(see env_file)"
        ctx["env_inline"] = env_inline
        return ctx


# ---------------------------------------------------------------------------
# Wizard (interactive)
# ---------------------------------------------------------------------------


def run_wizard(
    *,
    non_interactive: bool = False,
    defaults: dict[str, Any] | None = None,
) -> ResolvedConfig:
    """Run the install wizard. Returns a ResolvedConfig.

    Args:
        non_interactive: If True, take all values from `defaults` and never
            prompt. Test-friendly. Required keys in defaults match the
            ResolvedConfig field names.
        defaults: Pre-populated values that, in interactive mode, become the
            default answer for each prompt.
    """
    d = defaults or {}

    if non_interactive:
        return _build_from_defaults(d)

    import questionary  # local import: only required when running interactively

    target = questionary.select(
        "Deployment target?",
        choices=["docker", "systemd", "launchd", "windows"],
        default=d.get("deployment_target", "docker"),
    ).ask()

    policy = questionary.select(
        "Network policy?",
        choices=["managed-cloud", "single-tenant-cloud", "on-prem"],
        default=d.get("policy_target", "managed-cloud"),
    ).ask()

    install_dir = questionary.text(
        "Install directory?",
        default=str(d.get("install_dir", Path.home() / "foreman")),
    ).ask()

    workspace_dir = questionary.text(
        "Workspace / personality directory?",
        default=str(d.get("workspace_dir", Path.home() / ".foreman" / "workspace")),
    ).ask()

    env_file = questionary.text(
        "Where should the .env file live (per-deployment, holds API keys)?",
        default=str(d.get("env_file_path", Path.home() / ".foreman" / ".env")),
    ).ask()

    provider = questionary.select(
        "LLM provider?",
        choices=["anthropic", "openai", "ollama", "vllm"],
        default=d.get("llm_provider", "anthropic"),
    ).ask()

    api_key: str | None = None
    if provider in ("anthropic", "openai"):
        api_key = questionary.password(
            f"{provider.upper()} API key?",
            default=d.get("llm_api_key", "") or "",
        ).ask()

    model = questionary.text(
        "LLM model name?",
        default=d.get("llm_model", _PROVIDER_DEFAULT_MODEL[provider]),
    ).ask()

    print("\nEmail (inbound RFQs + outbound draft quotes). Leave blank to skip.")
    email = EmailConfig(
        imap_host=questionary.text("IMAP host?", default=d.get("email_imap_host", "")).ask() or "",
        imap_port=int(questionary.text("IMAP port?", default=str(d.get("email_imap_port", 993))).ask() or 993),
        imap_user=questionary.text("IMAP username?", default=d.get("email_imap_user", "")).ask() or "",
        imap_pass=questionary.password("IMAP password?", default=d.get("email_imap_pass", "") or "").ask() or "",
        smtp_host=questionary.text("SMTP host?", default=d.get("email_smtp_host", "")).ask() or "",
        smtp_port=int(questionary.text("SMTP port?", default=str(d.get("email_smtp_port", 587))).ask() or 587),
        smtp_user=questionary.text("SMTP username?", default=d.get("email_smtp_user", "")).ask() or "",
        smtp_pass=questionary.password("SMTP password?", default=d.get("email_smtp_pass", "") or "").ask() or "",
        allow_from=_split_csv(questionary.text(
            "Allowed sender domains (comma-separated)?",
            default=d.get("email_allow_from_csv", ""),
        ).ask() or ""),
    )

    owner_email = questionary.text(
        "Owner email for approval-required notifications?",
        default=d.get("owner_email", ""),
    ).ask() or ""

    shop_name = questionary.text(
        "Shop name (optional, for service descriptions)?",
        default=d.get("shop_name", ""),
    ).ask() or ""

    return ResolvedConfig(
        deployment_target=target,
        policy_target=policy,
        install_dir=Path(install_dir).expanduser(),
        workspace_dir=Path(workspace_dir).expanduser(),
        env_file_path=Path(env_file).expanduser(),
        llm_provider=provider,
        llm_api_key=api_key,
        llm_model=model,
        email=email,
        owner_email=owner_email,
        shop_name=shop_name,
    )


def _split_csv(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _build_from_defaults(d: dict[str, Any]) -> ResolvedConfig:
    """Construct ResolvedConfig from a flat dict (non-interactive / test)."""
    required = ("deployment_target", "policy_target", "owner_email", "llm_provider")
    missing = [k for k in required if k not in d]
    if missing:
        raise ValueError(f"non-interactive wizard requires: {missing}")

    provider = d["llm_provider"]
    return ResolvedConfig(
        deployment_target=d["deployment_target"],
        policy_target=d["policy_target"],
        install_dir=Path(d.get("install_dir", Path.home() / "foreman")).expanduser(),
        workspace_dir=Path(d.get("workspace_dir", Path.home() / ".foreman" / "workspace")).expanduser(),
        env_file_path=Path(d.get("env_file_path", Path.home() / ".foreman" / ".env")).expanduser(),
        llm_provider=provider,
        llm_api_key=d.get("llm_api_key"),
        llm_model=d.get("llm_model", _PROVIDER_DEFAULT_MODEL[provider]),
        email=EmailConfig(
            imap_host=d.get("email_imap_host", ""),
            imap_port=int(d.get("email_imap_port", 993)),
            imap_user=d.get("email_imap_user", ""),
            imap_pass=d.get("email_imap_pass", ""),
            smtp_host=d.get("email_smtp_host", ""),
            smtp_port=int(d.get("email_smtp_port", 587)),
            smtp_user=d.get("email_smtp_user", ""),
            smtp_pass=d.get("email_smtp_pass", ""),
            allow_from=d.get("email_allow_from", []),
        ),
        owner_email=d["owner_email"],
        shop_name=d.get("shop_name", ""),
        gateway_port=int(d.get("gateway_port", 18790)),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


_TEMPLATE_FILES: dict[DeploymentTarget, list[tuple[str, str]]] = {
    "docker": [("installer/docker/docker-compose.foreman.yml", "docker-compose.foreman.yml")],
    "systemd": [("installer/systemd/foreman.service.template", "foreman.service")],
    "launchd": [("installer/launchd/com.foreman.agent.plist.template", "com.foreman.agent.plist")],
    "windows": [("installer/windows/install_foreman_service.ps1.template", "install_foreman_service.ps1")],
}


def render_outputs(
    config: ResolvedConfig,
    output_dir: Path,
    *,
    repo_root: Path | None = None,
) -> dict[str, Path]:
    """Render the platform-specific templates into output_dir.

    Returns a dict mapping output filenames to absolute paths.
    """
    output_dir = output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    repo = repo_root or _default_repo_root()
    written: dict[str, Path] = {}
    for template_rel, dest_name in _TEMPLATE_FILES[config.deployment_target]:
        template_path = repo / template_rel
        if not template_path.exists():
            raise FileNotFoundError(f"Template missing: {template_path}")
        rendered = Template(template_path.read_text(encoding="utf-8")).render(
            **config.template_context()
        )
        dest = output_dir / dest_name
        dest.write_text(rendered, encoding="utf-8")
        written[dest_name] = dest
    return written


def _default_repo_root() -> Path:
    """foreman/installer/wizard.py → foreman/ → repo root."""
    return Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Runtime config writers (~/.foreman/config.json + .env)
# ---------------------------------------------------------------------------


def write_runtime_config(config: ResolvedConfig, foreman_home: Path | None = None) -> dict[str, Path]:
    """Write ~/.foreman/config.json and ~/.foreman/.env from the resolved config.

    Returns a dict {kind: path} of files written.
    """
    home = (foreman_home or Path.home() / ".foreman").expanduser()
    home.mkdir(parents=True, exist_ok=True)

    # 1. config.json (read by nanobot's loader)
    config_payload: dict[str, Any] = {
        "_comment": (
            "Generated by `foreman install`. Edit by hand or rerun the "
            "wizard. Secrets live in the .env file referenced via "
            "${VAR_NAME} interpolation, NOT here."
        ),
        "agents": {
            "defaults": {
                "workspace": str(config.workspace_dir),
                "model": f"{config.llm_provider}/{config.llm_model}",
                "provider": config.llm_provider,
                "temperature": 0.3,
                "max_tokens": 8192,
                "max_tool_iterations": 30,
            }
        },
        "providers": _provider_block(config),
        "channels": _channels_block(config),
    }
    config_path = home / "config.json"
    config_path.write_text(json.dumps(config_payload, indent=2), encoding="utf-8")

    # 2. .env (per-deployment secrets)
    env_path = config.env_file_path
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Generated by `foreman install`. Do NOT commit this file."]
    if config.llm_api_key:
        env_var = f"{config.llm_provider.upper()}_API_KEY"
        lines.append(f"{env_var}={config.llm_api_key}")
    if config.email.configured:
        lines.append(f"FOREMAN_EMAIL_IMAP_PASS={config.email.imap_pass}")
        lines.append(f"FOREMAN_EMAIL_SMTP_PASS={config.email.smtp_pass}")
    lines.append(f"FOREMAN_POLICY_TARGET={config.policy_target}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Best-effort permissions tighten on POSIX
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass

    return {"config_json": config_path, "env_file": env_path}


def _provider_block(config: ResolvedConfig) -> dict[str, Any]:
    """Build the providers.<name> section for nanobot config.json."""
    if config.llm_provider in ("anthropic", "openai"):
        env_var = f"{config.llm_provider.upper()}_API_KEY"
        return {config.llm_provider: {"api_key": f"${{{env_var}}}"}}
    # Local providers don't need a key; assume the OpenAI-compat endpoint.
    if config.llm_provider == "ollama":
        return {"custom": {"api_base": "http://localhost:11434/v1"}}
    if config.llm_provider == "vllm":
        return {"custom": {"api_base": "http://localhost:8000/v1"}}
    return {}


def _channels_block(config: ResolvedConfig) -> dict[str, Any]:
    """Build the channels.* section. Curated to email/slack/cli/websocket per CLAUDE.md."""
    block: dict[str, Any] = {
        "send_progress": True,
        "send_tool_hints": False,
        "websocket": {"enabled": True},
    }
    if config.email.configured:
        block["email"] = {
            "enabled": True,
            "imap_host": config.email.imap_host,
            "imap_port": config.email.imap_port,
            "imap_username": config.email.imap_user,
            "imap_password": "${FOREMAN_EMAIL_IMAP_PASS}",
            "smtp_host": config.email.smtp_host,
            "smtp_port": config.email.smtp_port,
            "smtp_username": config.email.smtp_user,
            "smtp_password": "${FOREMAN_EMAIL_SMTP_PASS}",
            "allow_from": config.email.allow_from,
            "verify_dkim": True,
            "verify_spf": True,
        }
    return block
