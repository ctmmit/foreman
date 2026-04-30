# Foreman

> An agent for the shop owner. The shop's deputy. Skills compose. The network emerges.

Foreman is a long-running agent that represents the owner of a small or mid-size North American machine shop. It has its own company email address, access to the shop's drives and ERP, and the authority to act on the owner's behalf within explicit policy bounds. It learns continuously: every owner correction ("Boeing pays slow, add 8 percent") is captured and recalled the next time the same situation arises. It is the shop's digital deputy.

Each shop gets an agent. The agent gets skills. The network is what emerges.

**License:** MIT

---

## Why this exists

North America runs more than 20,000 small and mid-size machine shops. They are the operational backbone of domestic manufacturing, deeply trusted by their customers, and almost entirely undigitized. The conventional play is a centralized SaaS marketplace. It fails because the shop's moat is the customer relationship and the routing memory, not raw capacity.

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

Foreman is built on a skill model. Capability ships as **skills** — small, independently testable units (a `SKILL.md` plus a registered Python tool). New capabilities ship as new skills, not as new code paths in a monolith. Skills can be authored by Foreman, by third parties, or by the shops themselves.

**Today: the Quoting bundle (seven skills).** The first generation addresses responding to a customer RFQ — the most painful and most universal SMB-manufacturing workflow.

| Skill | What it does |
|---|---|
| [`shop-extract-drawing`](./skills/shop-extract-drawing/SKILL.md) | Drawing PDF → structured schema (material, tolerances, features, finish, threads). Vision-LLM call with a confidence floor of 0.95 on tolerance fields. |
| [`shop-retrieve-similar-jobs`](./skills/shop-retrieve-similar-jobs/SKILL.md) | Top-3 historical jobs for material + customer, including at least one loss for benchmark pricing. |
| [`shop-check-material`](./skills/shop-check-material/SKILL.md) | Raw-material inventory and supplier lead time. |
| [`shop-check-schedule`](./skills/shop-check-schedule/SKILL.md) | Machine slack and earliest available production slot. |
| [`shop-recall-personality`](./skills/shop-recall-personality/SKILL.md) | Customer-gated retrieval of prior owner feedback. Called before every compose. |
| [`shop-compose-quote`](./skills/shop-compose-quote/SKILL.md) | Final draft quote under one of three steering profiles (conservative / balanced / aggressive). Personality deltas applied on top. Deterministic math, auditable. |
| [`shop-remember-feedback`](./skills/shop-remember-feedback/SKILL.md) | Persists owner corrections to the personality store. Called automatically on every correction. |

The orchestration recipe the agent follows for end-to-end quoting is [`foreman-quote-rfq`](./skills/foreman-quote-rfq/SKILL.md).

**Next: every white-collar workflow inside the shop.** Scheduling, procurement, capacity planning, customer follow-up, pricing strategy, succession planning, financial reporting. Each new skill compounds the agent's value to the owner without making the runtime more complex.

