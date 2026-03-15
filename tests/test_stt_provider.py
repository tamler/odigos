"""Tests for the MoonshineSTT provider."""
from unittest.mock import MagicMock, patch


class TestMoonshineSTT:
    def test_ensure_wav_passthrough(self):
        """WAV files are returned as-is."""
        from plugins.stt.provider import MoonshineSTT

        stt = MoonshineSTT(model_size="small", language="en")
        assert stt._ensure_wav("/tmp/test.wav") == "/tmp/test.wav"
        assert stt._ensure_wav("/tmp/TEST.WAV") == "/tmp/TEST.WAV"

    def test_ensure_wav_converts_mp3(self):
        """Non-WAV files trigger ffmpeg conversion."""
        from plugins.stt.provider import MoonshineSTT

        stt = MoonshineSTT(model_size="small", language="en")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = stt._ensure_wav("/tmp/test.mp3")
            assert result.endswith(".wav")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "ffmpeg"
            assert "/tmp/test.mp3" in args

    def test_lazy_loading_not_loaded_initially(self):
        """Model is not loaded until _ensure_loaded() is called."""
        from plugins.stt.provider import MoonshineSTT

        stt = MoonshineSTT(model_size="small", language="en")
        assert stt._transcriber is None

    def test_model_size_stored(self):
        """Model size and language are stored correctly."""
        from plugins.stt.provider import MoonshineSTT

        stt = MoonshineSTT(model_size="tiny", language="en")
        assert stt._model_size == "tiny"
        assert stt._language == "en"

        stt2 = MoonshineSTT(model_size="medium", language="en")
        assert stt2._model_size == "medium"
