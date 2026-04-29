# CLAUDE.md — Foreman

This file is the working agreement for any Claude (or human) opening this repo. Read it before making changes. It states what Foreman is, what we forked, what we keep from upstream, what we change, and the order of work.

---

## What Foreman is

Foreman is an agent that represents the owner of a small or mid-size machine shop. It knows what the shop manufactures, the equipment on the floor, the customer history, and the pricing logic. It has its own company email address and access to the shop's information systems. It acts on the owner's behalf within explicit policy bounds. It is the shop's digital deputy.

The first skill bundle is quoting: a customer RFQ arrives by email, the agent extracts the drawing, retrieves similar historical jobs, checks material inventory, checks the machine schedule, recalls prior owner pricing corrections for that customer, composes a draft quote, and learns from any owner correction so the next matching RFQ is priced correctly without being told to remember.

Foreman is **LLM-agnostic** and **deployment-agnostic**. The same code runs on a managed cloud, a shop's own cloud account, or an on-prem GPU box. The shop chooses. Sovereignty is a configuration, not a product tier.

Network capabilities — one Foreman talking to another, or to a buyer's procurement agent via MCP — are deliberately deferred until enough Foremans exist to make them useful. That is Phase Three. We do not build it now.

The team is Aline Zimerman, Colin McGonigle, Omar Dominguez. MAS.664 AI Studio, MIT Media Lab.

---

## What we forked

