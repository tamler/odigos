# Multi-hop GraphRAG Design

**Date:** 2026-04-04
**Status:** Approved
**Goal:** Expand entity context from 1-hop to 2-hop traversal so the agent automatically pulls in related entities (e.g., "The Q3 Project" pulls in Sarah as lead and Budget.docx).

## Context

The entity graph already has `traverse(entity_id, depth=2)` implemented via recursive CTE in `graph.py`. But `manager.recall()` only calls `get_related()` (1-hop) and doesn't show relationship types in the output. The fix is narrow: use 2-hop traversal and format output with relationship paths.

## Design

### 1. New method: `traverse_with_paths()` in graph.py

The existing `traverse()` returns entities but not the edges connecting them. Add `traverse_with_paths()` that returns entities WITH relationship info using a CTE that captures the path.

```python
async def traverse_with_paths(self, entity_id: str, depth: int = 2) -> list[dict]:
    """Multi-hop traversal returning entities with relationship paths."""
    # Returns: [{entity fields + "relationship": str, "from_name": str, "hop": int}]
```

### 2. Updated recall() in manager.py

Replace 1-hop `get_related()` with 2-hop `traverse_with_paths()`. Cap total entities at 8 across all seed entities. Rank by hop distance (closer = more relevant), then edge strength.

### 3. Updated output format

```markdown
## Known entities
- Alice: person, senior engineer
  -> works_on -> Odigos (project)
  -> colleague -> Bob (person)
  -> Odigos -> uses -> SQLite (concept)
```

Includes relationship types so the agent can trace reasoning chains.

## Files Changed

| File | Change |
|------|--------|
| `odigos/memory/graph.py` | Add `traverse_with_paths()` method |
| `odigos/memory/manager.py` | Use 2-hop traversal in `recall()`, format with relationship paths |

## Future (Roadmap)

**Configurable depth per classification:** Simple queries stay 1-hop, complex/planning queries get 2-hop. Controlled via routing rules. Not built now.
