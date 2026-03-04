# Odigos — Product Requirements Document

**Version:** 1.0
**Date:** March 4, 2026
**Owner:** Jacob
**Status:** Draft

---

## What Is Odigos?

Odigos is a self-hosted personal AI agent that runs on a VPS and acts as a virtual assistant. Unlike chatbots, it remembers who you are, takes actions on your behalf, monitors things you care about, and gets better over time. You talk to it through Telegram. It has access to its own Google account (email, drive, calendar) and eventually delegate access to yours.

The name comes from the Greek word for "guide."

---

## Who Is It For?

**Primary user:** Jacob (the owner). This is a single-user system. There is one owner and one agent.

**Secondary audience:** If the project is open-sourced, technically capable individuals who want to self-host a personal AI assistant and are comfortable running a VPS, managing API keys, and editing YAML config files. Not a consumer product — a power-user tool.

---

## Why Build This?

Existing personal AI tools fall into two camps: chat interfaces that forget you the moment the session ends, and over-engineered agent frameworks that are fragile, expensive, and require a PhD to configure. Neither feels like having an assistant.

Odigos exists because a good VA should know that you hate morning meetings, remember that Alex is your business partner (not your dentist), proactively tell you when something important arrives in email, and improve at its job every week — without you having to re-explain everything every time.

---

## Core Principles

These govern every design and scope decision:

1. **Memory is the product.** An assistant that forgets is just a chatbot. Every interaction should make the next one better.
2. **Actions over words.** The agent should do things, not describe how to do things.
3. **Resilience over perfection.** It's better to degrade gracefully than to crash spectacularly. Self-healing beats self-optimizing.
4. **Lean core, rich periphery.** The core agent loop should stay under 2,000 lines. Complexity belongs in modular tools and monitors, not in the brain.
5. **Your data, your server.** Nothing phones home. No vendor lock-in on critical infrastructure.
6. **Don't over-engineer.** If a simpler approach works, use it. We can always add complexity later; we can never easily remove it.

---

## What Success Looks Like

### Phase 0 — Skeleton
**"It talks back."**
You send a message on Telegram. The agent responds via OpenRouter. There's a SQLite database persisting conversations. You can see it running on the VPS. That's it — nothing fancy, but the plumbing works.

**Acceptance criteria:**
- Telegram bot receives and responds to text messages
- Responses come from an LLM via OpenRouter (model selectable via config)
- Conversations are stored in SQLite
- The agent runs as a systemd service and auto-restarts on crash
- Config is driven by `.env` + `config.yaml`, no hardcoded values

### Phase 1 — Memory & Personality
**"It remembers me."**
You tell the agent something on Monday and it remembers on Friday. It knows your name, your preferences, your projects. It has a consistent voice — not generic ChatGPT tone, but something that feels like *your* assistant.

**Acceptance criteria:**
- Agent recalls facts from previous conversations without being reminded
- Entity extraction: explicit mentions of people, projects, and preferences create entities in the graph. Casual mentions are stored with lower confidence and promoted if referenced again.
- Vector search: "what did we discuss about X?" returns top 3-5 results ranked by semantic similarity. User can ask for more.
- Personality is driven by `personality.yaml` and visibly changes agent behavior when settings are modified (e.g., switching from "concise" to "verbose" produces noticeably different response lengths)
- Corrections are remembered across sessions and applied in similar contexts. The agent may ask "Last time you corrected me on X — should I apply that here?" when relevant.

### Phase 2 — Tools
**"It does things."**
You ask the agent to search the web, read a PDF, or schedule a reminder — and it actually does it. Tool use feels natural, not like issuing commands to a terminal.

**Acceptance criteria:**
- Agent uses tools autonomously based on your request (you say "find me...", it searches)
- Web search returns useful results
- Document processing handles PDF, DOCX, images (via Docling)
- Code execution works in a sandbox (5s CPU time limit, 512MB memory, no network access by default; agent can request network for specific tasks with approval)
- Task scheduling works: "remind me to X in 2 hours" → you get reminded

### Phase 3 — Self-Improvement & Proactive
**"It's getting better and it doesn't just wait for me."**
The agent recovers from failures without you noticing. It tracks what you correct and avoids repeating mistakes. It monitors costs and stays within budget. It starts to do things on its own — a health check here, a pattern observation there.

**Acceptance criteria:**
- Tool failures are retried with backoff; a tool is auto-disabled after 3 consecutive failures or >50% failure rate over 24 hours. User is notified via Telegram and can manually re-enable.
- Correction log → rule extraction pipeline works (correction turns into behavioral rule)
- Cost tracking is accurate per-message and per-task; budget alert sent via Telegram at 80% of any budget period; hard cap stops LLM calls immediately (agent enters low-cost mode, can still respond with cached/simple answers)
- `/status`, `/explain`, `/audit` commands work in Telegram
- Self-tool-building: agent can propose, draft, test, and register a new tool (with your approval)
- At least one proactive monitor runs (system health). Proactive behavior defaults to conservative: only interrupt for system health issues and explicitly configured triggers. All other proactive observations are batched for the daily digest.

### Phase 4 — Google Integration + Proactive Monitors
**"It's handling my email."**
The agent watches the dedicated Google account. It triages email, surfaces important messages on Telegram, drafts replies, and manages the calendar. Proactive monitors for email, calendar, and behavioral patterns are active.

