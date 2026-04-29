# Foreman

> A quoting deputy for the owner of a small US machine shop. Reads the drawing, checks the schedule, retrieves similar past jobs, recalls the owner's prior corrections for each customer, and produces a draft quote the owner reviews and sends. Never sends anything outbound without the owner's approval.

**Status: work in progress.** MIT AI Studio (MAS.664) final project, team [Aline Zimerman](#), [Colin McGonigle](#), [Omar Dominguez](#).

**License:** MIT (this repo) + MIT (upstream [HKUDS/nanobot](https://github.com/HKUDS/nanobot))

---

## What it does

A US machine shop with $5M-$30M revenue handles 80-120 RFQs a week. Each one takes the owner 30-90 minutes. Owners lose 30-50% of bids because they cannot respond fast enough. Foreman reads a customer drawing, checks the shop's inventory and schedule, retrieves similar past jobs, applies any prior owner feedback for that customer, and produces a draft quote in under three minutes.

The hero behavior is the learning loop. The owner gives a verbal correction in plain English ("too low — Boeing pays slow, add 8%"); Foreman persists it as customer-specific personality. On the next matching RFQ, Foreman applies the +8% and cites the original correction in the reasoning field. Without being told to remember.

The whole stack runs on a computer in the shop. Drawings never leave the building.

## How to read this repo

- **[CLAUDE.md](./CLAUDE.md)** — the working agreement. What Foreman is, what we forked, what we keep from upstream, what we change, the Non-negotiables, and the phase plan. Read this before making changes.
- **[upstream-version.lock](./upstream-version.lock)** — the nanobot revision Foreman is built on. Pinned at `v0.1.5.post3` (commit `0b1631f`).
- **`skills/`** — Foreman-specific skill bundles in Anthropic SKILL.md format. The orchestrating meta-skill is `foreman-quote-rfq`; the seven granular building blocks are `shop-*`.
- **`nanobot/`** — upstream package directory. Internal name is preserved to keep upstream merges clean; user-facing surfaces (CLI, persona, branding) are rebranded to Foreman.

## Status — what's working today

This is the active branding/wiring phase. Right now:

- ✅ Forked from `HKUDS/nanobot` at `v0.1.5.post3`, pinned in `upstream-version.lock`
- ✅ Rebranded user-facing surfaces (CLI name `foreman`, version banner, logo, package metadata)
- ✅ Shop-deputy persona in `nanobot/templates/SOUL.md` (replaces upstream's generic personal-assistant persona)
- ✅ `foreman-quote-rfq` orchestration SKILL.md drafted
- 🚧 WebUI rebrand pass
- 🚧 Default channel curation (email + slack + CLI + websocket on; rest off)
- 🚧 Memory extension (`ForemanMemoryStore` with structured slots)
- 🚧 Seven `shop-*` Python tools
- 🚧 Multi-platform installer (Docker + systemd + LaunchAgent + Windows service)

See [CLAUDE.md → Phase plan](./CLAUDE.md#phase-plan) for the full sequence.

## Quickstart (developer mode)

> **This is fork-stage software. There is no end-user installer yet.** The path below gets the runtime up so a developer can poke at it.

```bash
git clone https://github.com/ctmmit/foreman
cd foreman
uv sync
uv run foreman --version
```

Expected output: `🔧 Foreman v0.1.0` (or current pin).

For a real shop deployment, wait for the multi-platform installer (Phase 5 of the bootstrap plan).

## Acknowledgments

Foreman stands on:

- [**nanobot**](https://github.com/HKUDS/nanobot) (Xubin Ren and contributors) — the agent runtime, MCP client, channel layer, and Dream memory consolidation we did not have to build.
- The five US shop owners who took early calls and corrected our assumptions.

## Contact

- Omar Dominguez · MIT · [github.com/odominguez7](https://github.com/odominguez7)
- Colin McGonigle · MIT · [github.com/ctmmit](https://github.com/ctmmit)
- Aline Zimerman · MIT
