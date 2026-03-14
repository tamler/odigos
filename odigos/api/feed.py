"""RSS feed publisher endpoint.

Serves GET /feed.xml with entries from the feed_entries table.
Auth: public if feed.public is true, otherwise requires a valid
card key (subscribe or connect) or the global API key.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from odigos.api.deps import get_db, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/feed.xml")
async def get_feed(
    request: Request,
    settings=Depends(get_settings),
    db=Depends(get_db),
):
    """Serve RSS 2.0 feed of published entries."""
    if not settings.feed.enabled:
        raise HTTPException(status_code=404, detail="Feed is disabled")

    # Auth check for private feeds
    if not settings.feed.public:
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(status_code=401, detail="Feed requires authentication")

        parts = auth_header.split(" ", 1)
        token = parts[1] if len(parts) == 2 and parts[0] == "Bearer" else ""

        # Accept global API key
        if token == settings.api_key:
            pass
        else:
            # Accept card key
            card_manager = getattr(request.app.state, "card_manager", None)
            if not card_manager:
                raise HTTPException(status_code=401, detail="No card manager available")
            card = await card_manager.validate_card_key(token)
            if not card:
                raise HTTPException(status_code=403, detail="Invalid card key")

    # Fetch entries
    entries = await db.fetch_all(
        "SELECT * FROM feed_entries ORDER BY created_at DESC LIMIT ?",
        (settings.feed.max_entries,),
    )

    # Build RSS XML
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = f"{settings.agent.name} Feed"
    SubElement(channel, "description").text = f"Published updates from {settings.agent.name}"
    SubElement(channel, "lastBuildDate").text = datetime.now(timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )

    for entry in entries:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = entry["title"]
        SubElement(item, "description").text = entry["content"]
        SubElement(item, "guid", isPermaLink="false").text = entry["id"]
        SubElement(item, "pubDate").text = entry["created_at"]
        if entry.get("category"):
            SubElement(item, "category").text = entry["category"]

    xml_bytes = tostring(rss, encoding="unicode", xml_declaration=False)
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes

    return Response(content=xml_str, media_type="application/rss+xml")
