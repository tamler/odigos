Classify this user message and create an execution plan. Respond ONLY with valid JSON.

Recent conversation:
{recent_turns}

Current message: "{message}"

Available tools:
{tool_catalog}

Respond with:
{{"classification": "simple|standard|document_query|complex|planning|creative", "confidence": 0.85, "intent": "what the user wants done", "tool_hint": "tool_name_or_null", "needs": {{"rag": false, "user_profile": false, "user_facts": false, "history": false, "experiences": false}}, "search_queries": [], "response_style": "brief|detailed|step_by_step", "complexity": "single_tool|multi_step|conversation"}}

Rules:
- tool_hint: pick the single most likely tool from the list above, or null if no tool needed
- needs.rag: true only if the answer requires searching documents or past conversations
- needs.user_profile: true only if the answer depends on knowing the user personally
- needs.user_facts: true only if the user references something they told the agent before
- needs.history: true only if this message references earlier messages ("do it again", "change that")
- needs.experiences: true if using a tool (past lessons help)
- response_style: "brief" for simple requests, "detailed" for research/analysis, "step_by_step" for planning
- classification "creative" for any generation request (images, music, code, documents)
