# TTS & STT Plugins Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add local speech-to-text (Moonshine) and text-to-speech (Pocket-TTS) as optional plugins with both file-based and streaming audio support.

**Architecture:** Two independent plugins (`plugins/stt/`, `plugins/tts/`) following the existing `register(ctx)` pattern. Each plugin registers provider instances and agent tools. A new `odigos/api/audio.py` router provides WebSocket endpoints for streaming audio. Upload endpoint and Telegram channel are modified to detect audio files and auto-transcribe. Config gated via `stt.enabled` / `tts.enabled` in config.yaml.

**Tech Stack:** moonshine-voice (ONNX, CPU), pocket-tts (PyTorch, CPU), scipy (WAV writing), ffmpeg (format conversion subprocess)

---

### Task 1: Add STT/TTS Config Models and Optional Dependencies

**Files:**
- Modify: `/Users/jacob/Projects/odigos/odigos/config.py:100-172`
- Modify: `/Users/jacob/Projects/odigos/pyproject.toml:26-31`

**Step 1: Add config models to config.py**

Add these two Pydantic models after `FeedConfig` (line 104) and add them to `Settings`:

```python
class STTConfig(BaseModel):
    enabled: bool = False
    model: str = "small"       # tiny, small, medium (all streaming-capable)
    language: str = "en"


class TTSConfig(BaseModel):
    enabled: bool = False
    voice: str = "alba"        # alba, marius, javert, jean, fantine, cosette, eponine, azelma
```

In the `Settings` class, add these two fields after `feed`:

```python
    stt: STTConfig = STTConfig()
    tts: TTSConfig = TTSConfig()
```

**Step 2: Add optional dependencies to pyproject.toml**

After the `dev` extras in `[project.optional-dependencies]`, add:

```toml
stt = ["moonshine-voice>=1.0.0"]
tts = ["pocket-tts>=0.1.0", "scipy"]
audio = ["moonshine-voice>=1.0.0", "pocket-tts>=0.1.0", "scipy"]
```

**Step 3: Verify config loads**

Run: `python -c "from odigos.config import load_settings; s = load_settings(); print(s.stt.enabled, s.tts.enabled)"`
Expected: `False False`

**Step 4: Commit**

```bash
git add odigos/config.py pyproject.toml
git commit -m "feat: add STT/TTS config models and optional dependencies"
```

---

### Task 2: STT Provider (MoonshineSTT)

**Files:**
- Create: `/Users/jacob/Projects/odigos/plugins/stt/provider.py`
- Test: `/Users/jacob/Projects/odigos/tests/test_stt_provider.py`

**Step 1: Write the failing test**

Create `/Users/jacob/Projects/odigos/tests/test_stt_provider.py`:

```python
"""Tests for the MoonshineSTT provider."""
import os
import tempfile
import pytest
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

    def test_arch_mapping(self):
        """Model size maps to correct streaming architecture."""
        from plugins.stt.provider import MoonshineSTT

        stt = MoonshineSTT(model_size="tiny", language="en")
        assert stt._model_size == "tiny"

        stt2 = MoonshineSTT(model_size="medium", language="en")
        assert stt2._model_size == "medium"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_stt_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plugins.stt'`

**Step 3: Write the STT provider**

Create `/Users/jacob/Projects/odigos/plugins/stt/provider.py`:

```python
"""Moonshine speech-to-text provider with file and streaming support."""
from __future__ import annotations

import logging
import subprocess
import tempfile

logger = logging.getLogger(__name__)


class MoonshineSTT:
    """Local CPU speech-to-text using Moonshine ONNX models.

    Supports both file transcription and streaming audio chunks.
    Uses streaming-capable model architectures that handle both modes.
    """

    def __init__(self, model_size: str = "small", language: str = "en") -> None:
        self._transcriber = None
        self._model_size = model_size
        self._language = language

    def _ensure_loaded(self) -> None:
        """Load ONNX model on first use. Model stays resident in memory."""
        if self._transcriber is not None:
            return
        from moonshine_voice.transcriber import Transcriber
        from moonshine_voice.moonshine_api import ModelArch
        from moonshine_voice.utils import get_model_path

        arch_map = {
            "tiny": ModelArch.TINY_STREAMING,
            "small": ModelArch.SMALL_STREAMING,
            "medium": ModelArch.MEDIUM_STREAMING,
        }
        arch = arch_map.get(self._model_size, ModelArch.SMALL_STREAMING)
        model_name = f"{self._model_size}-{self._language}"
        model_path = str(get_model_path(model_name))
        self._transcriber = Transcriber(model_path=model_path, model_arch=arch)
        logger.info("Moonshine STT loaded: %s (%s)", model_name, arch)

    def transcribe_file(self, audio_path: str) -> str:
        """Transcribe an audio file to text. Returns full transcript string."""
        self._ensure_loaded()
        wav_path = self._ensure_wav(audio_path)
        from moonshine_voice.utils import load_wav_file

        audio_data, sample_rate = load_wav_file(wav_path)
        transcript = self._transcriber.transcribe_without_streaming(audio_data, sample_rate)
        return " ".join(line.text for line in transcript.lines)

    async def transcribe_stream(self, audio_chunks):
        """Transcribe streaming audio. Yields partial transcript strings.

        Args:
            audio_chunks: async iterator of (audio_data, sample_rate) tuples
        """
        self._ensure_loaded()
        async for chunk_data, _sample_rate in audio_chunks:
            transcript = self._transcriber.transcribe(chunk_data)
            if transcript and transcript.lines:
                yield " ".join(line.text for line in transcript.lines)

    def _ensure_wav(self, path: str) -> str:
        """Convert non-WAV audio to WAV via ffmpeg. Returns WAV path."""
        if path.lower().endswith(".wav"):
            return path
        wav_path = tempfile.mktemp(suffix=".wav")
        subprocess.run(
            ["ffmpeg", "-i", path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
            capture_output=True,
            check=True,
        )
        return wav_path
```

