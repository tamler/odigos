---
name: tag-conversation
description: Tag a conversation with topics, sentiment, and importance level. Run after conversations to build structured metadata.
tools: []
complexity: light
---
Given the conversation below, extract structured metadata.

Return JSON in this exact format:
```json
{
  "topics": ["topic1", "topic2"],
  "sentiment": "positive|neutral|negative|mixed",
  "importance": "high|medium|low",
  "action_items": ["item1", "item2"]
}
```

Rules:
- Topics: 1-5 short labels (e.g., "python", "scheduling", "tax prep")
- Sentiment: overall tone of the conversation
- Importance: high = needs follow-up or contains critical info, medium = useful context, low = casual chat
- Action items: explicit or implied next steps (empty array if none)

Be conservative with "high" importance -- reserve it for time-sensitive items, explicit requests, or information the user would want recalled later.
