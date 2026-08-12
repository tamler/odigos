# Odigos Features -- Deep Dive

Everything the agent can do and how it works under the hood. Use this for marketing materials, investor decks, blog posts, and technical comparisons.

---

## Why Odigos is Different

Most AI assistants are stateless -- every conversation starts from scratch. Odigos is fundamentally different:

- **It remembers.** Durable knowledge stored as markdown files on disk. Entity graphs with typed relationships. Provenance tracking -- every fact links back to where it was learned. A background lint pass audits for stale claims and contradictions. The agent knows who you are, not just what you said.
- **It improves itself.** A built-in evolution engine evaluates every response, runs experiments on its own behavior, and promotes changes that work. No manual prompt tuning -- the agent tunes itself.
- **It builds its own tools.** When the agent writes code that solves a problem, it saves it as a reusable executable skill. Next time, the tool is already there.
- **It works while you sleep.** A proactive pipeline scans for knowledge gaps, researches topics from recent conversations, and surfaces insights without being asked. You wake up to findings on the Activity page.
- **It's yours.** Self-hosted. Your data stays on your machine. One agent, one owner -- no shared infrastructure, no data leaving your network.

---

## Chat and Communication

Chat through the web dashboard (mobile-friendly PWA), Telegram, or the API. Responses stream word-by-word. The agent builds a profile of you over time -- your communication style, expertise, preferences -- by analyzing conversations in the background. Tell it "remember that I prefer concise answers" and it stores that as an explicit fact. Everything persists across conversations and channels.

**Cross-channel awareness:** Switch between web, Telegram, and API without losing context. The agent knows what you were talking about regardless of channel.

**Voice I/O:** Tap the mic button to record, audio is transcribed server-side via Groq Whisper. Edge-TTS reads responses aloud in voice mode with 30 selectable voices. Adaptive silence threshold calibrates to ambient noise.

---

## Proactive Agent

When idle, the agent doesn't just wait. A 4-stage pipeline runs in the background:

1. **Scan** -- gathers signals from knowledge gaps, recent conversations, active goals, and cross-entity connections. No LLM call -- just fast DB queries.
2. **Prioritize** -- ranks opportunities by user relevance and novelty. Respects feedback -- topics the user ignores are deprioritized over time.
3. **Execute** -- researches the top opportunity using the full agent pipeline (search, RAG, tools). Note: this runs with the full tool registry, not a restricted set. A `proactive.safe_tools` allowlist existed in config but was read by no code, so the read-only mode this line used to claim was never enforced; the dead key was removed 2026-08-12 rather than left as documentation of a control that does not exist.
4. **Publish** -- writes findings as markdown artifacts, sends push notifications, and surfaces results on the Activity page.

The proactive engine learns from implicit feedback: opened findings are positive signals, ignored ones are negative. No manual thumbs up/down required -- engagement IS the signal.

**Controls:** Toggle on/off and adjust frequency (low/medium/high) from Settings > Proactive.

---

## Memory System

Odigos has a multi-layer memory architecture, each layer serving a different purpose:

### Brain (Compiled Knowledge)
Durable markdown files in `data/brain/` -- entity pages, topic indexes, synthesized insights. These survive database drops and can rebuild the entire DB from scratch. A heartbeat maintenance phase projects changed entities to disk every 30 seconds. A lint pass runs every 5 minutes: flags stale claims, orphan entities, contradictions, and missing cross-references.

### Vector Memory (RAG)
All conversation messages and uploaded documents are chunked, embedded locally (nomic-embed-text-v1.5 on CPU -- no API calls), and stored with vector search (sqlite-vec) and full-text search (FTS5). Hybrid retrieval combines both with cross-encoder reranking (ms-marco-MiniLM) for accuracy. Pyramid expansion loads full content for high-relevance results and summaries for the rest, within a token budget.

### Explicit Facts
Discrete facts stored via "remember that..." commands. Facts have categories, provenance, and are injected into every conversation's context -- they don't depend on semantic similarity.

### User Profile (Dreaming)
During idle heartbeat cycles, the agent analyzes recent conversations to build a structured user profile: communication style, expertise areas, preferences, engagement patterns. Built automatically without explicit input.

### Tactical Experiences (XSkill)
The agent learns from tool usage. Successes and failures are stored with context, outcome, and a lesson. Confidence scores track reliability. Stale experiences are pruned, near-duplicates are merged. These lessons are surfaced via dynamic tool mapping when similar situations arise.

### Entity Graph
People, tools, documents, and concepts tracked with typed relationships and confidence scores. Multi-hop traversal (2-hop BFS) pulls in related entities automatically. The graph supports provenance -- every entity links to where it was first mentioned.

---

## Evolution Engine

The agent improves itself without human intervention through a continuous loop:

### The Loop

**Classify -> Execute -> Evaluate -> Dream -> Learn -> Evolve**

1. **Classify** -- every message is categorized using two-tier rules: fast heuristics first, LLM-based for uncertain cases. The rules themselves are evolvable.
2. **Execute** -- the ReAct-style executor runs tools in a loop. Each classification has routing rules controlling available tools and context sections.
3. **Evaluate** -- rubric-based scoring plus implicit feedback detection. AREW-inspired critique scores tool usage quality.
4. **Dream** -- during idle cycles, the agent analyzes conversations, extracts experiences, and mines tool patterns.
5. **Learn** -- the strategist proposes hypotheses from evaluation data. High-confidence proposals are auto-executed.
6. **Evolve** -- proposals become time-boxed trials. The checkpoint manager monitors scores and promotes or reverts changes.