Also create empty `__init__.py` so Python can find the module:

Create `/Users/jacob/Projects/odigos/plugins/stt/__init__.py` (leave empty for now — registration comes in Task 4).

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_stt_provider.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add plugins/stt/provider.py plugins/stt/__init__.py tests/test_stt_provider.py
git commit -m "feat: add MoonshineSTT provider with file and streaming transcription"
```

---

### Task 3: TTS Provider (PocketTTSProvider)

**Files:**
- Create: `/Users/jacob/Projects/odigos/plugins/tts/provider.py`
- Test: `/Users/jacob/Projects/odigos/tests/test_tts_provider.py`

**Step 1: Write the failing test**

Create `/Users/jacob/Projects/odigos/tests/test_tts_provider.py`:

```python
"""Tests for the PocketTTSProvider."""
import os
import pytest
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
        # Called only once due to caching
        provider._model.get_state_for_audio_prompt.assert_called_once_with("alba")

    def test_generate_audio_creates_file(self):
        """generate_audio writes a WAV file and returns path + duration."""
        from plugins.tts.provider import PocketTTSProvider
        import numpy as np

        provider = PocketTTSProvider()
        provider._model = MagicMock()
        provider._model.sample_rate = 24000

        # Mock audio tensor
        fake_audio = MagicMock()
        fake_audio.numpy.return_value = np.zeros(24000, dtype=np.float32)  # 1 second
        fake_audio.__len__ = lambda self: 24000
        provider._model.generate_audio.return_value = fake_audio
        provider._voice_states["alba"] = "fake_state"

        with patch("scipy.io.wavfile.write"):
            filepath, duration_ms = provider.generate_audio("hello world")
            assert filepath.startswith("data/audio/")
            assert filepath.endswith(".wav")
            assert duration_ms == 1000  # 24000 samples / 24000 Hz = 1s
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_tts_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plugins.tts'`

**Step 3: Write the TTS provider**

Create `/Users/jacob/Projects/odigos/plugins/tts/provider.py`:

```python
"""Pocket-TTS text-to-speech provider with file and streaming support."""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)


class PocketTTSProvider:
    """Local CPU text-to-speech using Pocket-TTS PyTorch model.

    Supports complete file generation and chunked streaming (~200ms first chunk).
    Model and voice states are loaded eagerly at initialize() since loading is slow.
    """

    def __init__(self, default_voice: str = "alba") -> None:
        self._model = None
        self._voice_states: dict = {}
        self._default_voice = default_voice

    def initialize(self) -> None:
        """Load model and default voice state. Call once at startup."""
        from pocket_tts import TTSModel

        self._model = TTSModel.load_model()
        self._voice_states[self._default_voice] = (
            self._model.get_state_for_audio_prompt(self._default_voice)
        )
        logger.info("Pocket-TTS loaded with voice: %s", self._default_voice)

    @property
    def sample_rate(self) -> int:
        """Output audio sample rate."""
        return self._model.sample_rate

    def _get_voice_state(self, voice: str):
        """Get or load a voice state, caching for reuse."""
        if voice not in self._voice_states:
            self._voice_states[voice] = self._model.get_state_for_audio_prompt(voice)
        return self._voice_states[voice]

    def generate_audio(self, text: str, voice: str | None = None) -> tuple[str, int]:
        """Generate complete WAV file from text.

        Returns:
            (file_path, duration_ms) tuple
        """
        import scipy.io.wavfile

        voice = voice or self._default_voice
        voice_state = self._get_voice_state(voice)
        audio = self._model.generate_audio(voice_state, text)

        os.makedirs("data/audio", exist_ok=True)
        filename = f"{int(time.time())}_{os.urandom(4).hex()}.wav"
        filepath = os.path.join("data/audio", filename)
        scipy.io.wavfile.write(filepath, self._model.sample_rate, audio.numpy())

        duration_ms = int(len(audio) / self._model.sample_rate * 1000)
        return filepath, duration_ms

    async def generate_stream(self, text: str, voice: str | None = None):
        """Stream audio generation. Yields raw PCM bytes as produced.

        Each chunk is a bytes object of float32 PCM audio at self.sample_rate.
        First chunk arrives in ~200ms.
        """
        voice = voice or self._default_voice
        voice_state = self._get_voice_state(voice)
        for chunk_tensor in self._model.generate_audio_stream(voice_state, text):
            yield chunk_tensor.numpy().tobytes()
```

Also create empty `__init__.py`:

