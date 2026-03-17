Summarize this conversation segment. Return ONLY valid JSON with this structure:

{{
  "summary": "A structured summary of the conversation. Include Goal, Progress, Decisions, Next Steps, and Key Facts sections as relevant. Use markdown formatting within this string.",
  "tags": ["topic-tag-1", "topic-tag-2"],
  "key_facts": ["Factual statement 1 extracted from the conversation", "Factual statement 2"],
  "action_items": ["Pending action 1", "Pending action 2"]
}}

Guidelines:
- summary: Compress the conversation into a structured overview. Include only sections with relevant content. Be concise.
- tags: 2-5 lowercase topic tags for correlation (e.g., "code-review", "debugging", "research").
- key_facts: Specific factual statements worth remembering (e.g., "User uploaded report.pdf", "API rate limit is 100/min").
- action_items: Any pending actions or follow-ups mentioned. Empty array if none.
