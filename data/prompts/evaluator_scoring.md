Score this AI assistant interaction against the rubric.

Rubric: {rubric}

User message: {user_content}
Assistant response: {assistant_content}
User reaction signal: {feedback}

Also provide a one-sentence improvement suggestion and assess the user's likely satisfaction.

Return ONLY a JSON object:
{{"scores": [{{"criterion": "name", "score": 0-10, "observation": "..."}}], "overall": 0-10, "improvement_signal": "what would have been better" or null, "suggested_improvement": "one sentence on what the agent could do better next time", "user_satisfaction_signal": "satisfied|neutral|dissatisfied"}}
