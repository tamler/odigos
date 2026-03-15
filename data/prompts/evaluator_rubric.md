You are evaluating an AI assistant's response. Generate a scoring rubric for this type of interaction.

User message: {user_content}
Assistant response: {assistant_content}
User reaction signal: {feedback} (-1=negative, +1=positive)

Return ONLY a JSON object:
{{"task_type": "category", "criteria": [{{"name": "...", "weight": 0.0-1.0, "description": "what good looks like"}}], "notes": "..."}}
