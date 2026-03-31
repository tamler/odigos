Assess this user's engagement with their AI agent based on recent conversations.

Recent conversations:
{conversations}

Respond ONLY with valid JSON:
{{
  "activity_pattern": "morning|afternoon|evening|mixed",
  "engagement_trend": "increasing|stable|decreasing",
  "unmet_needs": "things the user seems to want but the agent doesn't do well (or empty string)",
  "relationship_stage": "new|developing|established",
  "facts": [
    {{"fact": "specific fact about the user", "category": "personal|professional|preference|technical|location|general"}}
  ]
}}