Create `/Users/jacob/Projects/odigos/plugins/tts/__init__.py` (leave empty for now).

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_tts_provider.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add plugins/tts/provider.py plugins/tts/__init__.py tests/test_tts_provider.py
git commit -m "feat: add PocketTTSProvider with file and streaming generation"
```

---

### Task 4: Plugin Registration (STT + TTS)

**Files:**
- Modify: `/Users/jacob/Projects/odigos/plugins/stt/__init__.py`
- Create: `/Users/jacob/Projects/odigos/plugins/stt/plugin.yaml`
- Modify: `/Users/jacob/Projects/odigos/plugins/tts/__init__.py`
- Create: `/Users/jacob/Projects/odigos/plugins/tts/plugin.yaml`
- Test: `/Users/jacob/Projects/odigos/tests/test_plugin_registration.py`

**Step 1: Write the failing test**

Create `/Users/jacob/Projects/odigos/tests/test_plugin_registration.py`:

```python
"""Tests for STT and TTS plugin registration."""
import pytest
from unittest.mock import MagicMock


def _make_ctx(stt_enabled=False, tts_enabled=False):
    """Create a mock PluginContext with configurable STT/TTS settings."""
    from odigos.config import Settings, STTConfig, TTSConfig

    settings = Settings(
        stt=STTConfig(enabled=stt_enabled),
        tts=TTSConfig(enabled=tts_enabled),
    )
    ctx = MagicMock()
    ctx.config = {"settings": settings}
    ctx.register_tool = MagicMock()
    ctx.register_provider = MagicMock()
    return ctx


class TestSTTPluginRegistration:
    def test_stt_disabled_returns_available(self):
        """STT plugin returns 'available' when not enabled."""
        from plugins.stt import register

        ctx = _make_ctx(stt_enabled=False)
        result = register(ctx)
        assert result["status"] == "available"
        ctx.register_tool.assert_not_called()

    def test_stt_enabled_registers_tool_and_provider(self):
        """STT plugin registers tool and provider when enabled."""
        from plugins.stt import register

        ctx = _make_ctx(stt_enabled=True)
        result = register(ctx)
        # Should not return error status
        assert result is None or result.get("status") != "error"
        ctx.register_provider.assert_called_once()
        assert ctx.register_provider.call_args[0][0] == "stt"
        ctx.register_tool.assert_called_once()


class TestTTSPluginRegistration:
    def test_tts_disabled_returns_available(self):
        """TTS plugin returns 'available' when not enabled."""
        from plugins.tts import register

        ctx = _make_ctx(tts_enabled=False)
        result = register(ctx)
        assert result["status"] == "available"
        ctx.register_tool.assert_not_called()

    def test_tts_enabled_registers_tool_and_provider(self):
        """TTS plugin registers tool and provider when enabled."""
        from plugins.tts import register

        ctx = _make_ctx(tts_enabled=True)
        result = register(ctx)
        assert result is None or result.get("status") != "error"
        ctx.register_provider.assert_called_once()
        assert ctx.register_provider.call_args[0][0] == "tts"
        ctx.register_tool.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_plugin_registration.py -v`
Expected: FAIL — `ImportError` or `AttributeError` (register function not defined)

**Step 3: Write STT plugin registration**

Write `/Users/jacob/Projects/odigos/plugins/stt/__init__.py`:

```python
"""STT plugin — speech-to-text via Moonshine (local CPU, ONNX).

Registers the transcribe_audio tool and STT provider when stt.enabled is true.
Requires: pip install moonshine-voice
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.stt.enabled:
        return {"status": "available", "error_message": "STT not enabled in config"}

    try:
        from moonshine_voice.transcriber import Transcriber  # noqa: F401
    except ImportError:
        return {"status": "error", "error_message": "moonshine-voice package not installed. Run: pip install moonshine-voice"}

    from plugins.stt.provider import MoonshineSTT
    from odigos.tools.transcribe import TranscribeAudioTool

    provider = MoonshineSTT(
        model_size=settings.stt.model,
        language=settings.stt.language,
    )
    ctx.register_provider("stt", provider)

    ingester = getattr(ctx.service, "doc_ingester", None) if ctx.service else None
    tool = TranscribeAudioTool(stt_provider=provider, ingester=ingester)
    ctx.register_tool(tool)
    logger.info("STT plugin loaded (model=%s, lang=%s)", settings.stt.model, settings.stt.language)
```

Create `/Users/jacob/Projects/odigos/plugins/stt/plugin.yaml`:

```yaml
id: stt
name: Speech-to-Text (Moonshine)
description: Local CPU speech-to-text transcription via Moonshine ONNX models
category: providers
requires:
  - moonshine-voice
config_keys:
  - stt.enabled
  - stt.model
  - stt.language
```

**Step 4: Write TTS plugin registration**

Write `/Users/jacob/Projects/odigos/plugins/tts/__init__.py`:

```python
"""TTS plugin — text-to-speech via Pocket-TTS (local CPU, PyTorch).

