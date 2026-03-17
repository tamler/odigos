Classify this user message and extract metadata. Respond ONLY with valid JSON, no other text.

Message: "{message}"

Respond with:
{{"classification": "simple|standard|document_query|complex|planning", "entities": ["entity1"], "confidence": 0.85, "search_queries": ["optimized query"], "sub_questions": ["sub-question 1"]}}

Classification guide:
- simple: greetings, acknowledgments, very short messages
- standard: normal questions and requests
- document_query: questions about uploaded documents or files
- complex: multi-part questions, comparisons, analysis requests
- planning: goal-setting, scheduling, strategy requests

Only include sub_questions for complex and planning classifications.
Only include search_queries when the message could benefit from document/memory search.