### What Evolves

| Component | How it changes |
|-----------|---------------|
| Classification rules | Heuristic patterns modified by trials |
| Routing rules | Per-classification tool filtering, RAG skipping |
| Prompt sections | Identity, voice, meta instructions |
| Skills | New skills auto-created from detected patterns |
| Experiences | Tactical lessons stored and injected into context |
| Evolution parameters | The strategist tunes its own confidence thresholds |

### Meta-Improvement

The strategist doesn't just improve the agent -- it improves how improvement works. When domain performance trends suggest the evolution system is miscalibrated, the strategist proposes changes to its own parameters. These meta-proposals are evaluated by the same system.

---

## Smart Tool Registry

The agent has 45+ tools but never presents them all at once. Research shows LLM tool selection degrades above 15-20 tools. The registry uses a three-layer approach:

1. **JIT schema injection** -- the classifier determines query type, the executor loads historically-used tools for that type. Ready immediately.
2. **Progressive discovery** -- `find_tools` searches by description when JIT tools don't cover the query. New tools are returned without loading every schema.
3. **Dynamic adaptation** -- as usage patterns change, JIT injection adapts automatically.

Tools are organized in a type hierarchy: `APITool` (external APIs with connection pooling, polling, retry), `CLITool` (subprocess with input hardening, JSON-first output), and local tools. All share a standard contract with JSON schema validation and auto-distill for verbose output.

---

## Tool Execution Contracts

Every tool has an execution contract: retry behavior, timeouts, failure handling. Errors are classified (transient, input, permission, unavailable) with per-category recovery. Transient failures (timeouts, rate limits) are retried transparently with exponential backoff -- the LLM never sees the retry.

**Background execution:** Long-running tools (image/music generation) return immediately with "pending" status. The heartbeat polls for completion. Results appear in chat and on the Activity page via push notification.

---

## What the Agent Can Do

- **Deep research** -- decomposes questions, searches multiple sources, cross-references, produces DOCX/Markdown reports
- **Web search and scraping** -- SearXNG, Brave, or Google; web scraping with content archival
- **Code execution** -- sandboxed Python and shell with memory limits and network isolation
- **File creation** -- CSV, Markdown, JSON, HTML, TXT, XML, YAML, DOCX
- **Image generation and processing** -- create images, resize, crop, OCR, convert
- **Music generation** -- songs with vocals via API
- **Email** -- check inbox, read messages, send replies (BYO SMTP/IMAP)
- **Calendar** -- check events, create events (BYO CalDAV)
- **Notebooks** -- markdown notebooks with journal mode
- **Kanban boards** -- shared boards with drag-and-drop
- **Data tracking** -- structured tables for budgets, expenses, habits, inventory
- **QR codes** -- generate for URLs, WiFi, contacts
- **Knowledge lookup** -- Grokipedia and Wikipedia
- **Translation** -- 100+ languages via Google Translate
- **Text analysis** -- sentiment analysis, spell checking, language detection
- **Goals and todos** -- with proactive follow-up and commitment detection
- **News monitoring** -- RSS feeds filtered by your topics

---

## Skill System

Skills are reusable instruction sets that modify how the agent thinks:

- **Text skills** -- markdown files with instructions injected into conversation context (deep-research, journal, tutor, mentor)
- **Executable skills** -- Python code saved by the agent as callable tools, born from real successful interactions
- **Skill mining** -- the strategist detects repeated tool patterns and proposes new skills automatically

---

## Plan System

For complex multi-step requests, the agent decomposes work into tracked plans with dual-loop verification. Plans persist across conversations. Autonomous execution during idle time uses headless mode (~67% token savings vs full chat history).

---

## Dashboard

- **Activity page** -- agent's command center showing proactive findings, morning briefings, task completions
- **Chat** -- streaming responses, file uploads, voice I/O, suggested actions
- **Notebooks** -- markdown editor with journal mode and agent integration
- **Kanban boards** -- drag-and-drop columns and cards
- **Documents** -- file artifacts created by the agent
- **Settings** -- all configuration, analytics, mesh status, proactive controls, email/calendar setup
- **PWA** -- installable on mobile/desktop, push notifications, biometric login
- **Dark/light theme, mobile responsive, keyboard shortcuts**

---

## Security

- Session-based auth with HTTP-only cookies and API keys
- Sandboxed code execution (bubblewrap isolation)
- Path containment on all file operations
- Multi-layer prompt injection defense (regex, NLP, structural separation, canary tokens)
- SSRF protection (private IP ranges blocked)
- Budget controls (daily/monthly spending caps)
- Storage quotas with monitoring
- Mesh mutual authentication with prompt injection scanning
- Single-user by design -- one agent, one owner

---

## Mesh Networking

Agents connect to each other via WebSocket with mutual authentication and heartbeat monitoring. Auto-connect on startup, reconnect with exponential backoff, real-time messaging between agents. Supervised mode for managed agents with locked settings.

---

## Architecture Summary

One process. One database. No microservices.

| Layer | Tech |
|-------|------|
| Backend | Python 3.12, FastAPI, uvicorn, aiosqlite |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, shadcn/ui |
| Database | SQLite + sqlite-vec (vectors) + FTS5 (full-text) |
| Embeddings | nomic-embed-text-v1.5 (local CPU) |
| Reranking | ms-marco-MiniLM cross-encoder |
| Package mgmt | uv (Python), npm (frontend) |
| Infra | Docker or systemd, single VPS |

Runs on 4 CPU / 16GB RAM. No external databases, message queues, or container orchestration.
