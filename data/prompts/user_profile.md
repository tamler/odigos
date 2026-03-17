Analyze these recent conversations and update the user profile. The user is the owner of this AI agent.

Current profile:
{current_profile}

Recent conversations (last 20):
{conversations}

Based on these conversations, update each section. Keep existing accurate information, add new observations, remove anything contradicted by recent behavior.

Also extract discrete facts about the user. Facts are specific, concrete pieces of information
(e.g., "Lives in Austin, TX", "Prefers Python over JavaScript", "Works as a software engineer").
Only include facts you are reasonably confident about based on the conversations.

Also assess meta-information about the user's engagement with the agent.

Respond ONLY with valid JSON:
{{
  "communication_style": "How the user communicates: formal/casual, verbose/concise, asks for explanations vs trusts the agent",
  "expertise_areas": "Domains the user has shown knowledge in",
  "preferences": "How the user likes things done: step-by-step vs direct answers, level of detail, etc",
  "recurring_topics": "Topics and themes that come up frequently",
  "correction_patterns": "Common corrections or adjustments the user makes",
  "summary": "2-3 sentence overall profile of who this user is and how to best serve them",
  "activity_pattern": "morning|afternoon|evening|mixed -- when the user is most active based on conversation timestamps",
  "engagement_trend": "increasing|stable|decreasing -- is the user using the agent more or less over time?",
  "unmet_needs": "Things the user seems to want but the agent doesn't do well yet (or empty string if none apparent)",
  "relationship_stage": "new|developing|established -- how well does the agent know this user based on interaction depth?",
  "facts": [
    {{"fact": "Example fact about the user", "category": "personal|professional|preference|technical|location|general"}}
  ]
}}