"""Tests for odigos.memory.source_archiver."""
import pytest

from odigos.memory.source_archiver import archive_source


@pytest.mark.asyncio
async def test_archive_creates_file(tmp_path):
    content = "# Hello World\n\nSome article content."
    url = "https://example.com/hello"
    title = "Hello World"

    result = await archive_source(content, title, url=url, sources_dir=tmp_path)

    assert result is not None
    filepath = tmp_path / result.split("/")[-1]
    assert filepath.exists()

    text = filepath.read_text(encoding="utf-8")
    assert "url: https://example.com/hello" in text
    assert "title: Hello World" in text
    assert "scraped_at:" in text
    assert "content_type: article" in text
    # sha256 is present
    assert "sha256:" in text
    # body content after frontmatter
    assert "# Hello World" in text
    assert "Some article content." in text


@pytest.mark.asyncio
async def test_archive_dedup_by_hash(tmp_path):
    content = "Duplicate content here."
    title = "Duplicate"

    first = await archive_source(content, title, sources_dir=tmp_path)
    second = await archive_source(content, title, sources_dir=tmp_path)

    assert first is not None
    assert second is None

    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1


@pytest.mark.asyncio
async def test_archive_sanitizes_filename(tmp_path):
    title = "What's New in Python 3.12!"
    content = "Python release notes."

    result = await archive_source(content, title, sources_dir=tmp_path)

    assert result is not None
    filename = result.split("/")[-1]
    # No special chars, no apostrophes, no exclamation marks
    assert "'" not in filename
    assert "!" not in filename
    # Should contain a clean slug derived from the title
    assert "whats-new-in-python-312" in filename or "what" in filename


@pytest.mark.asyncio
async def test_archive_returns_filepath(tmp_path):
    content = "Some content to archive."
    title = "My Article"

    result = await archive_source(content, title, url="https://example.com/my-article", sources_dir=tmp_path)

    assert result is not None
    from pathlib import Path
    assert Path(result).exists()
    assert Path(result).read_text(encoding="utf-8").startswith("---")