**Eventually: outside the walls of the shop.** Once Foremans are deployed at scale, the network is what emerges from per-shop agency — not a marketplace, not a central protocol operator, but an ecosystem with four properties no centralized system can have: visibility into the federated industrial graph, efficiency from peer-to-peer coordination, automation that leaves humans on commitments and agents on coordination, and the compounding progress those three create. Federation is deferred until enough Foremans exist to make it useful; the architecture today preserves that arc without committing to it. See [The emergent ecosystem](#the-emergent-ecosystem) below.

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

## Capabilities by layer

### Communication
- **Email** (inbound RFQs + outbound draft quotes). IMAP polling, SMTP send, attachment allowlist restricted to drawing formats (`.pdf .dwg .dxf .step .stp .iges .igs`), DKIM/SPF self-loop guard.
- **Slack** for team coordination on quote review.
- **CLI** for direct owner interaction.
- **WebUI** via WebSocket for the owner's browser session.
- Other channels (Discord, Telegram, Matrix, WhatsApp, etc.) remain in the codebase but are off by default. Attack-surface reduction.

### Memory and learning
- **Personality store** — seven structured slots: `shop_profile`, `equipment[]`, `customers[customer_id]`, `materials[material_code]`, `routing_memory[(process, material)]`, `pricing_corrections[(customer_id, context)]`, `audit_log` (append-only).
- **Customer-id resolver** with confidence-gated escalation. Wrong customer → wrong recalled feedback → wrong margin applied. Below 0.9 confidence the agent escalates to the owner instead of guessing. Property-tested.
- **Audit log on every personality write** — the agent's authority comes from being correctable. Every write records caller / timestamp / slot / delta. Reversible.
- **Two-tier memory model** — free-form long-term markdown plus structured slots; consolidated by a background pass.

### Safety and policy
- **Three deployment policies** in [`policies/`](./policies): `managed-cloud.yaml`, `single-tenant-cloud.yaml`, `on-prem.yaml`.
- **Egress allowlist** — outbound HTTP only to the configured LLM provider, the email server, and explicitly enumerated MCP servers. Anything else denied.
- **Outbound-send approval gate** enforced via `ForemanMessageTool`. Blocked sends land in `workspace/personality/outbound_queue.jsonl` for owner review through `foreman queue list / approve / reject`.
- **Drawings never leave the deployment.** The on-prem policy ships with `llm_provider_hosts: []` — assumes local Ollama / vLLM, no cloud reach.

### LLM providers
Curated in the install wizard: **Anthropic** (default cloud), **OpenAI** (alternate cloud), **Ollama** (on-prem local), **vLLM** (on-prem high-throughput). The full provider registry (Azure OpenAI, OpenRouter, HuggingFace, etc.) remains accessible behind an "advanced" toggle.

### Deployment
Four platform packagings, all from a unified setup wizard:
- **Docker / docker-compose** — default for managed and single-tenant cloud.
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
uv run python -m pytest foreman/tests       # full test suite
uv run foreman --version                    # 🔧 Foreman v0.1.0
```

### Shop deployment (bring Foreman online)

```bash
# 1. Configure the runtime (six prompts)
foreman install
#  - Deployment target?       docker / systemd / launchd / windows
#  - Network policy?          managed-cloud / single-tenant-cloud / on-prem
#  - Install + workspace + .env paths
#  - LLM provider + key?      anthropic / openai / ollama / vllm
#  - Email IMAP/SMTP creds + allowed-from list
#  - Owner email for approval-required notifications

# 2. Onboard the shop's knowledge (interview or YAML)
foreman onboard-shop
#  - shop profile, equipment, customers, materials, routing memory, pricing rules

# 3. Run the platform-native install command (the wizard prints exact next steps)
sudo cp foreman-install/foreman.service /etc/systemd/system/
sudo systemctl enable --now foreman
journalctl -u foreman -f
```

The install wizard generates the deployment file(s), writes `~/.foreman/config.json` (no inlined secrets — provider keys surface as `${ANTHROPIC_API_KEY}` interpolation), and writes a per-deployment `.env` chmod'd to `0600` on POSIX.

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
- **Not autonomous.** The agent composes drafts. The owner clicks send.

---

## The emergent ecosystem

The web is being rebuilt as a network of agents that act on behalf of users, coordinate through shared protocols, and accumulate trust over time. Foreman applies that thesis to a vertical that needs it most. The interesting claim is not "Foremans will do these specific things for each other." It is that the same per-shop primitive — agent + skills + per-shop policy — composes at scale into an ecosystem with four properties no centralized system can have.

**Visibility — the federated graph becomes legible.** Today, North American manufacturing is operationally invisible. Nobody — not the shops themselves, not OEMs, not policy makers — has a real-time view of which shops can do what, at what price, with what capacity. With Foremans interacting under per-shop policy, the regional industrial graph emerges bottom-up: who can do AS9100D titanium work in the Pittsburgh corridor, where 5-axis capacity is tight this week, which shops are the local experts on what. No central operator owns the graph; it lives at the edges, queryable from any node. The eventual buyers of that legibility are not the shops — they have it locally — but OEMs concerned with industrial-base resilience, sovereign-wealth allocators, and government.

**Efficiency — coordination cost collapses.** The routing graph already exists, but it lives in owners' heads and runs on phone calls. Every outside-process handoff, every spec question, every overflow match is bottlenecked by the friction of finding the right peer for the right thing at the right time. When Foremans interact, that friction approaches zero. Spare capacity becomes addressable. Knowledge unlocks. Customer relationships survive moments that would otherwise break them.

**Automation — humans on commitments, agents on coordination.** The disciplined split. Centralized marketplaces automate commitments; the shop becomes a fungible execution layer. Foreman does the opposite. Agents handle discovery, query, signal, draft, and routing. Owners stay in their authority over every outbound commitment via the same approval gate that wraps internal use. The owner becomes more powerful, not less. This is what makes the system trustworthy at scale.

**Progress — the compounding loop.** Better win rates, less time lost to coordination, customer relationships preserved through cluster slack, tribal knowledge made queryable so apprentices learn faster. Shops survive the owner-succession cliff. Regional clusters coordinate as clusters. Eventually, the federated industrial graph becomes legible at industrial-base scale, and the conversation about manufacturing resilience stops requiring a McKinsey study.

The architecture rests on three principles the vision treats as foundational: **per-user agency** (every shop has its own agent — the prerequisite for any network), **skills compose** (capability is the moat; the runtime stays simple), and **trust without centralization** (each shop owns its data; no marketplace operator sits in the middle). The conventional play (Xometry, Fictiv, Hubs) forecloses the emergent arc by capturing the customer relationship on day one. The agentic-web play does not require that capture. Each shop keeps its customer; the network forms from the bottom up.

The architecture today preserves the right to every layer above. It does not commit to any of them. **That is the discipline.**

---

## Repository layout

```
foreman/
├── CLAUDE.md                    # working agreement (read before changing things)
├── upstream-version.lock        # pinned version of the underlying agent runtime
├── README.md                    # this file
├── foreman/                     # Foreman-specific code (memory, tools, security, installer, CLI, queue, hooks, tests)
├── skills/                      # SKILL.md guides (orchestration recipes + per-skill instructions)
├── policies/                    # 3 deployment policies (managed-cloud / single-tenant / on-prem)
├── installer/                   # platform templates (Docker / systemd / launchd / Windows NSSM)
└── webui/                       # the owner-facing browser interface
```

For the full working agreement (skill convention, naming, non-negotiables, upstream merge protocol, security review ownership, etc.), read [CLAUDE.md](./CLAUDE.md).

---

## Roadmap

In order of effort and proximity:

1. **Deepen the agent's knowledge of the shop.** Company email integration. ERP adapters (ProShop and JobBOSS first). CAD repository indexing. Customer history ingestion. Equipment registry. Voice channel via Twilio. Owner authentication. The agent should know the shop the way a 20-year veteran employee does.
2. **Expand the skill library.** Scheduling, procurement, capacity planning, customer follow-up, pricing strategy, succession planning, financial reporting. Each new skill compounds value.
3. **Per-shop ontology.** Each shop's job graph, customer graph, and capability graph become queryable assets the agent reasons over.
4. **Network capabilities.** Once Foremans are deployed broadly, inter-agent quoting, opt-in capacity routing, and policy-gated exposure to buyer-side agents. The federated graph becomes legible at industrial-base scale.

---

## Team

| | |
|---|---|
| **Aline Zimerman** | Co-founder. Behavioral data, personality store design. PhD Fellow, Boston Children's Hospital / Harvard Medical School. |
| **Colin McGonigle** | Co-founder. Strategy and architecture. MIT Sloan Fellow MBA. Eight years as Director of Research at Mozaic LLC. |
| **Omar Dominguez** | Co-founder, lead engineer. Eleven years operating his family's CNC shop. MIT Sloan Fellow MBA. |

## Contact

- Omar Dominguez — [github.com/odominguez7](https://github.com/odominguez7)
- Colin McGonigle — [github.com/ctmmit](https://github.com/ctmmit)
- Aline Zimerman

---

## Acknowledgments

Foreman's agent runtime is built on top of [`HKUDS/nanobot`](https://github.com/HKUDS/nanobot), an MIT-licensed open agent framework, used in accordance with its license.

> *The architecture today preserves the right to every layer above it. The architecture today does not commit to any of them. That is the discipline.*
