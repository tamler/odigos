"""System diagnostic endpoint -- checks all subsystems are healthy."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends

from odigos.api.deps import get_agent_service, get_db, get_settings, require_auth
from odigos.storage import FILES_DIR, DATA_DIR

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_auth)],
)


@router.get("/diagnostic")
async def run_diagnostic(
    db=Depends(get_db),
    agent_service=Depends(get_agent_service),
    settings=Depends(get_settings),
):
    """Run a full system diagnostic. Returns status of all subsystems."""
    checks = []

    # 1. Database
    try:
        row = await db.fetch_one("SELECT COUNT(*) as cnt FROM conversations")
        checks.append({
            "name": "Database",
            "status": "ok",
            "detail": f"{row['cnt']} conversations",
        })
    except Exception as e:
        checks.append({"name": "Database", "status": "error", "detail": str(e)})

    # 2. LLM Provider
    try:
        provider = agent_service.agent.executor.provider
        model = getattr(provider, "default_model", "unknown")
        checks.append({
            "name": "LLM Provider",
            "status": "ok",
            "detail": f"Model: {model}",
        })
    except Exception as e:
        checks.append({"name": "LLM Provider", "status": "error", "detail": str(e)})

    # 3. Embedding Model
    try:
        from sentence_transformers import SentenceTransformer
        checks.append({
            "name": "Embedding Model",
            "status": "ok",
            "detail": "sentence-transformers loaded",
        })
    except Exception as e:
        checks.append({"name": "Embedding Model", "status": "error", "detail": str(e)})

    # 4. Disk Space
    try:
        total_bytes = sum(
            f.stat().st_size for f in DATA_DIR.rglob("*")
            if f.is_file() and not f.is_symlink()
        )
        total_mb = total_bytes / (1024 * 1024)
        checks.append({
            "name": "Disk Usage",
            "status": "ok",
            "detail": f"{total_mb:.1f} MB in data/",
        })
    except Exception as e:
        checks.append({"name": "Disk Usage", "status": "error", "detail": str(e)})

    # 5. Tool Count
    try:
        tools = agent_service.agent.executor.tool_registry
        count = len(tools.list()) if tools else 0
        checks.append({
            "name": "Tools",
            "status": "ok",
            "detail": f"{count} tools registered",
        })
    except Exception as e:
        checks.append({"name": "Tools", "status": "error", "detail": str(e)})

    # 6. TextBlob NLP
    try:
        from textblob import TextBlob
        TextBlob("test").words
        checks.append({"name": "TextBlob NLP", "status": "ok", "detail": "Corpus available"})
    except Exception as e:
        checks.append({"name": "TextBlob NLP", "status": "error", "detail": str(e)})

    # 7. Voice (STT/TTS)
    try:
        stt = settings.voice.stt_provider
        tts = settings.voice.tts_provider
        checks.append({
            "name": "Voice",
            "status": "ok" if stt != "disabled" else "disabled",
            "detail": f"STT: {stt}, TTS: {tts}",
        })
    except Exception as e:
        checks.append({"name": "Voice", "status": "error", "detail": str(e)})

    # 8. File Storage
    try:
        file_count = sum(1 for f in FILES_DIR.iterdir() if f.is_file()) if FILES_DIR.exists() else 0
        checks.append({
            "name": "File Storage",
            "status": "ok",
            "detail": f"{file_count} files in data/files/",
        })
    except Exception as e:
        checks.append({"name": "File Storage", "status": "error", "detail": str(e)})

    # 9. Heartbeat
    try:
        hb = agent_service.agent.heartbeat
        paused = getattr(hb, "paused", False) if hb else None
        if hb is None:
            checks.append({"name": "Heartbeat", "status": "disabled", "detail": "Not running"})
        else:
            checks.append({
                "name": "Heartbeat",
                "status": "ok" if not paused else "paused",
                "detail": f"Interval: {hb._interval}s, paused: {paused}",
            })
    except Exception as e:
        checks.append({"name": "Heartbeat", "status": "error", "detail": str(e)})

    all_ok = all(c["status"] in ("ok", "disabled") for c in checks)

    return {
        "status": "healthy" if all_ok else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
