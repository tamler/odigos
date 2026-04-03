"""Tests for simplified GenerateMusicTool (single tool, no draft step)."""
import pytest
from unittest.mock import AsyncMock, patch
from odigos.tools.music_gen import GenerateMusicTool


@pytest.fixture
def tool(tmp_path):
    return GenerateMusicTool(
        api_key="test-key",
        provider="suno",
        task_type="suno_music",
        model="V5",
        max_poll_seconds=10,
        output_dir=str(tmp_path),
        db=None,
    )


class TestGenerateMusicParams:
    @pytest.mark.asyncio
    async def test_requires_prompt(self, tool):
        result = await tool.execute({"prompt": ""})
        assert not result.success
        assert "prompt" in result.error.lower()

    def test_tool_name(self, tool):
        assert tool.name == "generate_music"

    def test_no_artifact_id_param(self, tool):
        """The old submit_music required artifact_id. The new tool should not."""
        props = tool.parameters_schema["properties"]
        assert "artifact_id" not in props
        assert "prompt" in props

    def test_has_style_and_title_params(self, tool):
        props = tool.parameters_schema["properties"]
        assert "style" in props
        assert "title" in props
        assert "instrumental" in props
        assert "vocal_gender" in props


class TestVocalGenderMapping:
    def test_male_maps_to_m(self):
        assert GenerateMusicTool._map_vocal_gender("male") == "m"

    def test_female_maps_to_f(self):
        assert GenerateMusicTool._map_vocal_gender("female") == "f"

    def test_m_passes_through(self):
        assert GenerateMusicTool._map_vocal_gender("m") == "m"

    def test_empty_stays_empty(self):
        assert GenerateMusicTool._map_vocal_gender("") == ""


class TestExtractTracks:
    def test_dict_with_sunoData(self):
        response = {"sunoData": [{"audioUrl": "http://example.com/a.mp3", "title": "Song"}]}
        tracks = GenerateMusicTool._extract_tracks(response)
        assert len(tracks) == 1
        assert tracks[0]["audioUrl"] == "http://example.com/a.mp3"

    def test_dict_with_arbitrary_key(self):
        """Provider-agnostic: finds tracks under any key."""
        response = {"udioTracks": [{"audioUrl": "http://example.com/b.mp3"}]}
        tracks = GenerateMusicTool._extract_tracks(response)
        assert len(tracks) == 1

    def test_direct_list(self):
        response = [{"audioUrl": "http://example.com/c.mp3"}]
        tracks = GenerateMusicTool._extract_tracks(response)
        assert len(tracks) == 1

    def test_empty_response(self):
        assert GenerateMusicTool._extract_tracks({}) == []
        assert GenerateMusicTool._extract_tracks([]) == []
        assert GenerateMusicTool._extract_tracks("unexpected") == []