Registers the speak tool and TTS provider when tts.enabled is true.
Requires: pip install pocket-tts scipy
"""
import logging

logger = logging.getLogger(__name__)


def register(ctx):
    settings = ctx.config.get("settings")
    if not settings or not settings.tts.enabled:
        return {"status": "available", "error_message": "TTS not enabled in config"}

    try:
        from pocket_tts import TTSModel  # noqa: F401
    except ImportError:
        return {"status": "error", "error_message": "pocket-tts package not installed. Run: pip install pocket-tts scipy"}

    from plugins.tts.provider import PocketTTSProvider
    from odigos.tools.speak import SpeakTool

    provider = PocketTTSProvider(default_voice=settings.tts.voice)
    # Eager model loading — too slow for first request if deferred
    provider.initialize()
    ctx.register_provider("tts", provider)

    tool = SpeakTool(tts_provider=provider)
    ctx.register_tool(tool)
    logger.info("TTS plugin loaded (voice=%s)", settings.tts.voice)
```

Create `/Users/jacob/Projects/odigos/plugins/tts/plugin.yaml`:

```yaml
id: tts
name: Text-to-Speech (Pocket-TTS)
description: Local CPU text-to-speech generation via Pocket-TTS PyTorch model
category: providers
requires:
  - pocket-tts
  - scipy
config_keys:
  - tts.enabled
  - tts.voice
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/test_plugin_registration.py::TestSTTPluginRegistration::test_stt_disabled_returns_available tests/test_plugin_registration.py::TestTTSPluginRegistration::test_tts_disabled_returns_available -v`
Expected: 2 PASSED (disabled tests pass; enabled tests will fail until tools are created in Tasks 5-6)

**Step 6: Commit**

```bash
git add plugins/stt/__init__.py plugins/stt/plugin.yaml plugins/tts/__init__.py plugins/tts/plugin.yaml tests/test_plugin_registration.py
git commit -m "feat: add STT and TTS plugin registration with config gating"
```

---

### Task 5: transcribe_audio Tool

**Files:**
- Create: `/Users/jacob/Projects/odigos/odigos/tools/transcribe.py`
- Test: `/Users/jacob/Projects/odigos/tests/test_transcribe_tool.py`

**Step 1: Write the failing test**

Create `/Users/jacob/Projects/odigos/tests/test_transcribe_tool.py`:

```python
"""Tests for the transcribe_audio tool."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_transcribe_returns_transcript():
    """Tool transcribes audio file and returns text."""
    from odigos.tools.transcribe import TranscribeAudioTool

    mock_stt = MagicMock()
    mock_stt.transcribe_file.return_value = "Hello world this is a test"

    tool = TranscribeAudioTool(stt_provider=mock_stt)
    result = await tool.execute({"source": "/tmp/test.wav"})

    assert result.success is True
    assert "Hello world this is a test" in result.data
    mock_stt.transcribe_file.assert_called_once()


@pytest.mark.asyncio
async def test_transcribe_missing_source():
    """Tool returns error when no source provided."""
    from odigos.tools.transcribe import TranscribeAudioTool

    tool = TranscribeAudioTool(stt_provider=MagicMock())
    result = await tool.execute({})

    assert result.success is False
    assert "source" in result.error.lower()


@pytest.mark.asyncio
async def test_transcribe_ingests_into_memory():
    """Tool ingests transcript into memory when ingester available."""
    from odigos.tools.transcribe import TranscribeAudioTool

    mock_stt = MagicMock()
    mock_stt.transcribe_file.return_value = "Meeting notes about Q3 budget"

    mock_ingester = AsyncMock()
    mock_ingester.ingest.return_value = "doc-123"

    tool = TranscribeAudioTool(stt_provider=mock_stt, ingester=mock_ingester)
    result = await tool.execute({"source": "/tmp/meeting.wav"})

    assert result.success is True
    mock_ingester.ingest.assert_called_once()
    call_kwargs = mock_ingester.ingest.call_args[1]
    assert "Meeting notes about Q3 budget" in call_kwargs["text"]
    assert "meeting.wav" in call_kwargs["filename"]


@pytest.mark.asyncio
async def test_transcribe_handles_provider_error():
    """Tool returns error when transcription fails."""
    from odigos.tools.transcribe import TranscribeAudioTool

    mock_stt = MagicMock()
    mock_stt.transcribe_file.side_effect = RuntimeError("Model not loaded")

    tool = TranscribeAudioTool(stt_provider=mock_stt)
    result = await tool.execute({"source": "/tmp/test.wav"})

    assert result.success is False
    assert "Model not loaded" in result.error
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_transcribe_tool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odigos.tools.transcribe'`

**Step 3: Write the tool**

Create `/Users/jacob/Projects/odigos/odigos/tools/transcribe.py`:

```python
"""transcribe_audio tool — transcribe audio files via STT provider."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from odigos.memory.ingester import DocumentIngester
    from plugins.stt.provider import MoonshineSTT

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".m4a", ".webm", ".flac", ".opus"}


class TranscribeAudioTool(BaseTool):
    """Transcribe an audio file to text using local STT."""

    name = "transcribe_audio"
    description = (
        "Transcribe an audio file (WAV, MP3, OGG, M4A, FLAC, WebM) to text. "
        "Returns the full transcript. Also ingests it into memory for future recall."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "File path to the audio file to transcribe",
            },
        },
        "required": ["source"],
    }

    def __init__(self, stt_provider: MoonshineSTT, ingester: DocumentIngester | None = None) -> None:
        self.stt = stt_provider
        self.ingester = ingester

    async def execute(self, params: dict) -> ToolResult:
        source = params.get("source")
        if not source:
            return ToolResult(success=False, data="", error="No source audio path provided")

        try:
            transcript = await asyncio.to_thread(self.stt.transcribe_file, source)
        except Exception as e:
            logger.warning("Transcription failed for %s: %s", source, e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))

        # Auto-ingest transcript into memory
        if self.ingester and transcript:
            try:
                filename = os.path.basename(source)
                content_hash = hashlib.sha256(transcript.encode()).hexdigest()
                await self.ingester.ingest(
                    text=transcript,
                    filename=filename,
                    file_path=source,
                    file_size=os.path.getsize(source) if os.path.exists(source) else None,
                    content_hash=content_hash,
                )
            except Exception as e:
                logger.warning("Transcript ingestion failed for %s: %s", source, e, exc_info=True)

        return ToolResult(success=True, data=transcript)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_transcribe_tool.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add odigos/tools/transcribe.py tests/test_transcribe_tool.py
git commit -m "feat: add transcribe_audio tool with memory auto-ingestion"
```

