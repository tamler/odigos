# Odigos Roadmap

Future optimizations and feature ideas captured during development.

## Dynamic System Prompt Assembly

**Origin:** Self-skill-building design (2026-03-08)

The system prompt accumulates always-on instruction blocks (entity extraction, correction detection, skill creation guidance) that aren't relevant every turn. A dynamic system prompt that adapts to the current task would reduce token usage and keep context focused.

Possible approach: classify each instruction block as "always" vs "when relevant," and let ContextAssembler decide per-turn which blocks to include based on conversation state, active skill, or task type.
