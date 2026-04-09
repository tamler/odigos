"""Two-axis prompt evolution — consolidate corrections into personality sections."""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import tiktoken

logger = logging.getLogger(__name__)

_ENCODER = None


def _count_tokens(text: str) -> int:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return len(_ENCODER.encode(text))


@dataclass
class ConsolidationOp:
    op: str
    rule: str = ""
    old_rule: str | None = None
    reason: str | None = None
    source_correction_id: str | None = None
    conflict: bool = False


class PromptConsolidator:
    """Distills raw corrections into personality section files."""

    OPERATIONAL_FILENAME = "operational_rules.md"
    BEHAVIORAL_FILENAME = "behavioral_principles.md"
    MIN_BATCH_SIZE = 3
    MAX_SECTION_TOKENS = 300

    def __init__(self, db, llm_client, prompts_dir="data/prompts", sections_dir="data/agent"):
        self._db = db
        self._llm = llm_client
        self._prompts_dir = Path(prompts_dir)
        self._sections_dir = Path(sections_dir)

    async def consolidate(self) -> dict:
        """Main entry point. Classifies and merges unconsolidated corrections.

        Returns a stats dict with corrections_processed, operations_applied, compacted.
        """
        corrections = await self._load_unconsolidated()

        if len(corrections) < self.MIN_BATCH_SIZE:
            logger.debug(
                "Only %d unconsolidated corrections — skipping (min batch: %d)",
                len(corrections),
                self.MIN_BATCH_SIZE,
            )
            return {"corrections_processed": 0, "operations_applied": 0, "compacted": False}

        result = await self._classify_and_merge(corrections)

        classifications = {
            c["correction_id"]: c["axis"]
            for c in result.get("classifications", [])
        }
        operations = result.get("operations", [])
        updated_section = result.get("updated_section", "")

        # Separate corrections by axis — operational/behavioral get updated_section written,
        # knowledge get marked skipped.
        knowledge_ids = {
            cid for cid, axis in classifications.items() if axis == "knowledge"
        }

        # Determine which file to write: use the majority axis among non-knowledge corrections.
        non_knowledge = [
            (cid, axis) for cid, axis in classifications.items()
            if axis != "knowledge"
        ]
        axis_counts: dict[str, int] = {}
        for _, axis in non_knowledge:
            axis_counts[axis] = axis_counts.get(axis, 0) + 1

        target_filename = self.OPERATIONAL_FILENAME
        if axis_counts.get("behavioral", 0) > axis_counts.get("operational", 0):
            target_filename = self.BEHAVIORAL_FILENAME

        # Write the updated section content (only if there's something to write)
        compacted = False
        if updated_section.strip() and non_knowledge:
            self._write_section(target_filename, updated_section.strip())

            # Run compaction if section exceeds token budget
            current_content = self._read_section_content(target_filename)
            if _count_tokens(current_content) > self.MAX_SECTION_TOKENS:
                compacted_content = await self._compact(current_content)
                if compacted_content:
                    self._write_section(target_filename, compacted_content.strip())
                    compacted = True

        # Mark all corrections as consolidated
        now = datetime.now(timezone.utc).isoformat()
        for correction in corrections:
            cid = correction["id"]
            if cid in knowledge_ids:
                await self._db.execute(
                    "UPDATE corrections SET consolidated_at = ? WHERE id = ?",
                    ("skipped", cid),
                )
            else:
                await self._db.execute(
                    "UPDATE corrections SET consolidated_at = ? WHERE id = ?",
                    (now, cid),
                )

        # Write consolidation log entry
        log_id = str(uuid.uuid4())
        ops_json = json.dumps(operations)
        rules_before = len(self._read_section_content(target_filename).splitlines())
        rules_after = len(updated_section.splitlines()) if updated_section else rules_before

        await self._db.execute(
            "INSERT INTO consolidation_log "
            "(id, axis, corrections_processed, operations_json, rules_before, rules_after, compacted) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                log_id,
                target_filename.replace(".md", ""),
                len(corrections),
                ops_json,
                rules_before,
                rules_after,
                int(compacted),
            ),
        )

        try:
            await self._db.commit()
        except AttributeError:
            pass  # Some DB wrappers auto-commit

        return {
            "corrections_processed": len(corrections),
            "operations_applied": len(operations),
            "compacted": compacted,
        }

    async def _load_unconsolidated(self) -> list[dict]:
        """Load corrections that have not yet been consolidated."""
        rows = await self._db.fetch_all(
            "SELECT id, conversation_id, original_response, correction, context, category, created_at "
            "FROM corrections WHERE consolidated_at IS NULL ORDER BY created_at ASC"
        )
        return [dict(r) for r in rows]

    async def _classify_and_merge(self, corrections: list[dict]) -> dict:
        """Call LLM to classify corrections and produce merge operations."""
        template = self._load_prompt("consolidation_merge.md")

        # Build corrections block text
        lines = []
        for c in corrections:
            lines.append(
                f"ID: {c['id']}\n"
                f"Category: {c.get('category', 'unknown')}\n"
                f"Original: {c.get('original_response', '')}\n"
                f"Correction: {c.get('correction', '')}\n"
                f"Context: {c.get('context', '')}\n"
                f"Date: {c.get('created_at', '')}"
            )
        corrections_block = "\n\n---\n\n".join(lines)

        # Load current rules for both section files to give the LLM full context
        operational_content = self._read_section_content(self.OPERATIONAL_FILENAME)
        behavioral_content = self._read_section_content(self.BEHAVIORAL_FILENAME)
        current_rules = ""
        if operational_content:
            current_rules += f"### Operational Rules\n{operational_content}\n\n"
        if behavioral_content:
            current_rules += f"### Behavioral Principles\n{behavioral_content}"
        current_rules = current_rules.strip() or "(empty)"

        prompt = (
            template
            .replace("{current_rules}", current_rules)
            .replace("{corrections_block}", corrections_block)
        )

        response = await self._llm.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
        )

        return self._parse_json(response.content)

    async def _compact(self, content: str) -> str | None:
        """Call LLM to compact a section that has exceeded the token budget."""
        template = self._load_prompt("consolidation_compact.md")
        prompt = (
            template
            .replace("{current_rules}", content)
            .replace("{max_tokens}", str(self.MAX_SECTION_TOKENS))
        )

        try:
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1000,
            )
            return response.content.strip() or None
        except Exception as exc:
            logger.warning("Compaction LLM call failed: %s", exc)
            return None

    def _read_section_content(self, filename: str) -> str:
        """Read section file and strip YAML frontmatter."""
        path = self._sections_dir / filename
        if not path.exists():
            return ""
        text = path.read_text()
        # Strip YAML frontmatter (--- ... ---)
        stripped = re.sub(r"^---\n.*?\n---\n?", "", text, flags=re.DOTALL)
        return stripped.strip()

    def _write_section(self, filename: str, content: str) -> None:
        """Write section file, preserving any existing YAML frontmatter."""
        path = self._sections_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)

        # Preserve existing frontmatter if present
        frontmatter = ""
        if path.exists():
            existing = path.read_text()
            match = re.match(r"^(---\n.*?\n---\n?)", existing, re.DOTALL)
            if match:
                frontmatter = match.group(1)

        new_text = frontmatter + content + "\n" if content else frontmatter
        path.write_text(new_text)

    def _load_prompt(self, filename: str) -> str:
        """Load a prompt template from the prompts directory."""
        path = self._prompts_dir / filename
        return path.read_text()

    def _parse_json(self, content: str) -> dict:
        """Parse JSON from LLM response, handling markdown fences."""
        text = content.strip()

        # Strip ```json ... ``` or ``` ... ``` fences using regex
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text, count=1)
            text = re.sub(r"\n?```\s*$", "", text.rstrip())
            text = text.strip()

        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            logger.warning("Parsed JSON is not a dict: %r", result)
            return {}
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse JSON from LLM response: %s", exc)
            return {}
