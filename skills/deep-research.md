---
name: deep-research
description: Conduct thorough multi-round research on a topic, producing a comprehensive report the user can walk away from
tools: [decompose_query, web_search, read_page, run_code, create_artifact, send_notification, check_plan, update_plan]
complexity: standard
---

# Deep Research Mode

When the user asks for in-depth research on a topic, conduct a thorough multi-round investigation. This is NOT a quick search -- it's a structured research process that produces a comprehensive deliverable.

## Process

### 1. Decompose the question
Use decompose_query to break the topic into 4-8 research sub-questions. Each sub-question should cover a different angle (market landscape, key players, technical approaches, trends, risks, opportunities, etc.).

### 2. Research each sub-question
For EACH sub-question:
- Run 2-3 different web searches with varied queries
- Read the most relevant pages (at least 2-3 sources per sub-question)
- Extract key facts, data points, quotes, and sources
- Use update_plan to mark each sub-question as done with notes

### 3. Cross-reference and synthesize
After gathering information:
- Identify themes that appear across multiple sources
- Note contradictions or disagreements between sources
- Identify gaps where information is missing or uncertain
- Draw connections between sub-topics

### 4. Self-review loop (inspired by ARIS)
Review your own findings critically:
- What claims lack sufficient evidence? Research those gaps.
- What questions would a skeptic ask? Find answers.
- Are there perspectives you missed? Search for counterarguments.
- Run 1-2 additional targeted searches to fill the biggest gaps.
Use update_plan to track the review round.

### 5. Create deliverables

Use create_artifact to produce:
- **Main report** (research-report.md or research-report.docx): Executive summary, findings per sub-topic, analysis, conclusions, recommendations
- **Sources list** (sources.csv): URL, title, date, relevance, key finding from each source
- Optional: data tables, comparison matrices, or other structured data as CSV

### 6. Notify the user
When complete, use send_notification to alert the user that the research is ready for review. Summarize the key findings in the notification.

## Quality Standards

- Minimum 10 unique sources cited
- Each claim should reference a specific source with a clickable link
- Always include URLs as markdown links: [Source Title](https://url.com)
- In chat responses, provide clickable links to key sources so the user can explore further
- Include dates on information to show currency
- Acknowledge limitations and areas needing further investigation
- Use check_plan periodically to verify you're making progress

## Behavior

- This is a long-running task. Do NOT try to do it in one turn.
- Use the plan system to track progress across multiple turns.
- If the user sends another message mid-research, acknowledge it and continue.
- If you hit a dead end on a sub-question, note it and move on.
- Prefer recent sources (last 1-2 years) over older ones.
- Be thorough but not exhaustive -- aim for comprehensive coverage, not perfection.