---

### Task 6: speak Tool

**Files:**
- Create: `/Users/jacob/Projects/odigos/odigos/tools/speak.py`
- Test: `/Users/jacob/Projects/odigos/tests/test_speak_tool.py`

**Step 1: Write the failing test**

Create `/Users/jacob/Projects/odigos/tests/test_speak_tool.py`:

```python
"""Tests for the speak tool."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_speak_generates_audio_file():
    """Tool generates audio and returns file path."""
    from odigos.tools.speak import SpeakTool

    mock_tts = MagicMock()
    mock_tts.generate_audio.return_value = ("data/audio/123_abc.wav", 2500)

    tool = SpeakTool(tts_provider=mock_tts)
    result = await tool.execute({"text": "Hello world"})

    assert result.success is True
    assert "data/audio/123_abc.wav" in result.data
    assert "2500" in result.data or "2.5" in result.data
    mock_tts.generate_audio.assert_called_once_with("Hello world", None)


@pytest.mark.asyncio
async def test_speak_with_voice():
    """Tool passes voice parameter to provider."""
    from odigos.tools.speak import SpeakTool

    mock_tts = MagicMock()
    mock_tts.generate_audio.return_value = ("data/audio/456_def.wav", 1000)

    tool = SpeakTool(tts_provider=mock_tts)
    result = await tool.execute({"text": "Test", "voice": "marius"})

    assert result.success is True
    mock_tts.generate_audio.assert_called_once_with("Test", "marius")


@pytest.mark.asyncio
async def test_speak_missing_text():
    """Tool returns error when no text provided."""
    from odigos.tools.speak import SpeakTool

    tool = SpeakTool(tts_provider=MagicMock())
    result = await tool.execute({})

    assert result.success is False
    assert "text" in result.error.lower()


@pytest.mark.asyncio
async def test_speak_handles_provider_error():
    """Tool returns error when TTS generation fails."""
    from odigos.tools.speak import SpeakTool

    mock_tts = MagicMock()
    mock_tts.generate_audio.side_effect = RuntimeError("Out of memory")

    tool = SpeakTool(tts_provider=mock_tts)
    result = await tool.execute({"text": "Test"})

    assert result.success is False
    assert "Out of memory" in result.error
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_speak_tool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odigos.tools.speak'`

**Step 3: Write the tool**

Create `/Users/jacob/Projects/odigos/odigos/tools/speak.py`:

```python
"""speak tool — generate speech audio via TTS provider."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from odigos.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from plugins.tts.provider import PocketTTSProvider

logger = logging.getLogger(__name__)


class SpeakTool(BaseTool):
    """Generate speech audio from text using local TTS."""

    name = "speak"
    description = (
        "Convert text to speech audio. Returns a WAV file path and duration. "
        "Available voices: alba, marius, javert, jean, fantine, cosette, eponine, azelma."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to convert to speech",
            },
            "voice": {
                "type": "string",
                "description": "Voice name (default: config voice). Options: alba, marius, javert, jean, fantine, cosette, eponine, azelma",
            },
        },
        "required": ["text"],
    }

    def __init__(self, tts_provider: PocketTTSProvider) -> None:
        self.tts = tts_provider

    async def execute(self, params: dict) -> ToolResult:
        text = params.get("text")
        if not text:
            return ToolResult(success=False, data="", error="No text provided")

        voice = params.get("voice")

        try:
            filepath, duration_ms = await asyncio.to_thread(
                self.tts.generate_audio, text, voice
            )
        except Exception as e:
            logger.warning("TTS generation failed: %s", e, exc_info=True)
            return ToolResult(success=False, data="", error=str(e))

        return ToolResult(
            success=True,
            data=f"Audio generated: {filepath} ({duration_ms}ms)",
            side_effect={"audio_path": filepath, "duration_ms": duration_ms},
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_speak_tool.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add odigos/tools/speak.py tests/test_speak_tool.py
git commit -m "feat: add speak tool for text-to-speech generation"
```

---

### Task 7: Audio WebSocket Endpoints

**Files:**
- Create: `/Users/jacob/Projects/odigos/odigos/api/audio.py`
- Modify: `/Users/jacob/Projects/odigos/odigos/main.py:55-56,640-659`
- Test: `/Users/jacob/Projects/odigos/tests/test_audio_ws.py`

**Step 1: Write the failing test**

Create `/Users/jacob/Projects/odigos/tests/test_audio_ws.py`:

