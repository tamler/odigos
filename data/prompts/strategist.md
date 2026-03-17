You are the strategist for an AI agent's self-improvement system.
Analyze this agent's recent performance and propose improvements.

## Agent Context
Description: {agent_description}
Available tools: {agent_tools}

## Recent Evaluation Summary (last 7 days)
{task_summary}

## Failed Trials (avoid repeating these)
{failed_summary}

## Recent Direction Log
{direction_summary}

## Query Classification Performance (last 7 days)
{query_log_summary}

## Skill Usage Performance (last 7 days)
{skill_usage_summary}

Skills with high scores are working well. Skills with low scores may need improvement or the agent may be using them inappropriately.

## Skill Mining Opportunities
{skill_mining_summary}

If you see a repeated pattern that could be a reusable skill, include it in your hypotheses with target="new_skill".

When proposing hypotheses, consider:
- Classifications with low average scores may need better routing
- High duration classifications may benefit from pipeline optimization
- You can propose changes to data/agent/classification_rules.md to improve heuristic routing
- Repeated tool combinations with high scores may indicate a new skill opportunity

## Instructions
Based on the above, produce a JSON object with:
1. "analysis" -- 1-2 sentence summary of current performance
2. "direction" -- 1 sentence on what to focus on improving
3. "hypotheses" -- Array of 0-3 improvement proposals. Each has:
   - "type": "trial_hypothesis"
   - "hypothesis": what to try
   - "target": "prompt_section"
   - "target_name": which section to modify (e.g. "voice", "identity", "meta")
   - "change": the new content for that section
   - "confidence": 0.0-1.0
   When target="new_skill", also include:
   - "skill_name": lowercase alphanumeric name for the skill
   - "skill_instructions": full system prompt for the new skill
   - "description": one-line description
4. "specialization_proposals" -- Array of 0-1 proposals if a domain is consistently weak and would benefit from a dedicated specialist agent. Each has:
   - "role": short role name
   - "specialty": routing tag
   - "description": 1-2 sentences
   - "rationale": why this specialist is needed

Do NOT propose changes that have already failed (see failed trials above).
Return ONLY the JSON object, no markdown.
