"""Unified file storage layer.

All file I/O in the system goes through this module. No other code should
hardcode data/ paths or construct file paths from artifact IDs.

Directory layout:
    data/
        odigos.db           -- SQLite database
        files/              -- all user-visible files (uploads, generated, processed)
        files/plans/        -- plan step result files
        artifacts/          -- agent-created text artifacts (legacy, still supported)
        agent/              -- personality/routing markdown sections
        prompts/            -- custom LLM prompt overrides
        notebooks/          -- notebook backup files (not served)
        conversations/      -- conversation export files (not served)
        kanban/             -- kanban export files (not served)
        user/               -- user data export files (not served)
        plugins/            -- event-hook plugins
        vapid_keys.json     -- web push VAPID keypair
"""
from __future__ import annotations

import os
from pathlib import Path

# Base data directory -- everything is relative to this
DATA_DIR = Path("data")

# Primary file storage -- uploads, generated images, processed files
FILES_DIR = DATA_DIR / "files"

# Plan step result files
PLANS_DIR = FILES_DIR / "plans"

# Agent-created text artifacts (CSV, markdown, JSON, etc.)
ARTIFACTS_DIR = DATA_DIR / "artifacts"

# Agent personality and routing sections
AGENT_DIR = DATA_DIR / "agent"

# Custom LLM prompt overrides
PROMPTS_DIR = DATA_DIR / "prompts"

# Backup-only directories (not served via API)
NOTEBOOKS_DIR = DATA_DIR / "notebooks"
CONVERSATIONS_DIR = DATA_DIR / "conversations"
KANBAN_DIR = DATA_DIR / "kanban"
USER_DIR = DATA_DIR / "user"

# Plugins
PLUGINS_DIR = DATA_DIR / "plugins"

# VAPID keys
VAPID_KEYS_PATH = DATA_DIR / "vapid_keys.json"

# Legacy upload directory (read-only fallback for pre-consolidation installs)
_LEGACY_UPLOADS_DIR = DATA_DIR / "uploads"


def ensure_dirs() -> None:
    """Create all required directories. Called once at startup."""
    for d in [FILES_DIR, PLANS_DIR, ARTIFACTS_DIR, AGENT_DIR, PROMPTS_DIR,
              NOTEBOOKS_DIR, PLUGINS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def resolve_artifact_path(
    artifact_id: str,
    filename: str,
    file_path: str | None = None,
) -> Path | None:
    """Find an artifact file on disk. Returns the resolved Path or None.

    Checks in order:
    1. Explicit file_path from DB (if stored)
    2. data/artifacts/{id}/{filename} (text artifacts from create_artifact tool)
    3. data/files/{id}_{anything} (uploads with ID prefix)
    4. data/files/{filename} (generated images by bare filename)
    5. data/uploads/{id}_{anything} (legacy pre-consolidation uploads)
    """
    # 1. Explicit path from DB
    if file_path:
        p = Path(file_path)
        if p.exists():
            return p

    # 2. Artifact subdirectory
    p = ARTIFACTS_DIR / artifact_id / filename
    if p.exists():
        return p

    # 3. Files dir with ID prefix
    import glob as globmod
    for candidate in FILES_DIR.glob(f"{globmod.escape(artifact_id)}_*"):
        return candidate

    # 4. Files dir by bare filename
    p = FILES_DIR / filename
    if p.exists():
        return p

    # 5. Legacy uploads
    if _LEGACY_UPLOADS_DIR.exists():
        for candidate in _LEGACY_UPLOADS_DIR.glob(f"{globmod.escape(artifact_id)}_*"):
            return candidate

    return None


def write_upload(file_id: str, filename: str, content: bytes) -> Path:
    """Write an uploaded file to the canonical location. Returns the full path."""
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    dest = FILES_DIR / f"{file_id}_{safe_name}"
    dest.write_bytes(content)
    return dest


def write_artifact(artifact_id: str, filename: str, content: str) -> Path:
    """Write a text artifact to its subdirectory. Returns the full path."""
    artifact_dir = ARTIFACTS_DIR / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    dest = artifact_dir / filename
    dest.write_text(content)
    return dest


def write_plan_result(plan_id: str, step_num: str, content: str) -> str:
    """Write a plan step result file. Returns the relative path string."""
    plan_dir = PLANS_DIR / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    safe_step = step_num.replace(".", "_")
    filename = f"step_{safe_step}.md"
    filepath = plan_dir / filename
    filepath.write_text(content)
    return str(filepath)


def read_plan_result(path: str) -> str | None:
    """Read a filed plan step result. Returns None if missing."""
    p = Path(path)
    if p.exists() and p.is_file():
        return p.read_text()
    return None
