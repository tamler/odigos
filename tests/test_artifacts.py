import pytest
from pathlib import Path

from odigos.db import Database
from odigos.tools.artifact import CreateArtifactTool, ARTIFACTS_DIR


@pytest.fixture
async def db(tmp_db_path: str) -> Database:
    database = Database(tmp_db_path, migrations_dir="migrations")
    await database.initialize()
    yield database
    await database.close()


class TestCreateArtifactTool:
    async def test_create_csv(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr("odigos.tools.artifact.ARTIFACTS_DIR", tmp_path)
        tool = CreateArtifactTool(db=db)
        result = await tool.execute({
            "filename": "report.csv",
            "content": "name,age\nAlice,30\nBob,25",
            "_conversation_id": "conv-1",
        })
        assert result.success
        assert "report.csv" in result.data
        assert result.side_effect is not None
        assert result.side_effect["artifact"]["filename"] == "report.csv"
        assert result.side_effect["artifact"]["content_type"] == "text/csv"
        assert "/download" in result.side_effect["artifact"]["download_url"]

        # Verify file on disk
        artifact_id = result.side_effect["artifact"]["id"]
        file_path = tmp_path / artifact_id / "report.csv"
        assert file_path.exists()
        assert file_path.read_text() == "name,age\nAlice,30\nBob,25"

    async def test_create_json(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr("odigos.tools.artifact.ARTIFACTS_DIR", tmp_path)
        tool = CreateArtifactTool(db=db)
        result = await tool.execute({
            "filename": "data.json",
            "content": '{"key": "value"}',
            "_conversation_id": "conv-1",
        })
        assert result.success
        assert result.side_effect["artifact"]["content_type"] == "application/json"

    async def test_create_markdown(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr("odigos.tools.artifact.ARTIFACTS_DIR", tmp_path)
        tool = CreateArtifactTool(db=db)
        result = await tool.execute({
            "filename": "notes.md",
            "content": "# My Notes\n\nSome content here.",
            "_conversation_id": "conv-1",
        })
        assert result.success
        assert result.side_effect["artifact"]["content_type"] == "text/markdown"

    async def test_registered_in_database(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr("odigos.tools.artifact.ARTIFACTS_DIR", tmp_path)
        tool = CreateArtifactTool(db=db)
        result = await tool.execute({
            "filename": "test.txt",
            "content": "hello",
            "_conversation_id": "conv-1",
        })
        artifact_id = result.side_effect["artifact"]["id"]
        row = await db.fetch_one("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
        assert row is not None
        assert row["filename"] == "test.txt"
        assert row["conversation_id"] == "conv-1"
        assert row["file_size"] == 5

    async def test_empty_filename_fails(self, db):
        tool = CreateArtifactTool(db=db)
        result = await tool.execute({"filename": "", "content": "data"})
        assert not result.success

    async def test_path_traversal_blocked(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr("odigos.tools.artifact.ARTIFACTS_DIR", tmp_path)
        tool = CreateArtifactTool(db=db)
        result = await tool.execute({
            "filename": "../../../etc/passwd",
            "content": "malicious",
        })
        assert result.success  # filename gets sanitized to just "passwd"
        assert result.side_effect["artifact"]["filename"] == "passwd"

    async def test_html_artifact(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr("odigos.tools.artifact.ARTIFACTS_DIR", tmp_path)
        tool = CreateArtifactTool(db=db)
        result = await tool.execute({
            "filename": "chart.html",
            "content": "<html><body><h1>Chart</h1></body></html>",
        })
        assert result.success
        assert result.side_effect["artifact"]["content_type"] == "text/html"

    async def test_docx_artifact(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr("odigos.tools.artifact.ARTIFACTS_DIR", tmp_path)
        tool = CreateArtifactTool(db=db)
        result = await tool.execute({
            "filename": "report.docx",
            "content": "# Quarterly Report\n\n## Summary\n\nRevenue was strong.\n\n- Item one\n- Item two",
        })
        assert result.success
        assert result.side_effect["artifact"]["content_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        # Verify the file is a valid DOCX
        artifact_id = result.side_effect["artifact"]["id"]
        file_path = tmp_path / artifact_id / "report.docx"
        assert file_path.exists()
        assert file_path.stat().st_size > 0
        # Verify it's a valid zip (DOCX is a zip)
        import zipfile
        assert zipfile.is_zipfile(file_path)
