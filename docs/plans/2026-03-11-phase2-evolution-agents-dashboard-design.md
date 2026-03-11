# Phase 2: Evolution Engine, Agent Network, Dashboard — Design Document

## Goal

Extend Odigos with three interconnected capabilities: (1) a strategist module that autonomously proposes and creates self-improvement trials, (2) secure multi-agent communication over a NetBird WireGuard mesh with specialist spawning, and (3) dashboard views for evolution status, agent network, and conversation polish.

## Architecture Overview

Each Odigos instance is a fully autonomous agent with its own evolution engine. Agents communicate over a NetBird WireGuard mesh via WebSocket (primary) and HTTP (fallback). A lightweight agent registry on each instance tracks known peers. The generalist agent can delegate tasks to specialists, and specialists can optionally serve as evaluators for other agents in their domain.

No central orchestrator. The generalist becomes a natural coordinator because it's the one talking to the user — not because it's architecturally special.

---

## 1. Agent Identity & Registry

### Config Changes

```yaml
agent:
  name: "Odigos"
  role: "personal_assistant"
  description: "Jacob's personal AI. Manages scheduling, communications, task delegation."
  parent: null
  allow_external_evaluation: false
```

- `role` — Descriptive label for routing (e.g. `personal_assistant`, `backend_dev`, `sales_outreach`). Evolvable via the evolution engine.
- `description` — 1-2 sentences of natural language. Included in strategist prompts and peer delegation decisions. Also evolvable.
- `parent` — Name of the agent that spawned this one (null for the original).
- `allow_external_evaluation` — Opt-in for receiving evaluation requests from peers.

### Agent Registry Table

New table `agent_registry` on each instance:

| Column | Type | Purpose |
|--------|------|---------|
| `agent_name` | TEXT PK | Unique name on the mesh |
| `role` | TEXT | Role label |
| `description` | TEXT | Natural language description |
| `specialty` | TEXT | Short routing tag (nullable) |
| `netbird_ip` | TEXT | WireGuard mesh address |
| `ws_port` | INTEGER | WebSocket port |
| `status` | TEXT | online / offline / degraded |
| `last_seen` | TEXT | Heartbeat timestamp |
| `capabilities` | TEXT | JSON — tools, skills |
| `evolution_score` | REAL | Current avg evaluation score |
| `allow_external_evaluation` | INTEGER | 0/1 |
| `parent` | TEXT | Who spawned it |
| `updated_at` | TEXT | Last registry update |

On startup, each agent announces itself to all known peers. Heartbeat pings (every 60s over WebSocket) keep status fresh. Peers marked `offline` after 3 missed heartbeats.

---

## 2. Secure Networking via NetBird

### Infrastructure

- Self-hosted NetBird management server on one VPS (or NetBird cloud)
- Each Odigos instance runs the NetBird client
- Every agent gets a stable WireGuard IP (e.g. `100.64.x.x`)
- All agent-to-agent traffic encrypted via WireGuard tunnel

### Communication Protocol

**WebSocket (primary):** Persistent connections between all online peers.

Message types:
- `task_request` — Delegate a task to a peer
- `task_response` — Final response from peer
- `task_stream` — Streaming progress/partial results
- `evaluation_request` — Ask a peer to evaluate an action
- `evaluation_response` — Evaluation result from peer
- `registry_announce` — Peer announcing/updating its profile
- `status_ping` — Heartbeat keepalive

**HTTP (fallback):** Health checks, registry announcements when WebSocket unavailable.

### Security Layers

1. NetBird WireGuard encryption (all traffic, always on)
2. Per-peer API key (existing `require_api_key` pattern)
3. Message signing with shared secret per agent pair (Phase 2b hardening)

### Upgrade Path

Existing `PeerClient` in `odigos/core/peers.py` gets upgraded to `AgentClient` with WebSocket support. The `PeerConfig` in `config.yaml` changes from HTTP URLs to NetBird IPs + ports:

