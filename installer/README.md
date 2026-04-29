# Foreman installer

Six prompts → ready-to-deploy Foreman on the platform of your choice. Brings a non-technical shop from "we have a machine" to "Foreman is reading our email" in under an hour per CLAUDE.md → Phase plan.

```
installer/
├── docker/
│   └── docker-compose.foreman.yml         # Jinja overlay on upstream compose
├── systemd/
│   └── foreman.service.template           # Linux native service unit
├── launchd/
│   └── com.foreman.agent.plist.template   # macOS LaunchAgent
├── windows/
│   └── install_foreman_service.ps1.template  # NSSM-wrapped Windows service
├── defaults/
│   └── config.json                        # baseline config the wizard starts from
└── README.md                              # this file
```

## Run the wizard

```bash
foreman install
```

Six prompts:

1. **Deployment target** — `docker` / `systemd` / `launchd` / `windows`
2. **Network policy** — `managed-cloud` / `single-tenant-cloud` / `on-prem`
3. **Install + workspace + .env paths** — three subprompts
4. **LLM provider + key** — `anthropic` / `openai` / `ollama` / `vllm`
5. **Email IMAP / SMTP creds + allowed-from list** — leave blank to skip
6. **Owner email** for approval-required notifications

The wizard then renders the platform-specific deployment file into `./foreman-install/` (configurable with `--output-dir`), and writes:

- `~/.foreman/config.json` — runtime config nanobot reads at boot
- the `.env` file at the path you picked — holds API keys and email passwords (referenced from `config.json` via `${VAR}` interpolation; secrets never inlined)

## Non-interactive mode

For CI, scripted re-deploys, or testing:

```bash
foreman install --non-interactive --defaults answers.yaml
```

Where `answers.yaml` provides the same six answers in YAML form. Required keys: `deployment_target`, `policy_target`, `owner_email`, `llm_provider`. See `foreman/tests/test_installer.py::_minimum_defaults` for a reference.

## Per-target next steps

After the wizard finishes:

### Docker

```bash
docker compose -f docker-compose.yml \
  -f foreman-install/docker-compose.foreman.yml up -d
docker logs -f foreman
```

### systemd (Linux)

```bash
sudo cp foreman-install/foreman.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now foreman
journalctl -u foreman -f
```

### macOS LaunchAgent

```bash
cp foreman-install/com.foreman.agent.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.foreman.agent.plist
tail -f ~/Library/Logs/Foreman/foreman.out.log
```

### Windows (NSSM)

```powershell
# As Administrator. Requires NSSM installed and on PATH.
powershell -ExecutionPolicy Bypass -File foreman-install\install_foreman_service.ps1
nssm status Foreman
```

## Channel curation (default)

| Channel    | Purpose                                              | Default state |
|------------|------------------------------------------------------|---------------|
| `email`    | Inbound RFQs and outbound draft quotes               | Off (wizard turns on after IMAP/SMTP creds entered) |
| `slack`    | Team coordination on quote review                    | Off (configure post-install) |
| `cli`      | Owner direct interaction via terminal                | Always on (no config needed) |
| `websocket`| Backs the WebUI for the owner's browser session     | On (local-only by default) |

Other channels (`discord`, `telegram`, `feishu`, `qq`, `weixin`, `wecom`, `dingtalk`, `whatsapp`, `matrix`) remain in the codebase but are not surfaced in the wizard. Per-channel default is `enabled: false`. Rationale: attack-surface reduction and choice-paralysis avoidance — see [CLAUDE.md → What we keep, change, add, remove](../CLAUDE.md#change-small-targeted-edits).

## Provider curation (default)

| Provider    | Use when                                          |
|-------------|---------------------------------------------------|
| Anthropic   | Cloud, default. Best drawing-extraction quality.  |
| OpenAI      | Cloud, alternate. Fallback if Anthropic outage.   |
| Ollama      | On-prem, local model serving.                     |
| vLLM        | On-prem, high-throughput local inference.         |

Other upstream providers (Azure OpenAI, OpenRouter, HuggingFace, GitHub Copilot, OpenAI Codex, etc.) remain available — set them by hand-editing `~/.foreman/config.json`.

## What the wizard does NOT do

- It does NOT install Docker / systemd / NSSM. Those are user prerequisites.
- It does NOT call `systemctl enable` / `launchctl load` / `nssm start` for you. The wizard generates the files; the user runs the install command.
- It does NOT pull the GPU model (Ollama / vLLM) for you. Local-provider users handle that separately.
- It does NOT verify your provider key works. Run `foreman agent -m "ping"` after install to confirm.
