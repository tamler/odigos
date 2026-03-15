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
4. "specialization_proposals" -- Array of 0-1 proposals if a domain is consistently weak and would benefit from a dedicated specialist agent. Each has:
   - "role": short role name
   - "specialty": routing tag
   - "description": 1-2 sentences
   - "rationale": why this specialist is needed

Do NOT propose changes that have already failed (see failed trials above).
Return ONLY the JSON object, no markdown.
