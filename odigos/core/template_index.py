"""AgentTemplateIndex: dynamic index of agent templates from a GitHub repo.

Fetches the repo tree on demand, caches templates in SQLite, and provides
fuzzy matching to find the best template for a given role/specialty.

The repo URL is configurable via config.yaml (templates.repo_url).
Default: https://github.com/msitarzewski/agency-agents
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from odigos.db import Database

logger = logging.getLogger(__name__)

_DEFAULT_REPO_URL = "https://github.com/msitarzewski/agency-agents"
_DEFAULT_BRANCH = "main"
_DEFAULT_CACHE_TTL_DAYS = 7

# Known non-agent directories to exclude when scanning any repo tree.
_KNOWN_NON_AGENT_DIRS = {
    ".github", "examples", "scripts",
}


def _parse_repo_url(url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub URL."""
    parsed = urlparse(url.rstrip("/"))
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    raise ValueError(f"Cannot parse GitHub repo from URL: {url}")


def _parse_agent_name(filename: str) -> str:
    """Convert 'engineering-backend-architect.md' to 'backend architect'."""
    name = filename.removesuffix(".md")
    # Remove division prefix (e.g. 'engineering-' from 'engineering-backend-architect')
    parts = name.split("-", 1)
    if len(parts) > 1:
        return parts[1].replace("-", " ")
    return name.replace("-", " ")


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase keyword tokens."""
    return set(re.findall(r"[a-z]+", text.lower()))


class AgentTemplateIndex:
    """Maintains a searchable index of agent templates from a GitHub repo."""

    def __init__(
        self,
        db: Database,
        repo_url: str = _DEFAULT_REPO_URL,
        cache_ttl_days: int = _DEFAULT_CACHE_TTL_DAYS,
    ) -> None:
        self.db = db
        self.repo_url = repo_url
        self._cache_ttl_seconds = cache_ttl_days * 24 * 3600
        self._http = httpx.AsyncClient(timeout=15.0)
        self._index_refreshed_at: datetime | None = None

        owner, repo = _parse_repo_url(repo_url)
        self._tree_url = (
            f"https://api.github.com/repos/{owner}/{repo}"
            f"/git/trees/{_DEFAULT_BRANCH}?recursive=1"
        )
        self._raw_base = (
            f"https://raw.githubusercontent.com/{owner}/{repo}/{_DEFAULT_BRANCH}"
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def refresh_index(self, force: bool = False) -> int:
        """Fetch the repo tree from GitHub and update the index in SQLite.

        Returns the number of templates indexed.
        Skips if the index was refreshed within cache_ttl unless force=True.
        """
        if not force and self._index_refreshed_at:
            age = (datetime.now(timezone.utc) - self._index_refreshed_at).total_seconds()
            if age < self._cache_ttl_seconds:
                return 0

        try:
            resp = await self._http.get(self._tree_url)
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.warning("Failed to fetch repo tree from %s", self.repo_url, exc_info=True)
            return 0

        tree = resp.json().get("tree", [])
        count = 0
        indexed_paths: set[str] = set()

        for item in tree:
            if item.get("type") != "blob":
                continue
            path = item["path"]
            if not path.endswith(".md"):
                continue
            parts = path.split("/")
            if len(parts) < 2:
                continue

            # Skip known non-agent directories
            division = parts[0]
            if division in _KNOWN_NON_AGENT_DIRS:
                continue

            filename = parts[-1]
            name = _parse_agent_name(filename)
            indexed_paths.add(path)

            # Upsert into index
            existing = await self.db.fetch_one(
                "SELECT id FROM agent_templates WHERE github_path = ?",
                (path,),
            )
            if existing:
                await self.db.execute(
                    "UPDATE agent_templates SET name = ?, division = ?, updated_at = datetime('now') "
                    "WHERE github_path = ?",
                    (name, division, path),
                )
            else:
                await self.db.execute(
                    "INSERT INTO agent_templates (name, division, github_path) VALUES (?, ?, ?)",
                    (name, division, path),
                )
            count += 1

        # Remove templates that no longer exist in the repo (skip custom ones)
        existing_rows = await self.db.fetch_all("SELECT github_path FROM agent_templates")
        for row in existing_rows:
            if row["github_path"].startswith("custom:"):
                continue
            if row["github_path"] not in indexed_paths:
                await self.db.execute(
                    "DELETE FROM agent_templates WHERE github_path = ?",
                    (row["github_path"],),
                )

        self._index_refreshed_at = datetime.now(timezone.utc)
        logger.info("Agent template index refreshed: %d templates from %s", count, self.repo_url)
        return count

    async def match_template(
        self,
        role: str,
        specialty: str | None = None,
    ) -> dict | None:
        """Find the best matching template for a role/specialty.

        Returns the template row dict or None if no reasonable match.
        Uses keyword overlap scoring against template names and divisions.
        """
        await self.refresh_index()

        templates = await self.db.fetch_all(
            "SELECT id, name, division, github_path FROM agent_templates"
        )
        if not templates:
            return None

        query = f"{role} {specialty or ''}".strip()
        query_tokens = _tokenize(query)
        if not query_tokens:
            return None

        best = None
        best_score = 0

        for t in templates:
            candidate_tokens = _tokenize(f"{t['name']} {t['division']}")
            overlap = len(query_tokens & candidate_tokens)
            if overlap > best_score:
                best_score = overlap
                best = t

        if best_score == 0:
            return None

        return best

    async def fetch_template(self, github_path: str) -> str | None:
        """Fetch template content, using cache if fresh enough.

        Custom templates (github_path starts with 'custom:') are always
        served from cache. GitHub-sourced templates use TTL-based caching.

        Returns the raw Markdown content or None on failure.
        """
        # Custom templates are always local
        if github_path.startswith("custom:"):
            row = await self.db.fetch_one(
                "SELECT cached_content FROM agent_templates WHERE github_path = ?",
                (github_path,),
            )
            return row["cached_content"] if row and row["cached_content"] else None

        # Check cache first
        row = await self.db.fetch_one(
            "SELECT cached_content, cached_at FROM agent_templates WHERE github_path = ?",
            (github_path,),
        )
        if row and row["cached_content"] and row["cached_at"]:
            cached_at = datetime.fromisoformat(row["cached_at"])
            age = (datetime.now(timezone.utc) - cached_at.replace(tzinfo=timezone.utc)).total_seconds()
            if age < self._cache_ttl_seconds:
                return row["cached_content"]

        # Fetch from GitHub
        url = f"{self._raw_base}/{github_path}"
        try:
            resp = await self._http.get(url)
            resp.raise_for_status()
            content = resp.text
        except httpx.HTTPError:
            logger.warning("Failed to fetch template: %s", github_path, exc_info=True)
            # Return stale cache if available
            if row and row["cached_content"]:
                return row["cached_content"]
            return None

        # Update cache
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "UPDATE agent_templates SET cached_content = ?, cached_at = ? WHERE github_path = ?",
            (content, now, github_path),
        )

        return content

    async def create_custom_template(
        self,
        name: str,
        content: str,
        division: str = "custom",
    ) -> int:
        """Create a custom agent template stored locally.

        Custom templates use a 'custom:' prefix in github_path to distinguish
        them from repo-sourced templates. They are never pruned during index
        refresh and never fetched from GitHub.
        """
        path = f"custom:{division}/{name.lower().replace(' ', '-')}.md"
        now = datetime.now(timezone.utc).isoformat()
        existing = await self.db.fetch_one(
            "SELECT id FROM agent_templates WHERE github_path = ?", (path,)
        )
        if existing:
            await self.db.execute(
                "UPDATE agent_templates SET name = ?, cached_content = ?, cached_at = ?, "
                "updated_at = datetime('now') WHERE github_path = ?",
                (name, content, now, path),
            )
            return existing["id"]

        row_id = await self.db.execute_returning_lastrowid(
            "INSERT INTO agent_templates (name, division, github_path, cached_content, cached_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, division, path, content, now),
        )
        logger.info("Custom template created: %s (division=%s)", name, division)
        return row_id

    async def delete_custom_template(self, template_id: int) -> bool:
        """Delete a custom template by ID. Only custom templates can be deleted."""
        row = await self.db.fetch_one(
            "SELECT github_path FROM agent_templates WHERE id = ?", (template_id,),
        )
        if not row or not row["github_path"].startswith("custom:"):
            return False
        await self.db.execute("DELETE FROM agent_templates WHERE id = ?", (template_id,))
        return True

    async def list_templates(self, division: str | None = None) -> list[dict]:
        """List all indexed templates, optionally filtered by division."""
        if division:
            return await self.db.fetch_all(
                "SELECT id, name, division, github_path FROM agent_templates WHERE division = ? ORDER BY name",
                (division,),
            )
        return await self.db.fetch_all(
            "SELECT id, name, division, github_path FROM agent_templates ORDER BY division, name"
        )
