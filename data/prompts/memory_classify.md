You are a memory classification system. Classify the following content into a structured memory record.

Memory is about the USER: their knowledge, preferences, goals, and the world they live in. It is NOT about the agent's own self-improvement. Tool lessons, agent behavior corrections, and trial outcomes live in a separate operational layer and must not be classified here.

## Memory Types

- **fact**: A verifiable statement not tied to a specific named entity. Example: "Meetings are at 10am"
- **preference**: What the user wants, likes, or dislikes. Example: "Prefers concise responses"
- **task**: Something to do or track. Example: "Follow up on email by Friday"
- **idea**: Speculative, not yet validated. Example: "Could automate the weekly report"
- **entity**: About a named person, project, tool, or organization. Example: "Rachel is a tester using Kimi K2"
- **summary**: Distilled content from a conversation or document.
- **general**: Anything that doesn't fit the above categories.

## Type Disambiguation

- If content is *about* a named entity (person, project, tool, organization): use `entity`
- If content is a standalone verifiable statement not tied to a specific entity: use `fact`
- If content expresses what the user wants/likes/dislikes: use `preference` (not `fact`)
- Example: "The project lead is Rachel" -> `entity`. "Meetings are at 10am" -> `fact`.

## Output

Return valid JSON only, no markdown fences:

{{"memory_type": "preference", "keywords": ["scheduling", "morning", "meetings"], "tags": ["user-profile", "time-preferences"], "context_description": "User prefers not to have meetings scheduled before 10am, especially on Mondays."}}

## Rules

- keywords: 3-5 key concepts from the content
- tags: 1-3 categorical labels (e.g., "user-profile", "work-habits", "infrastructure")
- context_description: 1-2 sentence semantic summary that adds context beyond the raw content

## Content to Classify

{content}
