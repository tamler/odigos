"""Conversation list, detail, and messages API endpoints."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from odigos.api.deps import get_db, require_api_key
from odigos.db import Database


class ConversationUpdate(BaseModel):
    title: str | None = None

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_api_key)],
)


@router.get("/conversations/{conversation_id:path}/messages")
async def get_conversation_messages(
    conversation_id: str,
    db: Database = Depends(get_db),
):
    """Get all messages for a conversation, ordered by timestamp ascending."""
    conversation = await db.fetch_one(
        "SELECT id FROM conversations WHERE id = ?",
        (conversation_id,),
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await db.fetch_all(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
        (conversation_id,),
    )
    return {"messages": messages}


@router.get("/conversations/{conversation_id:path}")
async def get_conversation(
    conversation_id: str,
    db: Database = Depends(get_db),
):
    """Get a single conversation by ID."""
    conversation = await db.fetch_one(
        "SELECT * FROM conversations WHERE id = ?",
        (conversation_id,),
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("/conversations")
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
):
    """List conversations with pagination, ordered by last_message_at descending."""
    total_row = await db.fetch_one(
        "SELECT COUNT(*) AS total FROM conversations WHERE archived = 0 OR archived IS NULL"
    )
    total = total_row["total"] if total_row else 0

    conversations = await db.fetch_all(
        "SELECT * FROM conversations WHERE archived = 0 OR archived IS NULL "
        "ORDER BY last_message_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    return {"conversations": conversations, "total": total}


@router.patch("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    update: ConversationUpdate,
    db: Database = Depends(get_db),
):
    """Rename a conversation."""
    conversation = await db.fetch_one(
        "SELECT id FROM conversations WHERE id = ?",
        (conversation_id,),
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if update.title is not None:
        await db.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (update.title, conversation_id),
        )
    return {"status": "ok"}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: Database = Depends(get_db),
):
    """Archive a conversation (soft delete)."""
    conversation = await db.fetch_one(
        "SELECT id FROM conversations WHERE id = ?",
        (conversation_id,),
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await db.execute(
        "UPDATE conversations SET archived = 1 WHERE id = ?",
        (conversation_id,),
    )
    return {"status": "ok"}


async def _export_markdown(db: Database, conversation_id: str) -> str | None:
    """Export a conversation as markdown."""
    conv = await db.fetch_one(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    )
    if not conv:
        return None

    title = conv.get("title") or conv["id"]
    messages = await db.fetch_all(
        "SELECT role, content, timestamp FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
        (conversation_id,),
    )

    lines = [f"# {title}\n"]
    for msg in messages:
        ts = msg.get("timestamp", "")
        role = msg["role"].capitalize()
        lines.append(f"**{role}** ({ts}):\n{msg['content']}\n")

    return "\n".join(lines)


async def _export_json(db: Database, conversation_id: str) -> str | None:
    """Export a conversation as JSON."""
    conv = await db.fetch_one(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    )
    if not conv:
        return None

    messages = await db.fetch_all(
        "SELECT id, role, content, timestamp FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
        (conversation_id,),
    )

    return json.dumps({
        "conversation_id": conversation_id,
        "title": conv.get("title") or conv["id"],
        "messages": messages,
    }, indent=2, default=str)


@router.get("/conversations/{conversation_id:path}/export")
async def export_conversation(
    conversation_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    db: Database = Depends(get_db),
):
    """Export a conversation as markdown or JSON."""
    if format == "json":
        result = await _export_json(db, conversation_id)
        media_type = "application/json"
        filename = f"{conversation_id}.json"
    else:
        result = await _export_markdown(db, conversation_id)
        media_type = "text/markdown"
        filename = f"{conversation_id}.md"

    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return PlainTextResponse(
        content=result,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
