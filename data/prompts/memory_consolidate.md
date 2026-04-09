You are a memory synthesis system. A memory has many connections to other memories. Determine if they should be consolidated into a richer, higher-order insight.

## Central Memory

Type: {memory_type}
Content: {content}
Context: {context_description}

## Connected Memories

{connected_block}

## Decide

Should these memories be consolidated into a single richer memory that captures the combined insight?

Return valid JSON only:

{{"should_consolidate": true, "content": "Synthesized insight...", "memory_type": "fact", "keywords": [...], "tags": [...], "context_description": "..."}}

Or if consolidation is not warranted:

{{"should_consolidate": false}}
