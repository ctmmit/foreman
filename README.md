# Foreman

> An agent for the shop owner. The shop's deputy. Skills compose. The network emerges.

Foreman is a long-running agent that represents the owner of a small or mid-size US machine shop. It has its own company email address, access to the shop's drives and ERP, and the authority to act on the owner's behalf within explicit policy bounds. It learns continuously: every owner correction ("Boeing pays slow, add 8 percent") is captured and recalled the next time the same situation arises. It is the shop's digital deputy.

Each shop gets an agent. The agent gets skills. The network is what emerges.

**License:** MIT (this repo) + MIT (upstream [HKUDS/nanobot](https://github.com/HKUDS/nanobot))
**Status:** Work in progress. MIT AI Studio (MAS.664) final project — team Aline Zimerman, Colin McGonigle, Omar Dominguez.

---

## Why this exists

The United States operates roughly 17,000 small and mid-size machine shops. They are the operational backbone of domestic manufacturing, deeply trusted by their customers, and almost entirely undigitized. The conventional play is a centralized SaaS marketplace. It fails because the shop's moat is the customer relationship and the routing memory, not raw capacity.

Foreman takes the opposite approach. Per-shop agency first; the network forms from the bottom up.

---

## What the agent is

Four properties make a shop owner's agent the right primitive.

**Represents the owner.** Not a chatbot. The agent has its own company email address, access to the shop's drives, ERP, and CAD repositories, and the authority to act on the owner's behalf within policy bounds. When a customer emails an RFQ, Foreman receives it directly.

**Knows the shop.** From day one the agent ingests what the shop manufactures, the equipment list, the customer history, the pricing patterns, and the routing memory. Every owner correction is captured and recalled on the next matching situation. Institutional knowledge becomes queryable.

**Sovereign by configuration.** The shop chooses the deployment target — managed Foreman cloud, the shop's own cloud account, or on-prem hardware. Defense work, ITAR exposure, regulated programs: same code, same skills, same memory model — only the deployment target changes. Sovereignty is a configuration, not a product tier.

**Open source.** MIT-licensed. Inspectable, forkable, and deployable without vendor lock-in. This is what keeps the long-arc vision credible to sovereignty-obsessed buyers — government, defense, OEMs concerned with industrial-base resilience.

---

## How capability ships

The shop agent is the operating layer. Capability ships as **skills** — small, independently testable units (a `SKILL.md` plus a registered Python tool). New capabilities ship as new skills, not as new code paths in a monolith. Skills can be authored by Foreman, by third parties, or by the shops themselves.

**Today: the Quoting bundle (seven skills).** The first generation addresses responding to a customer RFQ — the most painful and most universal SMB-manufacturing workflow.

| Skill | What it does |
|---|---|
| [`shop-extract-drawing`](./nanobot/skills/shop-extract-drawing/SKILL.md) | Drawing PDF → structured schema (material, tolerances, features, finish, threads). Vision-LLM call with a confidence floor of 0.95 on tolerance fields. |
| [`shop-retrieve-similar-jobs`](./nanobot/skills/shop-retrieve-similar-jobs/SKILL.md) | Top-3 historical jobs for material + customer, including at least one loss for benchmark pricing. |
| [`shop-check-material`](./nanobot/skills/shop-check-material/SKILL.md) | Raw-material inventory and supplier lead time. |
| [`shop-check-schedule`](./nanobot/skills/shop-check-schedule/SKILL.md) | Machine slack and earliest available production slot. |
| [`shop-recall-personality`](./nanobot/skills/shop-recall-personality/SKILL.md) | Customer-gated retrieval of prior owner feedback. Called before every compose. |
| [`shop-compose-quote`](./nanobot/skills/shop-compose-quote/SKILL.md) | Final draft quote under one of three steering profiles (conservative / balanced / aggressive). Personality deltas applied on top. Deterministic math, auditable. |
| [`shop-remember-feedback`](./nanobot/skills/shop-remember-feedback/SKILL.md) | Persists owner corrections to the personality store. Called automatically on every correction. |

The orchestration recipe the agent follows for end-to-end quoting is [`foreman-quote-rfq`](./skills/foreman-quote-rfq/SKILL.md).

**Next: every white-collar workflow inside the shop.** Scheduling, procurement, capacity planning, customer follow-up, pricing strategy, succession planning, financial reporting. Each new skill compounds the agent's value to the owner without making the runtime more complex.

**Eventually: outside the walls of the shop.** Once Foremans are deployed at scale, they develop skills to interact with each other and with buyer-side agents — quoting jobs to other shops' agents, brokering overflow capacity, exposing operational state to buyers under policy. Federation is deferred until enough Foremans exist to make it useful, and only as opt-in skills the owner enables. The architecture today preserves that arc without committing to it.

---

## The hero behavior: the learning loop

This is the agentic moment — the proof that the primitive works.

```bash
# t=0: initial quote, no prior feedback for this customer
foreman agent -m "Quote demo_1.pdf for the aerospace customer, 150 pcs, balanced profile"
# → $31.00/u, $4,650, 7 days

# t=1: owner correction in plain English. No "remember this" needed.
foreman agent -m "Too low. They always pay slow. Add 8 percent."
# → shop-remember-feedback fires automatically; correction persisted to the personality store
#   with audit_log entry stamped "shop-remember-feedback".

# t=2: a different drawing for the same customer
foreman agent -m "Quote demo_3.pdf for the aerospace customer, 80 pcs, balanced"
# → $68.85/u (was $63.75 neutral, +8% applied)
# Reasoning field cites the prior feedback verbatim and shows the math:
#   "neutral $63.75/u → +8% margin → $68.85/u"
```

Every other skill in the library composes against the same memory.

---

## Architecture at a glance

```
nanobot/                        # upstream agent runtime, pinned at v0.1.5.post3
  agent/loop.py                 # +4 lines wiring Foreman: bootstrap policy, register tools
  cli/commands.py               # +3 lines registering `foreman install` and `foreman queue ...`
  channels/                     # email, slack, cli, websocket (rest disabled by default)
  templates/SOUL.md             # shop-deputy persona

foreman/                        # all Foreman-specific code lives here
  memory/                       # ForemanMemoryStore: 7 structured personality slots,
                                #   audit-log-on-write, customer-id resolver
  tools/                        # the 7 shop-* Python tools
  security/                     # policy schema, egress allowlist, outbound-send gate
  installer/                    # wizard + 4 platform templates
  cli/                          # `foreman install`, `foreman queue ...`
  queue/                        # outbound queue store
  hooks/                        # personality-write telemetry
  tests/                        # 103 tests passing

skills/foreman-quote-rfq/       # orchestration recipe (LLM-facing markdown)
nanobot/skills/shop-*/          # the 7 sub-skill SKILL.md guides
nanobot/skills/foreman-quote-rfq/  # mirror so nanobot's loader picks it up

policies/                       # 3 deployment policies (managed-cloud / single-tenant / on-prem)
installer/                      # platform templates (Docker / systemd / launchd / Windows NSSM)
```

The internal package is named `nanobot` to keep upstream merges clean; only user-facing surfaces (CLI, persona, branding, paths) are rebranded to Foreman.

---

## Capabilities by layer

### Communication
- **Email** (inbound RFQs + outbound draft quotes). IMAP polling, SMTP send, attachment allowlist restricted to drawing formats (`.pdf .dwg .dxf .step .stp .iges .igs`), DKIM/SPF self-loop guard.
- **Slack** for team coordination on quote review.
- **CLI** for direct owner interaction.
- **WebUI** via WebSocket for the owner's browser session.
- Other channels (Discord, Telegram, Feishu, QQ, WeChat, WeCom, DingTalk, WhatsApp, Matrix) remain in the codebase but are off by default. Attack-surface reduction.

### Memory and learning
- **Personality store** — seven structured slots: `shop_profile`, `equipment[]`, `customers[customer_id]`, `materials[material_code]`, `routing_memory[(process, material)]`, `pricing_corrections[(customer_id, context)]`, `audit_log` (append-only).
- **Customer-id resolver** with confidence-gated escalation. Wrong customer → wrong recalled feedback → wrong margin applied. Below 0.9 confidence the agent escalates to the owner instead of guessing. Property-tested.
- **Audit log on every personality write** — the agent's authority comes from being correctable. Every write records caller / timestamp / slot / delta. Reversible.
- **Dream memory** (free-form markdown, cron-driven consolidation) inherited from upstream nanobot.

### Safety and policy
- **Three deployment policies** in [`policies/`](./policies): `managed-cloud.yaml`, `single-tenant-cloud.yaml`, `on-prem.yaml`.
- **Egress allowlist** layered on nanobot's SSRF defense — outbound HTTP only to the configured LLM provider, the email server, and explicitly enumerated MCP servers. Anything else denied.
- **Outbound-send approval gate** (CLAUDE.md non-negotiable #1) enforced via `ForemanMessageTool`. Blocked sends land in `workspace/personality/outbound_queue.jsonl` for owner review through `foreman queue list / approve / reject`.
- **Drawings never leave the deployment.** The on-prem policy ships with `llm_provider_hosts: []` — assumes local Ollama / vLLM, no cloud reach.

### LLM providers
Curated in the install wizard: **Anthropic** (default cloud), **OpenAI** (alternate cloud), **Ollama** (on-prem local), **vLLM** (on-prem high-throughput). The full upstream registry (Azure OpenAI, OpenRouter, HuggingFace, GitHub Copilot, OpenAI Codex, etc.) remains accessible behind an "advanced" toggle.

### Deployment
Four platform packagings, all from a unified setup wizard:
- **Docker / docker-compose** — extends upstream `Dockerfile`. Default for managed and single-tenant cloud.
- **systemd service unit** — Linux native (`Restart=on-failure`, `User=foreman`, journald logging).
- **macOS LaunchAgent** — `com.foreman.agent.plist`, KeepAlive on, logs under `~/Library/Logs/Foreman/`.
- **Windows service** — wrapped via [NSSM](https://nssm.cc/), logs to `%ProgramData%\Foreman\logs\` + Windows Event Log.

---

## Quickstart

### Developer (read the code, run the tests)

```bash
git clone https://github.com/ctmmit/foreman
cd foreman
uv sync
uv run python -m pytest foreman/tests        # 103 tests
uv run foreman --version                     # 🔧 Foreman v0.1.0
```

### Shop deployment (six prompts to a running Foreman)

```bash
foreman install
# Six prompts:
#  1. Deployment target?       docker / systemd / launchd / windows
#  2. Network policy?          managed-cloud / single-tenant-cloud / on-prem
#  3. Install + workspace + .env paths
#  4. LLM provider + key?      anthropic / openai / ollama / vllm
#  5. Email IMAP/SMTP creds + allowed-from list  (skip to configure later)
#  6. Owner email for approval-required notifications

# Then the platform-native install command (the wizard prints exact next steps).
# Example for systemd:
sudo cp foreman-install/foreman.service /etc/systemd/system/
sudo systemctl enable --now foreman
journalctl -u foreman -f
```

The wizard generates the deployment file(s), writes `~/.foreman/config.json` (no inlined secrets — provider keys surface as `${ANTHROPIC_API_KEY}` interpolation), and writes a per-deployment `.env` chmod'd to `0600` on POSIX.

### Inspect the outbound queue (owner approval workflow)

```bash
foreman queue list                    # pending blocked sends
foreman queue show <queue_id>         # full content of one entry
foreman queue approve <queue_id>      # mark approved + audit
foreman queue reject <queue_id> --note "wrong customer"
```

---

## What this is NOT

- **Not a SaaS marketplace.** No central operator. No shared cloud database of shop activity. Each shop owns its data, its memory, and its behavior.
- **Not a chatbot.** Foreman acts on the owner's behalf within policy. Outbound communication requires owner approval (gate enforced in code, not just declared).
- **Not a replacement for the ERP.** Foreman sits on top. ProShop, JobBOSS, E2, Global Shop, SolidWorks remain the systems of record. Adapters wire in read-only first; write operations require human approval.
- **Not a quoting tool.** Quoting is the first skill bundle. Scheduling, procurement, capacity planning, follow-up, pricing strategy, financial reporting all become skills as they ship. The runtime stays unchanged.
- **Not autonomous.** The agent composes drafts. The owner clicks send. Phase One non-negotiable.

---

## Why this is the agentic-web thesis

The course thesis is that the web is being rebuilt as a network of agents that act on behalf of users, coordinate through shared protocols, and accumulate trust over time. Foreman applies that thesis to a vertical that needs it most.

- **Per-user agency.** Every shop has its own agent, with its own memory, policy, and authorized actions. This is the foundational primitive of the agentic web — per-user agents must exist before any network can form.
- **Skills compose.** New capabilities ship as new skills. The agent gets more useful every quarter without becoming more complex. The skill library is the moat.
- **Trust without centralization.** Each shop owns its data. No marketplace operator sits in the middle.
- **Phase Three — network capabilities at scale.** Once enough Foremans are deployed, they develop skills to interact outside the walls of the shop — buyer's procurement agent calls `shop-quote(drawing, qty, due_date)` directly; a partner shop's Foreman brokers an outside-process job; excess capacity routes opt-in across a regional cluster. None of this requires a central operator. The architecture today preserves the right to every layer above; it does not commit to any of them.

The conventional play (Xometry, Fictiv, Hubs) forecloses that arc by capturing the customer relationship on day one. The agentic-web play does not require that capture. Each shop keeps its customer; the network forms from the bottom up.

---

## Repository layout

```
foreman/
├── CLAUDE.md                    # working agreement (read before changing things)
├── upstream-version.lock        # nanobot revision Foreman is built on
├── README.md                    # this file
├── nanobot/                     # upstream agent runtime (pinned)
├── foreman/                     # Foreman-specific code (memory, tools, security, installer, CLI, queue, hooks, tests)
├── skills/foreman-quote-rfq/    # orchestration recipe
├── nanobot/skills/shop-*/       # 7 sub-skill guides
├── nanobot/skills/foreman-quote-rfq/  # mirror for the loader
├── policies/                    # 3 deployment policies
├── installer/                   # platform templates + defaults
├── webui/                       # rebranded WebUI (text only; image assets are placeholders)
└── tests/                       # nanobot's upstream tests
```

For the full working agreement (skill convention, naming, non-negotiables, upstream merge protocol, security review ownership, etc.), read [CLAUDE.md](./CLAUDE.md).

---

## Roadmap

In order of effort and proximity, mirroring the vision document:

1. **Deepen the agent's knowledge of the shop.** Company email integration. ERP adapters (ProShop and JobBOSS first). CAD repository indexing. Customer history ingestion. Equipment registry. Voice channel via Twilio. Owner authentication. The agent should know the shop the way a 20-year veteran employee does.
2. **Expand the skill library.** Scheduling, procurement, capacity planning, customer follow-up, pricing strategy, succession planning, financial reporting. Each new skill compounds value.
3. **Per-shop ontology.** Each shop's job graph, customer graph, and capability graph become queryable assets the agent reasons over.
4. **Network capabilities.** Once Foremans are deployed broadly, inter-agent quoting, opt-in capacity routing, and policy-gated exposure to buyer-side agents. The federated graph becomes legible at industrial-base scale.

---

## Acknowledgments

Foreman stands on:

- [**nanobot**](https://github.com/HKUDS/nanobot) (Xubin Ren and contributors) — the agent runtime, MCP client, channel layer, and Dream memory consolidation we did not have to build.
- The US shop owners who took early calls and corrected our assumptions.
- [**MIT AI Studio (MAS.664)**](https://www.media.mit.edu/) under Prof. Ramesh Raskar at the MIT Media Lab — for the framing, the discipline, and the deadline.

## Team

| Member | Affiliation | Contribution |
|---|---|---|
| **Aline Zimerman** | PhD Fellow, Boston Children's Hospital / Harvard Medical School | Research rigor and behavioral-data methodology. Translates clinically validated signal-extraction patterns into the shop-personality store design. |
| **Colin McGonigle** | Sloan Fellow MBA '26, MIT. Georgetown Economics. | 8.5 years as Director of Research at Mozaic LLC. Owns the institutional thesis, market sizing, ROI framework, and the agent-versus-marketplace argument. |
| **Omar Dominguez** | Sloan Fellow MBA '26, MIT. MIT Sandbox Founder. | Eleven years operating his family's CNC shop. Lead architect and engineer of the Foreman agent. Distribution and shop-owner relationships. |

## Contact

- Omar Dominguez · MIT · [github.com/odominguez7](https://github.com/odominguez7)
- Colin McGonigle · MIT · [github.com/ctmmit](https://github.com/ctmmit)
- Aline Zimerman · MIT

> *The architecture today preserves the right to every layer above it. The architecture today does not commit to any of them. That is the discipline.*
