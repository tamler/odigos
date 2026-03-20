# Odigos

Your personal AI that gets smarter every day.

Deploy it anywhere, connect any LLM, and get an assistant that remembers everything, learns from its mistakes, writes and saves its own tools, and improves its own behavior without you touching a prompt.

**License:** MIT

---

## Why Odigos?

Most AI assistants are stateless -- every conversation starts from scratch. Odigos is different:

- **It remembers.** Three-layer memory: explicit facts you tell it ("I prefer Python"), a user profile it builds by analyzing your conversations while idle, and long-term conversation memory with vector search and entity graphs. It knows who you are, not just what you said.
- **It improves itself.** A built-in evolution engine evaluates every response, runs experiments on its own behavior, and promotes changes that work. No manual prompt tuning.
- **It builds its own tools.** When the agent writes code that solves a problem, it can save it as a reusable executable skill. Next time a similar problem comes up, the tool is already there.
- **It understands complex requests.** An adaptive classifier routes simple questions fast and decomposes complex ones into sub-tasks. The agent tracks its plan, learns from errors, and gets better at routing over time.
- **It stays sharp.** AREW-inspired critique signals detect when the agent stops using its tools effectively or ignores information it retrieved, then automatically propose and test fixes.
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
Chat through the web dashboard (mobile-friendly), Telegram, or the API. Responses stream word-by-word. The agent builds a profile of you over time -- your communication style, expertise, preferences -- by analyzing conversations in the background. Tell it "remember that I prefer concise answers" and it stores that as an explicit fact. Everything persists across conversations.

### Notebooks and journals
Built-in markdown notebooks with agent integration. Start a journal and the agent offers guided prompts, tracks your mood, and recognizes patterns. The agent reads notebook content contextually when you're on the page and can suggest or add entries based on collaboration level.

### Kanban boards
Shared kanban boards between you and the agent. Create boards, manage cards with drag-and-drop, and the agent has full read/write access via tools. Ask it to create tasks, move cards as work progresses, or summarize what's in progress. Your board is a shared workspace for getting things done.

### Create files and artifacts
Ask the agent to generate a spreadsheet, report, or document and it creates a downloadable file. Supports CSV, Markdown, JSON, HTML, TXT, XML, and YAML. Files appear as download cards in the chat.

### Search and research
Web search (SearXNG, Brave, or Google), web scraping, RSS feeds. Upload documents and the agent indexes them for retrieval. Ask questions across all your documents -- the agent writes code to search them programmatically when simple retrieval isn't enough.

### Execute code
Sandboxed Python and shell execution with memory limits, timeouts, and network isolation. The agent can write and run code to solve problems, then save working solutions as reusable tools.

### Manage your life
Goals, todos, reminders with proactive follow-up. Cron jobs for recurring tasks. The agent checks in via its heartbeat loop and nudges you when things are due.

### Analytics
Built-in analytics dashboard showing query classifications, skill usage, tool errors, and active plans. See how your agent is performing at a glance.

### Work with your tools
Google Workspace (Gmail, Calendar, Drive), browser automation, MCP server integration, file management. Extend with plugins -- no restart required.

### Speak and listen
Optional voice: mic button for speech-to-text, speaker button for text-to-speech. Local models, no cloud dependency.

### Connect with other agents
Mesh networking with WebSocket auto-connect, mutual authentication, and heartbeat monitoring. Agents connect on startup, reconnect with exponential backoff, and can message each other in real-time. Contact cards for establishing trust. HTTP fallback for co-located agents.

## How It Gets Smarter

Odigos has a self-improvement loop that runs continuously:

**1. Classify** -- Every incoming message is categorized (simple, standard, document query, complex, planning) with [evolvable rules](https://arxiv.org/html/2603.11808v1). Simple questions skip heavy processing. Complex ones get decomposed into sub-tasks with persistent plans.

**2. Execute** -- The agent works through the request using its tools, memory, and skills. It tracks which tools it uses, how long each step takes, and how many tokens each classification costs.

**3. Evaluate** -- After responding, the evaluator scores the conversation using implicit feedback signals and rubric-based assessment. [AREW-inspired](https://arxiv.org/abs/2603.12109) critique signals also score whether the agent used appropriate tools (Action Selection) and whether it actually used the information it retrieved (Belief Tracking).

**4. Dream** -- In the background, the heartbeat ["dreams"](https://github.com/plastic-labs/honcho): analyzing conversations to build a [user profile](https://manthanguptaa.in/posts/chatgpt_memory/), extracting [tactical experiences](https://arxiv.org/html/2603.12056v2) from tool successes and failures, and mining repeated patterns for new skills.

**5. Learn** -- The strategist analyzes classification stats, skill usage, token costs, experience data, and AREW critique aggregates. It proposes experimental changes AND auto-creates new skills when it detects repeated patterns. When the agent frequently ignores its tools, the strategist proposes routing fixes.

**6. Evolve** -- The evolution engine runs time-boxed trials. Changes that improve scores get promoted. Changes that hurt get reverted. Classification rules, routing, prompt sections, and skills all evolve this way.

Three layers of memory feed the loop: [explicit facts](https://manthanguptaa.in/posts/chatgpt_memory/) the user states ("I prefer Python"), a user profile built from conversation analysis, and long-term conversation memory with vector search and entity graphs. The agent also maintains tactical experiences -- lessons learned from past tool interactions that prevent repeating the same mistakes.

## Architecture

One process. One database. No microservices.

- **FastAPI** with WebSocket for real-time streaming chat
- **SQLite** with vector search (sqlite-vec) and full-text search (FTS5)
- **Local embeddings** (nomic-embed-text-v1.5) on CPU -- no API calls for embedding
- **Cross-encoder reranking** (ms-marco-MiniLM) for document retrieval accuracy
- **Plugin system** for tools, channels, and providers
- **Heartbeat loop** for background processing, goal tracking, evolution trials
- **Parallel context assembly** -- 11 context queries run concurrently via asyncio.gather
- **Message queue** -- WebSocket chat messages never dropped, processed sequentially

Everything runs on a single VPS. 4 CPU, 16GB RAM is comfortable. No external databases, no message queues, no container orchestration.

## Dashboard

The web dashboard features:

- **Chat** with streaming responses, file uploads, voice I/O
- **Notebooks** with journal mode and contextual agent chat
- **Kanban boards** with drag-and-drop columns and cards
- **Cowork layout** -- any page can have a contextual agent chat panel alongside it
- **Contextual links** below the chat input for quick access to Journal, Board, Documents
- **Settings** with analytics, mesh status, peer configuration, and all agent settings
- **Keyboard shortcuts** -- Escape, Cmd+K, Cmd+N
- **Dark/light theme**
- **Mobile responsive**

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
| `notebooks` | Enable/disable notebooks |
| `kanban` | Enable/disable kanban boards |
| `mesh` | Enable/disable agent mesh networking |
| `voice` | TTS/STT on/off |

## Plugins

| Plugin | What it adds |
|--------|-------------|
| Web Search | SearXNG, Brave, or Google search |
| Google Workspace | Gmail, Calendar, Drive (requires gcloud setup) |
| Agent Browser | Browser automation |
| Telegram | Telegram bot interface |
| TTS/STT | Voice input and output |
| Docling | Deep document extraction |

Enable in the Plugins tab. Changes apply immediately.

## Security

- **Auth:** Username/password with signed HTTP-only session cookies. API key for programmatic access. All endpoints require authentication.
- **Sandbox:** Code runs in bubblewrap isolation with memory/timeout limits.
- **Upload validation:** Blocked file extensions (.exe, .sh, .php, etc.) and magic byte detection for renamed executables.
- **Approval gates:** Dangerous tools require human sign-off.
- **Budget controls:** Daily and monthly spending caps.
- **SSRF protection:** Private IP ranges blocked in web scraping.
- **Mesh auth:** Mutual API key authentication on WebSocket connections. Prompt injection scanning on all inbound peer messages.
- **Single-user:** One agent, one owner. Multi-user is handled at the deployment layer.

## Development

```bash
uv sync                        # Install dependencies
uv run pytest                  # Run tests (1094+)
uv run python -m odigos.main   # Start locally
cd dashboard && npm run dev    # Dashboard dev server
```

## Acknowledgments

- Evolution engine inspired by [autoresearch](https://github.com/karpathy/autoresearch) by Andrej Karpathy
- Active reasoning critique inspired by [AREW](https://arxiv.org/abs/2603.12109) (Active Reasoning with Edge-Weighted)
- Executable skills inspired by [SAGE](https://arxiv.org/html/2512.17102v2) (Skill Augmented GRPO for Self-Evolution)
- Skill mining and three-level loading inspired by [Automating Skill Acquisition](https://arxiv.org/html/2603.11808v1) and [Anthropic Skills](https://github.com/anthropics/skills)
- Experience layer inspired by [XSkill](https://arxiv.org/html/2603.12056v2) (Continual Learning in Multimodal Agents)
- Document analysis inspired by [RLM](https://arxiv.org/html/2512.24601v2) (Recursive Language Models)
- Plan persistence inspired by [planning-with-files](https://github.com/OthmanAdi/planning-with-files)
- User profiling and fact extraction inspired by [ChatGPT's memory architecture](https://manthanguptaa.in/posts/chatgpt_memory/) and [Honcho](https://github.com/plastic-labs/honcho)
- Token efficiency tracking inspired by [jMunchWorkbench](https://github.com/jgravelle/jMunchWorkbench)

## License

MIT