**Upstream: [HKUDS/nanobot](https://github.com/HKUDS/nanobot).** MIT-licensed Python 3.11+ agent runtime, "ultra-lightweight personal AI agent in the spirit of OpenClaw, Claude Code, and Codex." Pre-1.0, actively maintained, ~3k lines of core Python. Selected because it satisfies every Foreman hard requirement and several strong preferences out of the box.

**Pinned at `nanobot v0.1.5.post3`** (commit SHA recorded in `upstream-version.lock` at repo root). Merge upstream only when there's a concrete reason (security patch, capability we need). Do not chase head.

What we get for free from upstream:

- **LLM-agnostic.** Provider factory in `nanobot/providers/factory.py` covers OpenAI, Anthropic, Azure OpenAI, openai-compat (Ollama, vLLM, DeepSeek, Qwen, Moonshot, Mistral, Groq, Together, LM Studio, MiniMax, Llama), GitHub Copilot, OpenAI Codex. We do not build a model abstraction layer.
- **MCP client.** `nanobot/agent/tools/mcp.py` wraps external MCP servers as native tools. We adopt that layer as-is.
- **Email channel.** `nanobot/channels/email.py`, with IMAP/SMTP, attachment allowlisting, DKIM/SPF self-loop guard. We do not build email integration; we configure it.
- **Dream memory.** JSONL-based append-only history with cron-driven consolidation, plus durable `MEMORY.md` / `SOUL.md` / `USER.md` files versioned via GitStore. Free-form markdown today; we extend with structured slots additively.
- **Sandbox.** Bubblewrap (Linux kernel namespaces) workspace isolation, default-deny SSRF allowlist via `nanobot/security/network.py`. We tighten the policy defaults for shop context.
- **Deployment.** Docker + docker-compose. (See "Deployment targets" below for what Foreman adds; this is one of three CLAUDE.md claims that did NOT match upstream reality on first audit.)

What we explicitly do NOT get for free, despite earlier wording:

- **MCP server.** Nanobot is MCP **client only** today. Phase Three's "expose `shop-` skills as MCP tools other agents can call" requires building MCP server capability, not configuring it. Plan accordingly when Phase Three triggers.
- **Skill subprocess execution.** Nanobot's `SkillsLoader` (in `nanobot/agent/skills.py`) treats every `SKILL.md` as an LLM-facing instruction document. There is no `runner.py` or `.sh` execution by the loader. The seven `shop-*` capabilities are **registered Python tools**; the SKILL.md tells the LLM when and how to call them. See "Skills convention" below.
- **systemd / LaunchAgent / Windows service manifests.** Upstream ships Docker only. Foreman installer builds and ships these.

The cost of forking: nanobot is pre-1.0 and moves fast. Keep Foreman-specific changes as additive files outside `nanobot/` where possible. Conflict resolution policy in "Working agreements" below.

---

## What we keep, change, add, remove

### Keep (do not touch)

- The agent loop in `nanobot/core/` (or equivalent — verify the actual path on first clone).
- The provider abstraction layer.
- The MCP client and server code paths.
- The Dream memory consolidation pass.
- The workspace sandbox.
- The release/CI scaffolding.
- The Docker and systemd service definitions (we extend, we do not replace).

### Change (small, targeted edits)

- **Branding and persona.** Rebrand to Foreman in user-facing strings, system prompts, and the WebUI. The agent's default system prompt should establish the shop-owner deputy persona, not the generic personal assistant.
- **Default channels.** Disable Discord, Telegram, Feishu, QQ, WeChat, WeCom, DingTalk, Matrix, WhatsApp, Teams in the default config. Enable only Email, Slack, CLI, and Web. The shop owner does not use Feishu.
- **Default providers.** Surface a curated list in the install wizard: Anthropic and OpenAI for cloud, Ollama and vLLM for on-prem. Hide the long-tail providers behind an "advanced" toggle. Avoid choice paralysis.
- **Memory schema.** Extend Dream's consolidated memory with structured slots for shop ontology — see "Personality store schema" below.
- **Sandbox policy.** Lock down outbound network by default to an allowlist (LLM provider, MCP servers in config, email server). Drawings and customer data must not exfiltrate via a misbehaving skill.

### Add (new code)

- `skills/` directory at repo root, containing Foreman skill bundles in **Anthropic SKILL.md format** (frontmatter + markdown + optional runner scripts). See "Skills convention" below. The first bundle is `skills/quoting/` with the seven quoting skills.
- `adapters/erp/` for ERP integrations: ProShop, JobBOSS, E2, Global Shop. Each adapter exposes itself as a tool. Start with read-only adapters; write operations require human approval.
- `adapters/cad/` for SolidWorks, Onshape. Read-only at first.
- `adapters/drawing/` for the PDF-to-structured-schema extractor. This is the highest-risk skill technically (tolerance misreads kill shop trust). Build it as a tool that calls a vision-capable LLM with a tightly constrained JSON schema, with an explicit confidence score and a flag for human review.
- `personality/` — the schema, ingestion scripts, and admin tools for the shop's institutional knowledge. See below.
- `installer/` — the wizard that gets a shop from "we bought a GPU box" to "Foreman is reading our email" in under an hour.
- `policies/` — declarative network and filesystem policies, with a `default.yaml` and overrides per deployment target (managed cloud, single-tenant cloud, on-prem).
- `docs/` — Foreman-specific documentation. Keep upstream nanobot docs untouched; layer ours on top.

### Remove (delete or disable)

- `ClawHub` skill discovery UI in the default WebUI. We curate the skill set; the shop owner does not browse a marketplace. Reintroduce in Phase Two if we ship a Foreman-specific skill registry.
- Demo skills and example agents that are not relevant. Keep the test scaffolding; remove the example payloads.

---

## Skills convention

A Foreman skill is two things together:

1. A `SKILL.md` file in **Anthropic SKILL.md format** — markdown the LLM reads to know *when* to act and *which tool* to call.
2. A registered Python tool in `foreman/tools/` — the actual code the LLM invokes via nanobot's tool-call protocol.

Nanobot's `SkillsLoader` (in `nanobot/agent/skills.py`) does **not** subprocess scripts. The loader discovers `SKILL.md` files, summarizes them in the agent's system prompt, and lets the LLM `read_file` the full markdown on demand. Anthropic-format frontmatter (`name`, `description`, `version`, `triggers`) parses cleanly — extra fields are accepted but ignored. Use the format anyway: it's portable, it's the cross-framework standard, and it documents intent for humans even when nanobot ignores some fields.

A skill directory looks like:

```
skills/shop-extract-drawing/
  SKILL.md           # frontmatter + LLM-facing instructions
  schemas/
    output.json      # JSON schema for the tool's structured output
  examples/
    bosch-bracket.pdf
    boeing-bushing.pdf
  README.md          # human-facing notes (not loaded by agent)
```

The corresponding Python tool lives at `foreman/tools/shop_extract_drawing.py` and is registered with the agent in `foreman/tools/__init__.py`. SKILL.md documents the tool's call signature so the LLM knows what arguments to pass.

**Naming.** All Foreman skills are prefixed `shop-` (e.g., `shop-extract-drawing`, `shop-recall-personality`) for the granular sub-skills. The orchestrating meta-skill the LLM follows for end-to-end quoting uses the `foreman-` prefix (`foreman-quote-rfq`) — this is also the name external callers will see when Phase Three exposes skills via MCP server.

**Skill independence.** Each Python tool is independently testable. A tool that depends on another tool's output goes through the agent loop (the LLM calls A, then calls B with A's output), not via direct Python import. This keeps the tool graph composable and the test surface small.