```python
"""Tests for audio WebSocket endpoints."""
import json
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from starlette.testclient import TestClient


def _make_app(stt_provider=None, tts_provider=None):
    """Create test app with audio router."""
    from odigos.api.audio import router

    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(api_key="test-key")

    # Create mock plugin context with providers
    plugin_context = MagicMock()
    plugin_context.get_provider.side_effect = lambda name: {
        "stt": stt_provider,
        "tts": tts_provider,
    }.get(name)
    app.state.plugin_context = plugin_context

    return app


class TestTTSWebSocket:
    def test_tts_no_provider_returns_error(self):
        """Returns error when TTS provider not available."""
        app = _make_app(tts_provider=None)
        client = TestClient(app)

        with client.websocket_connect("/api/ws/audio/speak?token=test-key") as ws:
            ws.send_json({"text": "hello", "voice": "alba"})
            data = ws.receive_json()
            assert data.get("error") is not None

    def test_stt_no_provider_returns_error(self):
        """Returns error when STT provider not available."""
        app = _make_app(stt_provider=None)
        client = TestClient(app)

        with client.websocket_connect("/api/ws/audio/transcribe?token=test-key") as ws:
            ws.send_bytes(b"\x00" * 100)
            data = ws.receive_json()
            assert data.get("error") is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_audio_ws.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odigos.api.audio'`

**Step 3: Write the audio WebSocket router**

Create `/Users/jacob/Projects/odigos/odigos/api/audio.py`:

```python
"""WebSocket endpoints for streaming audio (STT and TTS)."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _authenticate(websocket: WebSocket) -> bool:
    """Authenticate WebSocket via query param token."""
    settings = websocket.app.state.settings
    token = websocket.query_params.get("token", "")
    if not settings.api_key:
        return False
    return hmac.compare_digest(token, settings.api_key)


@router.websocket("/ws/audio/transcribe")
async def ws_transcribe(websocket: WebSocket):
    """Stream audio chunks for real-time transcription.

    Protocol:
        Client -> Server: binary PCM audio chunks (16kHz, mono, 16-bit)
        Server -> Client: {"partial": "text so far", "final": false}
        On disconnect: {"partial": "complete transcript", "final": true}
    """
    await websocket.accept()

    if not _authenticate(websocket):
        await websocket.send_json({"error": "Authentication failed"})
        await websocket.close(code=4003)
        return

    plugin_context = getattr(websocket.app.state, "plugin_context", None)
    stt_provider = plugin_context.get_provider("stt") if plugin_context else None

    if not stt_provider:
        await websocket.send_json({"error": "STT provider not available"})
        await websocket.close(code=4004)
        return

    try:
        # Create async generator from WebSocket binary messages
        async def audio_chunks():
            while True:
                try:
                    data = await websocket.receive_bytes()
                    # Convert raw bytes to float list (16-bit PCM -> float32)
                    import struct
                    num_samples = len(data) // 2
                    samples = struct.unpack(f"<{num_samples}h", data)
                    float_samples = [s / 32768.0 for s in samples]
                    yield float_samples, 16000
                except WebSocketDisconnect:
                    return

        async for partial_text in stt_provider.transcribe_stream(audio_chunks()):
            await websocket.send_json({"partial": partial_text, "final": False})

        await websocket.send_json({"partial": partial_text if 'partial_text' in dir() else "", "final": True})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("STT WebSocket error: %s", e, exc_info=True)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass


@router.websocket("/ws/audio/speak")
async def ws_speak(websocket: WebSocket):
    """Stream TTS audio generation.

    Protocol:
        Client -> Server: {"text": "speak this", "voice": "alba"}
        Server -> Client: binary PCM audio chunks (float32, model sample rate)
        Final: {"done": true, "duration_ms": 1234}
    """
    await websocket.accept()

    if not _authenticate(websocket):
        await websocket.send_json({"error": "Authentication failed"})
        await websocket.close(code=4003)
        return

    plugin_context = getattr(websocket.app.state, "plugin_context", None)
    tts_provider = plugin_context.get_provider("tts") if plugin_context else None

    if not tts_provider:
        await websocket.send_json({"error": "TTS provider not available"})
        await websocket.close(code=4004)
        return

    try:
        raw = await websocket.receive_text()
        request = json.loads(raw)
        text = request.get("text", "")
        voice = request.get("voice")

        if not text:
            await websocket.send_json({"error": "No text provided"})
            return

        total_bytes = 0
        async for chunk_bytes in tts_provider.generate_stream(text, voice):
            await websocket.send_bytes(chunk_bytes)
            total_bytes += len(chunk_bytes)

        # Calculate duration from total bytes (float32 = 4 bytes per sample)
        samples = total_bytes // 4
        duration_ms = int(samples / tts_provider.sample_rate * 1000) if samples > 0 else 0

        await websocket.send_json({"done": True, "duration_ms": duration_ms})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("TTS WebSocket error: %s", e, exc_info=True)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
```

**Step 4: Wire the router into main.py**

Add import at `/Users/jacob/Projects/odigos/odigos/main.py` near line 56 (with other router imports):

```python
from odigos.api.audio import router as audio_router
```

Add router inclusion near line 659 (with other `app.include_router` calls):

```python
app.include_router(audio_router)
```

Also, store `plugin_context` on `app.state` so the audio router can access providers. After line 388 (`app.state.plugin_manager = plugin_manager`), add:

```python
app.state.plugin_context = plugin_context
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/test_audio_ws.py -v`
Expected: 2 PASSED

**Step 6: Commit**

```bash
git add odigos/api/audio.py odigos/main.py tests/test_audio_ws.py
git commit -m "feat: add WebSocket endpoints for streaming STT and TTS audio"
```

---

### Task 8: Upload Endpoint Audio Detection

