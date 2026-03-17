Analyze these recent tool interactions and extract tactical lessons.

Recent tool errors:
{errors}

Recent successful patterns:
{successes}

Existing experiences (don't duplicate):
{existing}

Extract new tactical experiences. Each should be a specific, actionable lesson.
Also assess your confidence in each lesson and how broadly it applies.

Respond ONLY with valid JSON:
[
  {{"tool_name": "search_documents", "situation": "query returns no results", "outcome": "broadening search terms found the answer", "lesson": "Try broader search terms before giving up on document search", "success": true, "confidence": 0.85, "applicability": "always|sometimes|rare"}}
]

- confidence: 0.0-1.0 how confident the lesson is based on evidence (single incident = 0.5, repeated pattern = 0.9+)
- applicability: "always" (universal rule), "sometimes" (context-dependent), "rare" (edge case)
Only include genuinely new insights. Keep each lesson to one sentence.