**What's a skill, what's a tool, what's neither.** A capability the LLM should choose to invoke based on context = registered tool + SKILL.md. A helper function that's always called as part of another tool = plain Python utility, no SKILL.md, no registration. When in doubt: if the agent needs to *decide* whether to call it, it's a skill; if it's an implementation detail of an existing skill, it's a function.

**The first seven skills (Foreman Quoting bundle):**

1. `shop-extract-drawing` — PDF to structured schema (material, tolerances, features, finish, threads). Handles aged scans and Spanish drawings. Highest technical risk; build first, test most.
2. `shop-retrieve-similar-jobs` — Top-3 historical jobs for material plus customer, including at least one loss for benchmark pricing.
3. `shop-check-material` — Raw material inventory and supplier lead time. Calls the ERP adapter.
4. `shop-check-schedule` — Machine slack and earliest available production slot. Calls the ERP adapter.
5. `shop-recall-personality` — Customer-gated retrieval of prior owner feedback. Called before every compose.
6. `shop-compose-quote` — Final draft quote under one of three steering profiles (conservative, balanced, aggressive). Personality deltas applied on top of base.
7. `shop-remember-feedback` — Persists owner corrections to the shop's personality store. Called automatically on every correction.

The hero behavior is the learning loop. The owner gives a verbal correction in plain English; `shop-remember-feedback` persists it; on the next matching RFQ, `shop-recall-personality` retrieves it; `shop-compose-quote` applies the delta and cites the recalled correction in the reasoning field. Without being told to remember. This must work end-to-end before anything else ships.

---

## Personality store schema

The shop personality store sits on top of nanobot's Dream memory layer. Dream gives us tiered storage, consolidation, and git-versioning for free. We add structured slots specific to a machine shop.

**Slots (canonical):**

- `shop_profile` — what the shop manufactures, certifications, capabilities, geographic position. Set once; updated rarely.
- `equipment` — list of machines with capability envelopes (max workpiece size, axes, tolerance class, available tooling). Owner-editable.
- `customers[customer_id]` — per-customer record: payment terms, payment behavior history, quality expectations, past dispositions ("Boeing pays slow, add 8 percent"), commercial relationship.
- `materials[material_code]` — preferred suppliers, typical lead times, scrap factors, margin defaults.
- `routing_memory[(process, material)]` — outside processors trusted for this combination, prior turnaround, prior quality outcomes.
- `pricing_corrections[(customer_id, context)]` — owner overrides on prior quotes, with the reason if given. This is what `shop-recall-personality` queries.
- `audit_log` — append-only record of every personality write, who triggered it, what was changed.

Every write to the personality store goes through the audit log. The shop owner can review and reverse any entry. This is non-negotiable; the agent's authority comes from being correctable.

---

## Deployment targets

Foreman supports three commercial deployment models. The same code runs on all three; the policy file in `policies/` and the wrapping infrastructure differ.

**Managed Foreman cloud.** Multi-tenant orchestration, single-tenant database and workspace per shop. Used by shops that want zero ops. Default for the wedge market.

**Single-tenant cloud.** The shop's own AWS, GCP, or Azure account. We provide a Terraform module. Used by shops with mid-tier compliance requirements or strong preference for owning their cloud bill.

**On-prem.** A GPU box in the shop's server room. Used by shops with defense work, ITAR exposure, or controlled-data programs.

### Platform packaging (what the installer ships)

Upstream nanobot ships **Docker only**. Foreman installer builds and ships four platform packagings, all from one declarative source:

