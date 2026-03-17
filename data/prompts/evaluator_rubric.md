You are evaluating an AI assistant's response. Generate a scoring rubric for this type of interaction.

User message: {user_content}
Assistant response: {assistant_content}
User reaction signal: {feedback} (-1=negative, +1=positive)

Also identify the key entities (people, tools, documents, concepts) mentioned in the interaction.

Return ONLY a JSON object:
{{"task_type": "category", "criteria": [{{"name": "...", "weight": 0.0-1.0, "description": "what good looks like"}}], "key_entities": ["entity1", "entity2"], "notes": "..."}}