**Files:**
- Modify: `/Users/jacob/Projects/odigos/odigos/api/upload.py`
- Test: `/Users/jacob/Projects/odigos/tests/test_upload_audio.py`

**Step 1: Write the failing test**

Create `/Users/jacob/Projects/odigos/tests/test_upload_audio.py`:

```python
"""Tests for audio file detection in upload endpoint."""
import pytest


def test_audio_extension_detection():
    """Audio extensions are correctly identified."""
    from odigos.tools.transcribe import AUDIO_EXTENSIONS

    assert ".wav" in AUDIO_EXTENSIONS
    assert ".mp3" in AUDIO_EXTENSIONS
    assert ".ogg" in AUDIO_EXTENSIONS
    assert ".m4a" in AUDIO_EXTENSIONS
    assert ".webm" in AUDIO_EXTENSIONS
    assert ".flac" in AUDIO_EXTENSIONS
    assert ".opus" in AUDIO_EXTENSIONS
    assert ".pdf" not in AUDIO_EXTENSIONS
    assert ".txt" not in AUDIO_EXTENSIONS


def test_is_audio_file():
    """is_audio_file correctly classifies files."""
    from odigos.api.upload import is_audio_file

    assert is_audio_file("recording.wav") is True
    assert is_audio_file("recording.MP3") is True
    assert is_audio_file("voice.ogg") is True
    assert is_audio_file("document.pdf") is False
    assert is_audio_file("notes.txt") is False
    assert is_audio_file("") is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_upload_audio.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_audio_file' from 'odigos.api.upload'`

**Step 3: Modify upload endpoint to detect and transcribe audio**

Add to `/Users/jacob/Projects/odigos/odigos/api/upload.py`, after the imports:

```python
from odigos.tools.transcribe import AUDIO_EXTENSIONS


def is_audio_file(filename: str) -> bool:
    """Check if a filename has an audio extension."""
    if not filename:
        return False
    ext = os.path.splitext(filename.lower())[1]
    return ext in AUDIO_EXTENSIONS
```

In the `upload_file` function, replace the text extraction block (lines 55-58: the `try`/`except` around `markitdown.convert_file`) with:

```python
    # Extract text — use STT for audio files, MarkItDown for everything else
    stt_provider = None
    plugin_context = getattr(request.app.state, "plugin_context", None)
    if plugin_context:
        stt_provider = plugin_context.get_provider("stt")

    if is_audio_file(safe_name) and stt_provider:
        try:
            extracted_text = await asyncio.to_thread(stt_provider.transcribe_file, dest)
        except Exception:
            logger.warning("Audio transcription failed for %s", safe_name, exc_info=True)
    else:
        try:
            extracted_text = await asyncio.to_thread(markitdown.convert_file, dest)
        except Exception:
            logger.warning("Text extraction failed for %s", safe_name, exc_info=True)
```

You'll need to add `request: Request` to the function signature and import `Request`:

```python
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
```

Update the function signature:

```python
async def upload_file(
    request: Request,
    file: UploadFile,
    upload_dir: str = Depends(get_upload_dir),
    ingester: DocumentIngester = Depends(get_doc_ingester),
    markitdown: MarkItDownProvider = Depends(get_markitdown),
):
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_upload_audio.py -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
git add odigos/api/upload.py tests/test_upload_audio.py
git commit -m "feat: auto-transcribe audio files via STT in upload endpoint"
```

---

### Task 9: Telegram Voice Note Integration

**Files:**
- Modify: `/Users/jacob/Projects/odigos/odigos/channels/telegram.py`
- Modify: `/Users/jacob/Projects/odigos/plugins/channels/telegram/__init__.py`

**Step 1: Add voice note handler to TelegramChannel**

In `/Users/jacob/Projects/odigos/odigos/channels/telegram.py`, add a new method after `_handle_document` (around line 209):

