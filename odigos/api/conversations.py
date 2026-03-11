"""Conversation list, detail, and messages API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
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
