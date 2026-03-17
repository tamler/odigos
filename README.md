# Odigos

Your personal AI that gets smarter every day.

Deploy it anywhere, connect any LLM, and get an assistant that remembers everything, learns from its mistakes, writes and saves its own tools, and improves its own behavior without you touching a prompt.

**License:** MIT

---

## Why Odigos?

Most AI assistants are stateless -- every conversation starts from scratch. Odigos is different:

- **It remembers.** Long-term memory across all conversations. Vector search, entity graphs, and automatic summarization mean your agent knows who you are, what you've discussed, and what matters to you.
- **It improves itself.** A built-in evolution engine evaluates every response, runs experiments on its own behavior, and promotes changes that work. No manual prompt tuning.
- **It builds its own tools.** When the agent writes code that solves a problem, it can save it as a reusable executable skill. Next time a similar problem comes up, the tool is already there.
- **It understands complex requests.** An adaptive classifier routes simple questions fast and decomposes complex ones into sub-tasks. The agent tracks its plan, learns from errors, and gets better at routing over time.
- **It's yours.** Self-hosted. Your data stays on your machine. One agent, one owner -- no shared infrastructure, no data leaving your network.

## Quick Start

You need an LLM API key ([OpenRouter](https://openrouter.ai/keys), OpenAI, Ollama, or any OpenAI-compatible provider).

```bash
git clone https://github.com/tamler/odigos.git && cd odigos
```

**Docker (recommended):**
```bash
bash install.sh
```

**Bare metal (Ubuntu, Debian, RHEL, macOS):**
```bash
bash install-bare.sh
```

Open **http://localhost:8000**, create your account, and start chatting.

## What Can It Do?

### Talk and remember
Chat through the web dashboard (mobile-friendly), Telegram, or the API. The agent maintains memory across every conversation -- it knows what you discussed last week.

### Search and research
Web search (SearXNG, Brave, or Google), web scraping, RSS feeds. Upload documents and the agent indexes them for retrieval. Ask questions across all your documents -- the agent writes code to search them programmatically when simple retrieval isn't enough.

### Execute code
Sandboxed Python and shell execution with memory limits, timeouts, and network isolation. The agent can write and run code to solve problems, then save working solutions as reusable tools.

### Manage your life
Goals, todos, reminders with proactive follow-up. Cron jobs for recurring tasks. The agent checks in via its heartbeat loop and nudges you when things are due.

### Work with your tools
Google Workspace (Gmail, Calendar, Drive), browser automation, MCP server integration, file management. Extend with plugins -- no restart required.

### Speak and listen
Optional voice: mic button for speech-to-text, speaker button for text-to-speech. Local models, no cloud dependency.

### Connect with other agents
Mesh networking over WireGuard. Contact cards for establishing trust. Spawn specialist agents from a catalog of 140+ personality templates. Agents evaluate each other's work.

## How It Gets Smarter

Odigos has a self-improvement loop that runs continuously:

**1. Classify** -- Every incoming message is categorized (simple, standard, document query, complex, planning) with evolvable rules. Simple questions skip heavy processing. Complex ones get decomposed into sub-tasks.

**2. Execute** -- The agent works through the request using its tools, memory, and skills. It tracks which tools it uses and how long each step takes.

**3. Evaluate** -- After responding, the evaluator scores the conversation using implicit feedback signals and rubric-based assessment.

**4. Learn** -- The strategist analyzes patterns: which query types score well? Which tools work for which tasks? Which skills get reused? It proposes experimental changes.

**5. Evolve** -- The evolution engine runs time-boxed trials. Changes that improve scores get promoted. Changes that hurt get reverted. Classification rules, routing, prompt sections, and skills all evolve this way.

The agent also learns from errors (tool failures are logged and surfaced to avoid repeating mistakes) and from skill reuse (successful code patterns are tracked and recommended for similar future tasks).

## Architecture

One process. One database. No microservices.

- **FastAPI** with WebSocket for real-time chat
- **SQLite** with vector search (sqlite-vec) and full-text search (FTS5)
- **Local embeddings** (nomic-embed-text-v1.5) on CPU -- no API calls for embedding
- **Cross-encoder reranking** (ms-marco-MiniLM) for document retrieval accuracy
- **Plugin system** for tools, channels, and providers
- **Heartbeat loop** for background processing, goal tracking, evolution trials

Everything runs on a single VPS. 4 CPU, 16GB RAM is comfortable. No external databases, no message queues, no container orchestration.

## Configuration

Two files:

- **`.env`** -- Secrets (LLM API key, session secret)
- **`config.yaml`** -- Everything else (models, budget, tools, plugins)

Key settings:

| Section | What it controls |
|---------|-----------------|
| `llm` | Models, temperature, base URL |
| `budget` | Daily/monthly spending caps |
| `agent` | Name, tool turn limits, timeouts |
| `approval` | Which tools need human sign-off |
| `evolution` | Trial duration, thresholds |
| `voice` | TTS/STT on/off |

## Plugins

| Plugin | What it adds |
|--------|-------------|
| Web Search | SearXNG, Brave, or Google search |
| Google Workspace | Gmail, Calendar, Drive |
| Agent Browser | Browser automation |
| Telegram | Telegram bot interface |
| TTS/STT | Voice input and output |
| Docling | Deep document extraction |

Enable in the Plugins tab. Changes apply immediately.

## Security

- **Auth:** Username/password with signed HTTP-only session cookies. API key for programmatic access.
- **Sandbox:** Code runs in bubblewrap isolation with memory/timeout limits.
- **Approval gates:** Dangerous tools require human sign-off.
- **Budget controls:** Daily and monthly spending caps.
- **SSRF protection:** Private IP ranges blocked in web scraping.
- **Single-user:** One agent, one owner. Multi-user is handled at the deployment layer.

## Development

```bash
uv sync                        # Install dependencies
uv run pytest                  # Run tests (1000+)
uv run python -m odigos.main   # Start locally
cd dashboard && npm run dev    # Dashboard dev server
```

## Acknowledgments

- Evolution engine inspired by [autoresearch](https://github.com/karpathy/autoresearch) by Andrej Karpathy
- Executable skills inspired by [SAGE](https://arxiv.org/html/2512.17102v2) (Skill Augmented GRPO for Self-Evolution)
- Document analysis inspired by [RLM](https://arxiv.org/html/2512.24601v2) (Recursive Language Models)
- Plan persistence inspired by [planning-with-files](https://github.com/OthmanAdi/planning-with-files)

## License

MIT