```python
    async def _handle_voice(self, update: Update, context) -> None:
        """Handle incoming voice notes — transcribe via STT and process as text."""
        voice = update.effective_message.voice or update.effective_message.audio
        if not voice:
            return

        try:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action=ChatAction.TYPING
            )
        except Exception:
            pass

        # Download voice note
        os.makedirs(DOCUMENT_DIR, exist_ok=True)
        ext = ".ogg"  # Telegram voice notes are OGG/Opus
        if update.effective_message.audio:
            ext = os.path.splitext(update.effective_message.audio.file_name or ".mp3")[1]
        file_path = os.path.join(DOCUMENT_DIR, f"voice_{update.effective_message.message_id}{ext}")

        try:
            tg_file = await context.bot.get_file(voice.file_id)
            await tg_file.download_to_drive(file_path)
        except Exception:
            logger.exception("Failed to download voice note")
            await update.effective_message.reply_text("Failed to download the voice note.")
            return

        # Save to persistent uploads
        upload_dir = getattr(self.service, "upload_dir", "data/uploads")
        os.makedirs(upload_dir, exist_ok=True)
        persistent_name = f"{secrets.token_hex(8)}_{os.path.basename(file_path)}"
        persistent_path = os.path.join(upload_dir, persistent_name)
        shutil.copy2(file_path, persistent_path)

        # Transcribe via STT provider
        stt_provider = getattr(self.service, "stt_provider", None)
        transcript = None
        if stt_provider:
            try:
                transcript = await asyncio.to_thread(stt_provider.transcribe_file, persistent_path)
            except Exception:
                logger.warning("Voice transcription failed for %s", file_path, exc_info=True)

        if not transcript:
            transcript = "[Voice note received but transcription unavailable]"

        # Auto-ingest transcript into memory
        ingester = getattr(self.service, "doc_ingester", None)
        if ingester and transcript and not transcript.startswith("["):
            try:
                content_hash = hashlib.sha256(transcript.encode()).hexdigest()
                await ingester.ingest(
                    text=transcript,
                    filename=os.path.basename(file_path),
                    file_path=persistent_path,
                    file_size=os.path.getsize(persistent_path),
                    content_hash=content_hash,
                )
            except Exception:
                logger.warning("Voice transcript ingestion failed", exc_info=True)

        # Process transcribed text as a regular message
        message = UniversalMessage(
            id=str(update.effective_message.message_id),
            channel="telegram",
            sender=str(update.effective_user.id),
            content=transcript,
            timestamp=datetime.now(timezone.utc),
            metadata={
                "chat_id": update.effective_chat.id,
                "username": getattr(update.effective_user, "username", None),
                "voice_note": True,
                "audio_path": persistent_path,
            },
        )

        try:
            response = await self.service.handle_message(message)

            # If TTS is available and agent produced audio, send as voice message
            tts_provider = getattr(self.service, "tts_provider", None)
            if tts_provider and response:
                try:
                    audio_path, _duration = await asyncio.to_thread(
                        tts_provider.generate_audio, response
                    )
                    with open(audio_path, "rb") as audio_file:
                        await context.bot.send_voice(
                            chat_id=update.effective_chat.id, voice=audio_file
                        )
                    return  # Voice reply sent, skip text reply
                except Exception:
                    logger.warning("TTS voice reply failed, falling back to text", exc_info=True)

            await update.effective_message.reply_text(response)
        except Exception:
            logger.exception("Error handling voice message")
            await update.effective_message.reply_text("Something went wrong. Please try again.")
```

**Step 2: Register the voice handler in the start() method**

In the `start()` method of `TelegramChannel`, find where document handler is registered (look for `filters.Document`). Add voice and audio handlers nearby:

```python
        self._app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
        self._app.add_handler(MessageHandler(filters.AUDIO, self._handle_voice))
```

**Step 3: Wire STT/TTS providers to AgentService**

In `/Users/jacob/Projects/odigos/odigos/main.py`, after line 446 (`plugin_context.set_service(agent_service)`), add:

```python
    # Wire audio providers to service for channel access
    stt_from_plugin = plugin_context.get_provider("stt")
    tts_from_plugin = plugin_context.get_provider("tts")
    if stt_from_plugin:
        agent_service.stt_provider = stt_from_plugin
    if tts_from_plugin:
        agent_service.tts_provider = tts_from_plugin
```

**Step 4: Commit**

```bash
git add odigos/channels/telegram.py odigos/main.py
git commit -m "feat: add Telegram voice note transcription and TTS voice replies"
```

---

### Task 10: Full Registration Test + Wiring Verification

**Files:**
- Test: `/Users/jacob/Projects/odigos/tests/test_plugin_registration.py` (update existing)

**Step 1: Run the enabled plugin registration tests that depend on tools**

Now that the tools exist (Tasks 5-6), the enabled registration tests from Task 4 should pass:

Run: `pytest tests/test_plugin_registration.py -v`
Expected: 4 PASSED

**Step 2: Run the full test suite**

Run: `pytest tests/test_stt_provider.py tests/test_tts_provider.py tests/test_transcribe_tool.py tests/test_speak_tool.py tests/test_plugin_registration.py tests/test_upload_audio.py tests/test_audio_ws.py -v`
Expected: All tests PASS

**Step 3: Verify imports work**

Run: `python -c "from odigos.tools.transcribe import TranscribeAudioTool, AUDIO_EXTENSIONS; print('STT tool OK'); from odigos.tools.speak import SpeakTool; print('TTS tool OK'); from odigos.api.audio import router; print('Audio WS OK')"`
Expected: All three OK messages

**Step 4: Commit any fixes**

If any tests needed adjustments, commit the fixes:

```bash
git add -u
git commit -m "fix: resolve test issues in TTS/STT plugin suite"
```

---

## Summary

| Task | Component | Files Created/Modified |
|------|-----------|----------------------|
| 1 | Config + deps | `odigos/config.py`, `pyproject.toml` |
| 2 | STT provider | `plugins/stt/provider.py`, `tests/test_stt_provider.py` |
| 3 | TTS provider | `plugins/tts/provider.py`, `tests/test_tts_provider.py` |
| 4 | Plugin registration | `plugins/stt/__init__.py`, `plugins/stt/plugin.yaml`, `plugins/tts/__init__.py`, `plugins/tts/plugin.yaml`, `tests/test_plugin_registration.py` |
| 5 | transcribe_audio tool | `odigos/tools/transcribe.py`, `tests/test_transcribe_tool.py` |
| 6 | speak tool | `odigos/tools/speak.py`, `tests/test_speak_tool.py` |
| 7 | Audio WebSocket | `odigos/api/audio.py`, `odigos/main.py`, `tests/test_audio_ws.py` |
| 8 | Upload audio detection | `odigos/api/upload.py`, `tests/test_upload_audio.py` |
| 9 | Telegram voice | `odigos/channels/telegram.py`, `odigos/main.py` |
| 10 | Integration verification | Run all tests, verify wiring |
