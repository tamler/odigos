Score this AI assistant interaction against the rubric.

Rubric: {rubric}

User message: {user_content}
Assistant response: {assistant_content}
User reaction signal: {feedback}

Return ONLY a JSON object:
{{"scores": [{{"criterion": "name", "score": 0-10, "observation": "..."}}], "overall": 0-10, "improvement_signal": "what would have been better" or null}}
