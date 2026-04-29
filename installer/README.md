# Foreman installer

Installer scaffolding for the four deployment targets Foreman supports per [CLAUDE.md → Deployment targets](../CLAUDE.md#deployment-targets):

```
installer/
├── defaults/
│   └── config.json       # Foreman default config the wizard starts from
├── docker/               # extends upstream Dockerfile + docker-compose.yml (Phase 5)
├── systemd/              # foreman.service unit (Phase 5)
├── launchd/              # com.foreman.agent.plist (Phase 5)
├── windows/              # NSSM-wrapped Windows service (Phase 5)
└── wizard.py             # interactive setup wizard (Phase 5)
```

Most of this lands in **Phase 5** of the bootstrap plan. Today, only `defaults/config.json` exists — it's the baseline the wizard will copy and customize, and it's also what a developer can drop into `~/.foreman/config.json` to bootstrap manually.

## Channel curation

The default config enables four channels for Foreman:

| Channel    | Purpose                                              | Default state |
|------------|------------------------------------------------------|---------------|
| `email`    | Inbound RFQs and outbound draft quotes               | Off (wizard turns on after IMAP/SMTP creds entered) |
| `slack`    | Team coordination on quote review                    | Off (wizard turns on after Slack app provisioned) |
| `cli`      | Owner direct interaction via terminal                | Always on (no config needed) |
| `websocket`| Backs the WebUI for the owner's browser session     | On (local-only by default) |

Other channels (`discord`, `telegram`, `feishu`, `qq`, `weixin`, `wecom`, `dingtalk`, `whatsapp`, `matrix`) remain in the codebase but are not surfaced in the install wizard. Per-channel default is `enabled: false`, so they don't run unless a sophisticated user manually enables them in `~/.foreman/config.json`. Rationale: attack-surface reduction and choice paralysis avoidance — see [CLAUDE.md → What we keep, change, add, remove](../CLAUDE.md#change-small-targeted-edits).

## Provider curation

The wizard surfaces four providers in the curated install path:

| Provider    | Use when                                          |
|-------------|---------------------------------------------------|
| Anthropic   | Cloud, default. Best drawing-extraction quality.  |
| OpenAI      | Cloud, alternate. Fallback if Anthropic outage.   |
| Ollama      | On-prem, local model serving.                     |
| vLLM        | On-prem, high-throughput local inference.         |

The full upstream provider registry (Azure OpenAI, OpenRouter, HuggingFace, GitHub Copilot, OpenAI Codex, etc.) remains available behind an "advanced" toggle in the wizard.

## Manual bootstrap (developer mode)

Until the wizard exists:

```bash
# Copy the default config (do not edit installer/defaults/config.json directly)
mkdir -p ~/.foreman
cp installer/defaults/config.json ~/.foreman/config.json

# Set your provider key in the per-deployment env file
echo "ANTHROPIC_API_KEY=sk-ant-..." > ~/.foreman/.env

# Verify
foreman status
```