```yaml
peers:
  - name: "Archie"
    netbird_ip: "100.64.0.2"
    ws_port: 8001
    api_key: "archie-shared-secret"
```

---

## 3. Evolution Engine Phase 2 — Strategist

### New Module: `odigos/core/strategist.py`

Runs in heartbeat Phase 5 after scoring. Triggered when `>= 10` new evaluations exist since last strategist run.

### Three-Step Process

**3a. Analyze trends**
- Read recent evaluations, group by `task_type`, identify weak/strong areas
- Read `failed_trials_log` to avoid repeating mistakes
- Read `direction_log` for continuity
- Check agent registry for available specialists (relevant to delegation proposals)

**3b. Generate hypotheses**
- Ask LLM (fallback model) with context: evaluation summary, failed trials, direction history, agent's tools, task distribution, description
- Two output types:
  - `trial_hypothesis` — Self-improvement proposal (feeds into `EvolutionEngine.create_trial()`)
  - `specialization_proposal` — Suggests spawning a new specialist agent (stored for user approval)

**3c. Context-aware optimization**
- The strategist prompt does NOT use hardcoded rules per agent type
- Instead it includes: the agent's actual tools, recent task type distribution, self-description, and direction history
- The LLM decides whether to optimize for breadth or depth based on reality, not a label

### Auto-Trial Creation

- Hypothesis with confidence > 0.7 and no active trial → auto-creates trial
- Below 0.7 → logged to direction_log for future consideration
- Specialization proposals always require user approval

### Scoring Cadence

- Active trial: increased scoring frequency (score 5 actions per cycle)
- No trial, idle: normal rate (score 3 per cycle)
- Budget-constrained: reduce to 1 per cycle

### Migration Additions

```sql
-- Strategist tracking
CREATE TABLE IF NOT EXISTS strategist_runs (
    id TEXT PRIMARY KEY,
    evaluations_analyzed INTEGER,
    hypotheses_generated TEXT,  -- JSON array
    specialization_proposals TEXT,  -- JSON array
    direction_log_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Specialization proposals awaiting approval
CREATE TABLE IF NOT EXISTS specialization_proposals (
    id TEXT PRIMARY KEY,
    proposed_by TEXT,
    role TEXT NOT NULL,
    specialty TEXT,
    description TEXT NOT NULL,
    rationale TEXT,
    seed_knowledge TEXT,  -- JSON
    status TEXT DEFAULT 'pending',  -- pending / approved / dismissed
    approved_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

---

## 4. Cross-Agent Evaluation

### Two-Sided Consent

1. The evaluating agent must have `allow_external_evaluation: true`
2. The requesting agent must opt in to seeking external evaluation

### Evaluation Routing

When the local evaluator runs C.1/C.2:

1. Check agent registry for a peer whose `specialty` matches the action's `task_type`
2. Peer must be `online`, have `allow_external_evaluation: true`, and have `evolution_score > 7.0` with at least one promoted trial
3. If qualified peer found → send `evaluation_request` via WebSocket
4. If no peer or peer unavailable → fall back to local LLM evaluation (current behavior)

### Schema Addition

Add `evaluator_agent TEXT` column to the `evaluations` table to track who scored what.

### Phase 2b

Cross-agent evaluation infrastructure is built now (message types, field), but not activated until specialists exist and prove themselves. The user can also manually approve a specialist as an evaluator without the automated threshold.

---

## 5. Specialist Spawning

### Trigger

- User request: "Create a coding specialist"
- Strategist proposal approved via dashboard

### What Gets Created

1. **Config** — New `config.yaml` with unique name, role, description, parent reference, NetBird peer config, LLM provider settings
2. **Seed identity** — `data/prompt_sections/identity.md` generated by the parent LLM based on the specialty
3. **Seed knowledge** — Relevant memories and corrections cherry-picked from parent, filtered by matching `task_type`
4. **Clean evolution slate** — Empty evaluations, empty direction log, fresh checkpoint

### Deployment Flow

1. Parent generates config + seed files
2. Parent calls a deploy tool specifying target VPS
3. Tool creates container/service on target, installs NetBird client, registers on mesh
4. New agent starts, announces on mesh, begins accepting delegated tasks
5. New agent evolves independently from first interaction

### Config for Deployment Targets

```yaml
deploy_targets:
  - name: "vps-1"
    host: "100.64.0.1"
    method: "docker"  # or systemd
  - name: "vps-2"
    host: "100.64.0.3"
    method: "docker"
