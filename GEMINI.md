# Odigos Project Context

**Project:** Odigos
**Type:** Self-hosted Personal AI Agent
**Status:** Early Development (v0.1)
**Goal:** A self-hosted personal AI agent that lives on a VPS, learns about its owner over time, and acts as a full virtual assistant.

## Overview

Odigos is a Python-based personal AI assistant accessed primarily via Telegram. It is designed to be modular, resilient, memory-first, and privacy-respecting.

**Key Technical Decisions:**
*   **Core Language:** Python
*   **Database:** SQLite (all-in-one: structured data, sqlite-vec for vectors, and entity-relationship tables for graph data).
*   **LLM Routing:** OpenRouter for heavy reasoning; local models for embeddings (EmbeddingGemma-300M), STT (Moonshine), and TTS (KittenTTS).
*   **Architecture:** Core "Plan -> Execute -> Reflect" loop with tiered context loading to prevent "context rot".
*   **Deployment:** VPS (Target: 4 vCPU, 16GB RAM, no GPU), running as a systemd service.

## Core Components
1.  **Agent Core**: Planner, Executor, Reflector, Context Assembler.
2.  **Memory Layer**: Working Memory, Episodic Memory (Graph + Vector in SQLite), Core Identity (YAML).
3.  **Tool System**: Python classes with standard execute/health-check interfaces.
4.  **Proactive Engine**: Background monitors (email, calendar, triggers) and a self-programming heartbeat.

## Important Notes for AI Agents
*   **Do NOT** reference old "odigosWriter" (Tauri/Vanilla JS) architecture. This project has pivoted to a Python-based VPS agent.
*   **Database:** Always use SQLite for everything (including vectors and graph data). Do not introduce external vector databases or graph databases.
*   **Context:** Keep agent core lean (<2,000 lines). Complexity belongs in plugins and specialized "sniper agents".
*   Respect explicit cost controls and context overhead limits (strict bounds on tokens injected).