**Acceptance criteria:**
- OAuth2 flow works for the dedicated Google account
- Agent reads, searches, and sends email
- Agent reads and creates Google Calendar events
- Agent reads Google Drive files
- Email triage: incoming mail is classified by priority (high/medium/low) using sender importance + content analysis. High-priority messages surface immediately on Telegram. Classification improves with corrections — target >85% accuracy within 2 weeks of use.
- Morning brief delivered at the configured time. Contents: today's calendar, flagged overnight emails, overdue/upcoming tasks, and any batched proactive observations. Format is concise — fits in a single Telegram message.
- Proactive monitors active: email (new high-priority mail), calendar (upcoming events with context), patterns (learned behavioral triggers). Agent respects DND schedule and batches non-urgent notifications.
- Permission tiers enforced per `permissions.yaml`: full access on agent's own Google account; read + draft-only on delegated primary account (see ARCHITECTURE §4.13 for detailed model)

### Phase 5 — Voice & Polish
**"It sounds like my assistant."**
Voice messages work on Telegram — you send a voice note, the agent transcribes it, processes it, and optionally responds with audio. The system is polished: comprehensive error handling, backup system, optional web dashboard.

**Acceptance criteria:**
- Voice messages transcribed via Moonshine STT (>90% accuracy on clear audio, <2s processing time)
- Text-to-speech responses via KittenTTS (optional per config, <3s generation for typical responses)
- Backup script runs on schedule and produces encrypted archives
- All critical paths have error handling and don't crash the agent

---

## Explicitly Out of Scope (For Now)

These are things we've deliberately decided not to build yet. They may become future phases, but they are not part of the v1 plan:

- **Multi-user support.** One owner, one agent. No auth system, no user management.
- **Web UI / dashboard.** Telegram is the primary (and for now, only) interface. A web dashboard is a Phase 5 nice-to-have, not a requirement.
- **Outbound voice calls.** TTS on Telegram is in scope; making phone calls via Twilio is not.
- **Smart home integration.** Interesting but orthogonal to the core VA experience.
- **Fine-tuning a local LLM.** We use API models via OpenRouter. Local model fine-tuning on conversation history is a future research direction.
- **Mobile app.** Telegram *is* the mobile app.
- **Plugin marketplace.** The tool system is extensible, but we're not building discovery, installation, or community features.
- **Real-time collaboration.** The agent works with you, not with a team.
- **Handling money.** No purchases, no financial transactions, no payment processing. The agent can *tell* you about your finances but never act on them.

---

## Non-Functional Requirements

**Reliability:**
- The agent should achieve >99% uptime (measured as: responds to Telegram messages within 30 seconds)
- No data loss on crash — all state is persisted to SQLite before acknowledgment
- Automatic restart via systemd with a max of 3 restart attempts per 5-minute window

**Performance:**
- Response latency: <5 seconds for simple queries, <30 seconds for tool-using queries
- Memory usage: <4GB RSS under normal operation (leaving headroom on the 16GB VPS for local models)
- Database: <1 second for any single query at expected scale (~100K messages, ~10K entities)

**Security:**
- All API keys in `.env`, never in code or logs
- Google OAuth tokens encrypted at rest
- Code execution sandboxed (CPU time limit, memory limit, no network by default)
- VPS hardened: UFW, fail2ban, SSH keys only, no password auth
- Telegram webhook verified with secret token
- No public-facing endpoints beyond the Telegram webhook

**Cost:**
- Target: <$50/month total (VPS + API usage)
- Hard budget caps enforced at daily/weekly/monthly granularity
- Per-request cost tracking with attribution to conversation or task

**Maintainability:**
- Core agent loop: <2,000 lines of Python
- Total codebase (excluding tests): target <10,000 lines at v1
- Every tool is independently testable
- Database migrations are versioned and reversible
- Config is YAML + env vars, no magic

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| OpenRouter goes down | Medium | High — agent can't think | Fallback: direct provider API keys as backup; local model for basic responses |
| SQLite performance at scale | Low | Medium | sqlite-vec is benchmarked for millions of vectors; entity count will stay modest for years |
| EmbeddingGemma-300M quality is poor | Low | Medium | Swap for a different ONNX embedding model; the interface is model-agnostic |
| Telegram rate limits | Low | Low | Respect rate limits; queue outbound messages; use webhooks not polling |
| Runaway LLM costs | Medium | Medium | Hard budget caps, cost-aware routing, alert system |
| Self-built tools introduce bugs | Medium | Low-Medium | Sandbox execution, health checks, auto-disable, require approval for network access |
| Google OAuth token expiry | Medium | Low | Refresh token stored securely; auto-refresh; alert on auth failure |
| Scope creep | High | High | This document. If it's in "Out of Scope," it doesn't get built until the current phases are done. |

---

## Open Questions

Things we haven't decided yet and don't need to decide until later:

1. **What should the agent's default name/personality be?** We have the personality.yaml structure but haven't filled in the defaults. This is a fun decision to make once the skeleton is running.

2. **SearXNG vs. Brave Search API?** SearXNG is self-hosted (free, private) but needs Docker and maintenance. Brave Search has a generous free tier but is an external dependency. Decide during Phase 2.

3. **How aggressive should the proactive system be by default?** Start conservative (only system health monitoring) and dial up based on what feels useful vs. annoying.

4. **Git-based versioning for data/?** Auto-committing personality changes and custom tools to git is appealing for auditability but adds complexity. Evaluate once self-tool-building is implemented.

5. **Domain and web presence for odigos.one?** If we open-source, what goes on the site? GitHub repo link + docs? An interactive demo? A blog? Not a priority until the agent is solid.