```

### Specialist Does NOT Inherit

- Parent's personality (develops its own)
- Parent's full memory (only task-type-relevant subset)
- Parent's evolution history
- Parent's active trials

---

## 6. Dashboard Additions

### 6a. Evolution Dashboard (`/evolution`)

- **Active Trial card** — Hypothesis, time remaining, eval count vs minimum, avg score vs baseline, manual Promote/Revert buttons
- **Evaluation History** — Table: task type, score, implicit feedback, timestamp. Sparkline trend chart
- **Direction Log** — Recent entries showing agent's self-assessment
- **Failed Trials** — Collapsed section with failure reasons and lessons
- **Specialization Proposals** — Pending proposals with Approve/Dismiss actions

### 6b. Agent Network View (`/agents`)

- **Agent cards** — Name, role, description, status, last seen, evolution score per registered peer
- **Connection status** — WebSocket connection state, latency
- **Message history** — Recent inter-agent messages (expandable per-agent)
- **Spawn button** — "Create Specialist" form (name, role, description, target VPS)

### 6c. Conversation Polish

- **Auto-generated titles** — After first assistant response, generate title via fallback model, PATCH to conversation
- **Sidebar already wired** — Just needs backend auto-generation trigger

### API Endpoints Needed

```
GET  /api/evolution/status          — Active trial + recent evals
GET  /api/evolution/evaluations     — Paginated evaluation history
GET  /api/evolution/directions      — Direction log entries
GET  /api/evolution/failed-trials   — Failed trial history
POST /api/evolution/trial/:id/promote  — Manual promote
POST /api/evolution/trial/:id/revert   — Manual revert
GET  /api/agents                    — Registry of known agents
GET  /api/agents/:name/messages     — Message history with a peer
POST /api/agents/spawn              — Create a new specialist
GET  /api/proposals                 — Pending specialization proposals
POST /api/proposals/:id/approve     — Approve a proposal
POST /api/proposals/:id/dismiss     — Dismiss a proposal
```

---

## Implementation Phasing

### Phase 2a (Build First)
1. Strategist module + auto-trial creation
2. Agent registry table + config changes
3. NetBird setup + AgentClient (WebSocket upgrade)
4. Evolution dashboard UI
5. Conversation auto-titles

### Phase 2b (Build Second)
1. Cross-agent evaluation routing
2. Agent network dashboard UI
3. Specialist spawning tool + deployment automation
4. Specialization proposals UI

### Phase 2c (Polish)
1. Message signing hardening
2. Adaptive scoring cadence tuning
3. Specialist seed knowledge optimization
4. Role/description evolution through trials

---

## Key Design Decisions

1. **No central orchestrator** — Every agent is autonomous, generalist coordinates by convention
2. **NetBird from day one** — All peer communication over WireGuard mesh, no plain HTTP shortcuts
3. **WebSocket primary** — Agents maintain persistent connections for real-time delegation and streaming
4. **Context-aware optimization, not type-based** — Strategist reads tools + task distribution + description, not hardcoded rules
5. **Two-sided evaluation consent** — Both evaluator and evaluated agent must opt in
6. **Specialist = fresh entity** — Minimal seed, not a clone. Develops its own personality through evolution
7. **Deploy targets in config** — Spawning knows where it can create agents
8. **Everything evolvable** — Role, description, prompt sections, scoring behavior — all trial-overridable
