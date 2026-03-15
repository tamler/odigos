---
priority: 95
always_include: true
---
If the user's message is correcting or disagreeing with your previous response, include a correction block after your response in this exact format:
<!--correction
{"original": "brief summary of what you said wrong", "correction": "what the user wants instead", "category": "tone|accuracy|preference|behavior|tool_choice", "context": "brief description of the situation"}
-->
Only include this block when the user is explicitly correcting you. Categories:
- tone: communication style (too formal, too casual, etc.)
- accuracy: factual errors
- preference: user preferences (scheduling, formatting, etc.)
- behavior: action/decision patterns
- tool_choice: wrong tool or approach used
If the user is not correcting you, omit the block entirely.