- **Docker / docker-compose** — extends upstream `Dockerfile` and `docker-compose.yml`. Adds Foreman volumes for `personality/` and `policies/`. Default for managed and single-tenant cloud deployments.
- **systemd service unit** — Linux native. `installer/systemd/foreman.service`, `Restart=on-failure`, `User=foreman`, journald logging. Generated by the wizard from the user's chosen install path.
- **macOS LaunchAgent** — `installer/launchd/com.foreman.agent.plist`, `KeepAlive=true`, logs under `~/Library/Logs/Foreman/`.
- **Windows service** — wrapped via [NSSM](https://nssm.cc/), generated from a template by the wizard. Logs to Windows Event Log + a local rotating file.

The installer detects the target, prompts the owner for the policy bundle (`managed-cloud.yaml` / `single-tenant-cloud.yaml` / `on-prem.yaml`), and writes a per-deployment `.env` file outside the codebase. No code branches; differences live in config and the chosen wrapper.

---

## Phase plan

### Phase One: a working Foreman for one shop

Goal: Omar's family CNC shop runs Foreman in production for the quoting workflow. This is the demo state for the MAS.664 final.

- Fork nanobot. Get it running locally with the email channel and one Anthropic provider.
- Implement the seven Quoting skills against real Bosch and Boeing drawings.
- Build the ProShop adapter (or whichever ERP Omar's shop runs) read-only.
- Wire the Dream memory layer with the shop personality schema.
- Run the learning loop end-to-end. Owner correction → persisted → recalled on next matching RFQ → cited in the quote.
- Ship a docker-compose deployment that a non-technical shop can install in under an hour with a wizard.

### Phase Two: skill library expansion

Goal: Foreman is useful for more than quoting.

- Scheduling skills (capacity planning, due-date promises, machine slack analysis).
- Procurement skills (raw-material reorder thresholds, supplier RFQs, lead-time forecasting).
- Customer follow-up skills (overdue payment chasing, post-delivery quality check-ins).
- Pricing strategy skills (margin analysis, win/loss patterns, customer profitability).
- Each new skill compounds the agent's value to the owner. The agent gets more useful every quarter without becoming more complex, because the runtime stays unchanged.

### Phase Three: network capabilities at scale

Goal: Foremans interact outside the walls of the shop.

- Build MCP server capability into Foreman (nanobot upstream is MCP client only today; this is net-new code, not a configuration flip). Expose the `foreman-*` and `shop-*` skills as MCP tools other agents can call with policy-gated permission.
- A buyer's procurement agent calls `foreman-quote-rfq(drawing, qty, due_date)` directly. A partner shop's Foreman brokers an outside-process job. Excess capacity routes opt-in across a regional cluster.
- This phase begins only when there are ≥10 Foreman deployments in one regional corridor — enough density that brokered work and benchmarking have a population to draw from. Until then, MCP server exposure is a feature flag, off by default, and the code path is not built.
- Phase Three preserves the shop's customer ownership: every inbound external call surfaces in the owner inbox; no automated cross-shop disclosure of customer identity, drawings, or pricing without per-call owner approval.

---

## Non-negotiables

Four rules that every skill, adapter, and policy file must honor. These exist because the agent's authority comes from being correctable and bounded; without them, the first wrong quote ends the pilot.

1. **Human approval gate on every outbound message.** In Phase One, no skill sends a quote, an email, a Slack message, or any external communication without explicit owner click-through. The agent composes drafts; the owner sends them. The flag `outbound_send: require_human_approval: true` is set in every `policies/*.yaml`. Removing or overriding this requires a written exception signed off by Omar and Colin.

2. **Audit log on every personality write.** Every write to the personality store goes through `audit_log` with caller identity, timestamp, the slot written, and the delta applied. The owner can list, inspect, and reverse any entry via CLI. The audit log is append-only; reversals are new entries that null the prior delta, not edits.

3. **Drawings never leave the deployment boundary.** Outbound traffic from any skill is restricted to the LLM provider, the email server, and MCP servers explicitly enumerated in the active policy file. A startup check fails loud if any registered tool has outbound capability not in the allowlist. No silent upload of customer drawings to anything else, ever.

4. **Escalate on ambiguous customer-id.** When `shop-recall-personality`'s lookup confidence is below 0.9 (same buyer from two domains, RFQ forwarded by an assistant, broker-relayed RFQ, new contact at known customer), the agent surfaces candidate matches to the owner and waits. It does not guess. Wrong customer → wrong recalled feedback → wrong margin applied. This is the worst quoting failure mode and it is fully preventable.

---

## Working agreements

**Branching.** `main` tracks the latest stable Foreman release. `upstream` tracks `nanobot/main`. Feature work happens on short-lived branches off `main`.

**Upstream merges.** Pull from upstream only when there's a concrete reason (security patch, capability we need). Do not chase head. The version Foreman is pinned to is recorded in `upstream-version.lock` at repo root; bump the lock only after the merge passes the verification suite. Resolve conflicts in favor of upstream for runtime files (`nanobot/agent/`, `nanobot/providers/`, `nanobot/channels/`); in favor of Foreman for `skills/`, `adapters/`, `personality/`, `policies/`, `installer/`, `foreman/`, and `docs/foreman/`.

**Security review ownership.** Any change to `policies/*.yaml`, any new adapter that makes outbound calls, and any change that loosens the SSRF allowlist is reviewed by Colin before merge. Network attack surface is a non-negotiable concern for shops with regulated work.

**Tests.** Every skill has at least one integration test that runs the full agent loop. Every adapter has unit tests against a recorded fixture and an integration test against a sandboxed instance of the target system. Drawing extraction has a regression test set with 20+ real drawings, scored on tolerance precision and recall.

**Reviews.** Any change that touches the runtime is reviewed by Omar before merge. Any change that touches the personality schema is reviewed by Aline. Anything else can ship after one approving review.

**Commits.** Conventional commits format (`feat:`, `fix:`, `chore:`, `docs:`). Reference the skill or adapter affected in the scope (e.g., `feat(extract-drawing): handle Spanish dimension callouts`).

**Secrets.** No keys in the repo. The installer prompts for them; they live in a per-deployment env file outside the codebase.

---

## Open questions

These are decisions that affect the fork and have not yet been made. Resolve before they block work.

1. ~~**Skill format compatibility with nanobot's existing skill primitive.**~~ **RESOLVED 2026-04-29.** Anthropic SKILL.md frontmatter parses cleanly through nanobot's `SkillsLoader` (extra fields like `version`/`triggers` are ignored, not rejected). The skill model is markdown-only — nanobot does not subprocess runners. The seven `shop-*` capabilities are registered Python tools in `foreman/tools/`, not bash scripts. See "Skills convention" above.
2. **Drawing extraction LLM.** Anthropic Claude Sonnet, OpenAI GPT-4o, or a fine-tuned open model? Drives accuracy on aged scans and Spanish drawings, which is the technical risk that can kill the wedge. **Owner: Omar. Due: before the seven Quoting skills are wired.**
3. **ERP API stability.** ProShop and JobBOSS APIs are not uniformly stable across versions. Pick one customer shop and one ERP version as the reference; design for that, then port. **Owner: Omar. Due: before the ERP adapter starts.**
4. **Personality store backup/export.** A shop owner must be able to export the personality store as a portable artifact (the agent's accumulated knowledge is the shop's IP). Format and tooling not yet specified. **Owner: Colin. Due: end of Phase One.**
5. **Pricing of managed vs. on-prem deployments.** Affects positioning, not code. But the installer wizard needs to know the model. **Owner: Colin. Due: before any external customer pilot.**

---

## Sources of truth

- **Vision document:** `Foreman_Vision_v3.docx` in the project folder. The thesis, market sizing, agentic-web framing.
- **Deep research:** `foreman-deep-research.md` in the project folder. Market structure, software adoption patterns, hard objections.
- **Public site:** [foremanjobs.lovable.app](https://foremanjobs.lovable.app/)
- **Public repo:** [github.com/ctmmit/foreman](https://github.com/ctmmit/foreman) (current; supersedes [odominguez7/foreman](https://github.com/odominguez7/foreman) which holds the NemoClaw prototype)
- **Upstream:** [github.com/HKUDS/nanobot](https://github.com/HKUDS/nanobot)
- **Skill format:** [Anthropic SKILL.md spec](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview). Pin the version of the spec we follow in `docs/foreman/skill-format-version.md` whenever we adopt a new revision; the Anthropic spec evolves and we do not want silent drift.
- **Upstream pin:** `upstream-version.lock` at repo root holds the SHA of the nanobot commit Foreman is built on. Source of truth for "what version of the runtime are we on."
