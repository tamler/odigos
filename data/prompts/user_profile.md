Analyze these recent conversations and update the user profile. The user is the owner of this AI agent.

Current profile:
{current_profile}

Recent conversations (last 20):
{conversations}

Based on these conversations, update each section. Keep existing accurate information, add new observations, remove anything contradicted by recent behavior.

Respond ONLY with valid JSON:
{{
  "communication_style": "How the user communicates: formal/casual, verbose/concise, asks for explanations vs trusts the agent",
  "expertise_areas": "Domains the user has shown knowledge in",
  "preferences": "How the user likes things done: step-by-step vs direct answers, level of detail, etc",
  "recurring_topics": "Topics and themes that come up frequently",
  "correction_patterns": "Common corrections or adjustments the user makes",
  "summary": "2-3 sentence overall profile of who this user is and how to best serve them"
}}