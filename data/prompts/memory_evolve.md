You are a memory evolution system. An existing memory may need updating based on new information.

## Existing Memory

Type: {memory_type}
Content: {existing_content}
Context: {existing_context}
Keywords: {existing_keywords}

## New Information

{new_content}

## Decide

1. **UPDATE** -- the new information enriches the existing memory. Return updated fields.
2. **SUPERSEDE** -- the new information replaces or fundamentally changes the memory. Return a complete new memory.
3. **SKIP** -- the new information adds nothing meaningful.

Return valid JSON only:

For UPDATE:
{{"action": "UPDATE", "context_description": "...", "keywords": [...], "tags": [...]}}

For SUPERSEDE:
{{"action": "SUPERSEDE", "content": "...", "memory_type": "...", "keywords": [...], "tags": [...], "context_description": "..."}}

For SKIP:
{{"action": "SKIP"}}
