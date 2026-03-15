---
priority: 100
always_include: true
---
After your response, on a new line, include extracted entities in this exact format:
<!--entities
[{"name": "...", "type": "person|project|preference|concept", "relationship": "...", "detail": "..."}]
-->
Only include entities if the conversation mentions specific people, projects, preferences, or important concepts.
If none are relevant, omit the block entirely.
