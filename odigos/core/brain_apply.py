"""Apply a brain compilation manifest to disk.

Reads a JSON manifest from the brain-compiler sub-agent and applies
create/update/archive operations to data/brain/. Operations are applied
in dependency order: creates first, then updates, then archives.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


async def apply_compilation(
    manifest_json: str,
    brain_dir: str = "data/brain",
) -> dict:
    """Apply a brain compilation manifest to disk.

    Args:
        manifest_json: JSON string with operations, summary, etc.
        brain_dir: Root directory for brain files.

    Returns:
        {created: int, updated: int, archived: int, errors: list[str], summary: str}
    """
    try:
        manifest = json.loads(manifest_json)
    except (json.JSONDecodeError, TypeError) as exc:
        return {"created": 0, "updated": 0, "archived": 0,
                "errors": [f"Invalid manifest JSON: {exc}"], "summary": ""}

    operations = manifest.get("operations", [])
    summary = manifest.get("summary", "")

    if not operations:
        return {"created": 0, "updated": 0, "archived": 0,
                "errors": [], "summary": summary}

    brain = Path(brain_dir)

    # Sort operations by dependency order: create → update → archive
    creates = [op for op in operations if op.get("op") == "create"]
    updates = [op for op in operations if op.get("op") == "update"]
    archives = [op for op in operations if op.get("op") == "archive"]
    ordered = creates + updates + archives

    stats = {"created": 0, "updated": 0, "archived": 0, "errors": [], "summary": summary}

    for op in ordered:
        op_type = op.get("op")
        rel_path = op.get("path", "")

        # Path validation
        if not rel_path or ".." in rel_path:
            stats["errors"].append(f"Rejected invalid path: {rel_path}")
            continue
        full_path = (brain / rel_path).resolve()
        if not str(full_path).startswith(str(brain.resolve())):
            stats["errors"].append(f"Rejected path traversal: {rel_path}")
            continue

        try:
            if op_type == "create":
                content = op.get("content", "")
                if not content:
                    stats["errors"].append(f"Empty content for create: {rel_path}")
                    continue
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")
                stats["created"] += 1

            elif op_type == "update":
                content = op.get("content", "")
                if not content:
                    stats["errors"].append(f"Empty content for update: {rel_path}")
                    continue
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")
                stats["updated"] += 1

            elif op_type == "archive":
                if not full_path.exists():
                    stats["errors"].append(f"Archive target not found: {rel_path}")
                    continue
                archive_path = brain / "archive" / rel_path
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                # Read original, prepend archive metadata
                original = full_path.read_text(encoding="utf-8")
                reason = op.get("reason", "unknown")
                now = datetime.now(timezone.utc).isoformat()
                if original.startswith("---"):
                    # Insert archive fields into existing frontmatter
                    parts = original.split("---", 2)
                    if len(parts) >= 3:
                        original = (
                            f"---\narchived_at: {now}\n"
                            f"archive_reason: {reason}\n"
                            f"{parts[1]}---{parts[2]}"
                        )
                else:
                    original = (
                        f"---\narchived_at: {now}\n"
                        f"archive_reason: {reason}\n---\n\n{original}"
                    )
                archive_path.write_text(original, encoding="utf-8")
                full_path.unlink()
                stats["archived"] += 1

            else:
                stats["errors"].append(f"Unknown operation type: {op_type}")

        except Exception as exc:
            stats["errors"].append(f"{op_type} failed for {rel_path}: {exc}")
            logger.warning("Brain apply %s failed for %s: %s", op_type, rel_path, exc)

    # Regenerate index.md
    try:
        _regenerate_index(brain)
    except Exception as exc:
        stats["errors"].append(f"Index regeneration failed: {exc}")

    # Append to log.md
    try:
        _append_log(brain, summary, stats)
    except Exception as exc:
        logger.debug("Log append failed: %s", exc)

    return stats


def _regenerate_index(brain: Path) -> None:
    """Rebuild data/brain/index.md from the directory listing."""
    sections: list[str] = ["# Brain Index\n"]

    for subdir_name, label in [
        ("entities", "Entities"),
        ("concepts", "Concepts"),
        ("topics", "Topics"),
        ("conversations", "Conversations"),
        ("synthesis", "Synthesis"),
    ]:
        subdir = brain / subdir_name
        if not subdir.exists():
            continue
        files = sorted(subdir.glob("*.md"))
        if not files:
            continue
        sections.append(f"\n## {label} ({len(files)})\n")
        for f in files:
            name = f.stem.replace("-", " ").title()
            sections.append(f"- [{name}]({subdir_name}/{f.name})")

    (brain / "index.md").write_text("\n".join(sections) + "\n", encoding="utf-8")


def _append_log(brain: Path, summary: str, stats: dict) -> None:
    """Append a compilation entry to data/brain/log.md."""
    now = datetime.now(timezone.utc).isoformat()
    entry = (
        f"\n## {now} — Brain compilation\n"
        f"{summary}\n"
        f"Created: {stats['created']}, Updated: {stats['updated']}, "
        f"Archived: {stats['archived']}"
    )
    if stats["errors"]:
        entry += f", Errors: {len(stats['errors'])}"
    entry += "\n\n---\n"

    log_path = brain / "log.md"
    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        log_path.write_text(existing + entry, encoding="utf-8")
    else:
        log_path.write_text(f"# Brain Compilation Log\n{entry}", encoding="utf-8")
