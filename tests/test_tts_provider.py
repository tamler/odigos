"""Tests for the PocketTTSProvider."""
import os
import numpy as np
from unittest.mock import MagicMock, patch


class TestPocketTTSProvider:
    def test_default_voice(self):
        """Default voice is set correctly."""
        from plugins.tts.provider import PocketTTSProvider

        provider = PocketTTSProvider(default_voice="alba")
        assert provider._default_voice == "alba"

    def test_model_not_loaded_initially(self):
        """Model is not loaded until initialize() is called."""
        from plugins.tts.provider import PocketTTSProvider

        provider = PocketTTSProvider()
        assert provider._model is None

    def test_voice_state_caching(self):
        """Voice states are cached after first load."""
        from plugins.tts.provider import PocketTTSProvider

        provider = PocketTTSProvider()
        provider._model = MagicMock()
        provider._model.get_state_for_audio_prompt.return_value = "fake_state"

        state1 = provider._get_voice_state("alba")
        state2 = provider._get_voice_state("alba")
        assert state1 == state2
        provider._model.get_state_for_audio_prompt.assert_called_once_with("alba")

    def test_generate_audio_returns_path_and_duration(self):
        """generate_audio writes WAV and returns (path, duration_ms)."""
        from plugins.tts.provider import PocketTTSProvider

        provider = PocketTTSProvider()
        provider._model = MagicMock()
        provider._model.sample_rate = 24000

        fake_audio = MagicMock()
        fake_audio.numpy.return_value = np.zeros(24000, dtype=np.float32)
        fake_audio.__len__ = lambda self: 24000
        provider._model.generate_audio.return_value = fake_audio
        provider._voice_states["alba"] = "fake_state"

        with patch("scipy.io.wavfile.write"):
            filepath, duration_ms = provider.generate_audio("hello world")
            assert filepath.startswith("data/audio/")
            assert filepath.endswith(".wav")
            assert duration_ms == 1000
