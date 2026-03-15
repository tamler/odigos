# TTS & STT Plugins — Design

**Goal:** Add speech-to-text and text-to-speech as optional plugins, both running locally on CPU with no external API dependencies. Support both file-based and streaming audio from the start.

---

## STT Plugin (Moonshine)

### Library: `moonshine-voice`

**Key API surface:**
- `Transcriber(model_path, model_arch)` — loads ONNX model
- `transcriber.transcribe_without_streaming(audio_data, sample_rate)` — file transcription, returns `Transcript` with `.lines[].text`
- `transcriber.transcribe(audio_chunk)` — streaming transcription, feed chunks incrementally, returns partial `Transcript`
- `load_wav_file(path)` — returns `(audio_data: list[float], sample_rate: int)`, WAV only
- `get_model_path(model_name)` — resolves model directory from assets
- `ModelArch` enum: `TINY=0, BASE=1, TINY_STREAMING=2, BASE_STREAMING=3, SMALL_STREAMING=4, MEDIUM_STREAMING=5`
- Models downloaded via `python -m moonshine_voice.download --language en`

**Design decisions:**
- Use `SMALL_STREAMING` arch by default — handles both file and streaming input through a single model
- For file transcription: load audio, feed through streaming transcriber in one pass
- For real-time: feed audio chunks as they arrive, yield partial transcripts
- WAV-only native input. For other formats (mp3, ogg, m4a, webm), convert to WAV via ffmpeg subprocess before transcription
- Lazy model loading on first use (model stays in memory after that)

### Plugin Structure

```
plugins/stt/
  __init__.py    # register(ctx) -> registers transcribe_audio tool + WS handler
  plugin.yaml    # metadata
  provider.py    # MoonshineSTT class wrapping the library
```

### Provider: `MoonshineSTT`

```python
class MoonshineSTT:
    def __init__(self, model_size="small", language="en"):
        self._transcriber = None  # lazy init
        self._model_size = model_size
        self._language = language

    def _ensure_loaded(self):
        """Load model on first use."""
        if self._transcriber is not None:
            return
        from moonshine_voice.transcriber import Transcriber
        from moonshine_voice.moonshine_api import ModelArch
        from moonshine_voice.utils import get_model_path

        # Streaming archs work for both file and streaming input
        arch_map = {
            "tiny": ModelArch.TINY_STREAMING,
            "small": ModelArch.SMALL_STREAMING,
            "medium": ModelArch.MEDIUM_STREAMING,
        }
        arch = arch_map.get(self._model_size, ModelArch.SMALL_STREAMING)
        model_name = f"{self._model_size}-{self._language}"
        model_path = str(get_model_path(model_name))
        self._transcriber = Transcriber(model_path=model_path, model_arch=arch)

    def transcribe_file(self, audio_path: str) -> str:
        """Transcribe an audio file to text. Returns full transcript."""
        self._ensure_loaded()
        wav_path = self._ensure_wav(audio_path)
        from moonshine_voice.utils import load_wav_file
        audio_data, sample_rate = load_wav_file(wav_path)
        transcript = self._transcriber.transcribe_without_streaming(audio_data, sample_rate)
        return " ".join(line.text for line in transcript.lines)

    async def transcribe_stream(self, audio_chunks):
        """Transcribe streaming audio chunks. Yields partial transcript strings.

        Args:
            audio_chunks: async iterator of (audio_data: list[float], sample_rate: int) tuples
        """
        self._ensure_loaded()
        async for chunk_data, _sample_rate in audio_chunks:
            transcript = self._transcriber.transcribe(chunk_data)
            if transcript and transcript.lines:
                yield " ".join(line.text for line in transcript.lines)

    def _ensure_wav(self, path: str) -> str:
        """Convert non-WAV audio to WAV via ffmpeg if needed."""
        if path.lower().endswith(".wav"):
            return path
        import subprocess, tempfile
        wav_path = tempfile.mktemp(suffix=".wav")
        subprocess.run(
            ["ffmpeg", "-i", path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
            capture_output=True, check=True,
        )
        return wav_path
```

### Tool: `transcribe_audio`

- Parameters: `source` (file path to audio)
- Runs transcription via `asyncio.to_thread(provider.transcribe_file, path)`
- Auto-ingests transcript into memory via DocumentIngester (same as file upload)
- Returns transcript text

### WebSocket: `/ws/audio/transcribe`

- Client sends binary audio chunks (16kHz mono PCM)
- Server yields partial transcript JSON: `{"partial": "text so far...", "final": false}`
- On stream end: `{"partial": "complete text", "final": true}` + auto-ingest into memory

### Config

```yaml
stt:
  enabled: true
  model: "small"     # tiny, small, medium (all streaming-capable)
  language: "en"
```

### Integration Points

1. **Upload endpoint** — detect audio extensions (.wav, .mp3, .ogg, .m4a, .webm, .flac), transcribe via STT instead of MarkItDown, then ingest transcript
2. **Telegram voice notes** — auto-transcribe on receive, use transcript as message content, preserve original audio in `data/uploads/`
3. **Agent tool** — `transcribe_audio` tool available for the agent to use on demand
4. **WebSocket streaming** — real-time transcription for connected clients

---

## TTS Plugin (Pocket-TTS)

### Library: `pocket-tts`

**Key API surface:**
- `TTSModel.load_model()` — loads 100M param model (slow, do once)
- `model.get_state_for_audio_prompt("alba")` — load voice preset (slow, cache it)
- `model.generate_audio(voice_state, text)` — returns 1D torch tensor of PCM data
- `model.generate_audio_stream(voice_state, text)` — yields audio chunk tensors as generated (~200ms first chunk)
- `model.sample_rate` — output sample rate for WAV writing
- `scipy.io.wavfile.write(path, sample_rate, audio.numpy())` — save to WAV
- Available voices: alba, marius, javert, jean, fantine, cosette, eponine, azelma
- Voice cloning: pass any .wav file path to `get_state_for_audio_prompt()`
- Export voice state to .safetensors for fast loading

**Design decisions:**
- Load model and default voice state once at plugin init (not lazy — too slow for first request)
- Cache voice states for any requested voice
- Two generation modes: file (complete WAV) and stream (chunked PCM)
- File output to `data/audio/{timestamp}_{id}.wav`
- ~6x real-time on CPU, so 10s of speech generates in <2s
- Streaming: ~200ms to first audio chunk

### Plugin Structure

```
plugins/tts/
  __init__.py    # register(ctx) -> registers speak tool + WS handler
  plugin.yaml    # metadata
  provider.py    # PocketTTSProvider class wrapping the library
```

### Provider: `PocketTTSProvider`

```python
class PocketTTSProvider:
    def __init__(self, default_voice="alba"):
        self._model = None  # loaded in initialize()
        self._voice_states = {}
        self._default_voice = default_voice

    def initialize(self):
        """Load model and default voice. Call once at startup."""
        from pocket_tts import TTSModel
        self._model = TTSModel.load_model()
        self._voice_states[self._default_voice] = (
            self._model.get_state_for_audio_prompt(self._default_voice)
        )

    @property
    def sample_rate(self) -> int:
        return self._model.sample_rate

    def _get_voice_state(self, voice: str):
        if voice not in self._voice_states:
            self._voice_states[voice] = self._model.get_state_for_audio_prompt(voice)
        return self._voice_states[voice]

    def generate_audio(self, text: str, voice: str | None = None) -> tuple[str, int]:
        """Generate WAV audio from text. Returns (file_path, duration_ms)."""
        import os, time
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
        """Stream audio generation. Yields raw PCM bytes as they're produced.

        Each chunk is a bytes object of 16-bit PCM audio at self.sample_rate.
        ~200ms latency to first chunk.
        """
        voice = voice or self._default_voice
        voice_state = self._get_voice_state(voice)
        for chunk_tensor in self._model.generate_audio_stream(voice_state, text):
            yield chunk_tensor.numpy().tobytes()
```

### Tool: `speak`

- Parameters: `text` (string to speak), `voice` (optional voice name, default from config), `stream` (bool, default false)
- File mode: `asyncio.to_thread(provider.generate_audio, text, voice)` — returns file path + duration
- Stream mode: returns a stream reference that the transport layer uses to push audio chunks
- Agent uses this proactively or when caller requests audio

### WebSocket: `/ws/audio/speak`

- Client sends JSON: `{"text": "Hello world", "voice": "alba"}`
- Server streams back binary PCM audio chunks as they're generated
- Final message: JSON `{"done": true, "duration_ms": 1234}`
- Client plays chunks as they arrive for low-latency playback

### Config

```yaml
tts:
  enabled: true
  voice: "alba"    # alba, marius, javert, jean, fantine, cosette, eponine, azelma
```

### Integration Points

1. **Telegram** — when agent uses `speak` tool, send the complete WAV as a voice message (file mode)
2. **API response** — include `audio_path` in response when speak tool was used, caller can fetch file
3. **WebSocket streaming** — real-time audio playback for connected clients (~200ms first chunk)
4. **Agent-driven** — agent decides when to generate audio (proactive use of speak tool)
5. **Caller-requested** — API `audio_response: true` parameter triggers TTS on agent response

---

## Audio WebSocket Protocol

Both STT and TTS share a common WebSocket pattern on the existing WS infrastructure:

### STT Stream (`/ws/audio/transcribe`)
```
Client -> Server: binary PCM audio chunks (16kHz, mono, 16-bit)
Server -> Client: {"partial": "text so far", "final": false}
Server -> Client: {"partial": "complete transcript", "final": true}
```

### TTS Stream (`/ws/audio/speak`)
```
Client -> Server: {"text": "speak this", "voice": "alba"}
Server -> Client: binary PCM audio chunks (model sample rate, mono, 16-bit)
Server -> Client: {"done": true, "duration_ms": 1234}
```

---

## Audio File Handling

- Generated audio: `data/audio/{timestamp}_{id}.wav`
- Uploaded/received audio: `data/uploads/{id}_{filename}` (same as other uploads)
- Transcripts: ingested into memory as `document_chunk` with source tracking back to original audio file

---

## Dependencies

Added as optional extras in `pyproject.toml`:

```toml
[project.optional-dependencies]
stt = ["moonshine-voice>=1.0.0"]
tts = ["pocket-tts>=0.1.0", "scipy"]
```

Neither required for core agent operation. Plugins check for import availability and skip gracefully.

---

## What We're NOT Building

- No dashboard audio player (future)
- No voice cloning UI (can be done via config file path)
- No audio format conversion library (use ffmpeg subprocess)
- No multi-language STT models (English first, add more via config later)
- No duplex voice conversation (STT + TTS combined in real-time loop — future)

---

## Files to Create/Modify

| File | Change |
|------|--------|
| `plugins/stt/__init__.py` | New — plugin registration + WS route |
| `plugins/stt/plugin.yaml` | New — plugin metadata |
| `plugins/stt/provider.py` | New — MoonshineSTT wrapper (file + streaming) |
| `plugins/tts/__init__.py` | New — plugin registration + WS route |
| `plugins/tts/plugin.yaml` | New — plugin metadata |
| `plugins/tts/provider.py` | New — PocketTTSProvider wrapper (file + streaming) |
| `odigos/tools/transcribe.py` | New — transcribe_audio tool |
| `odigos/tools/speak.py` | New — speak tool (file + stream modes) |
| `odigos/api/upload.py` | Modify — detect audio files, use STT |
| `odigos/api/audio.py` | New — WebSocket endpoints for streaming audio |
| `odigos/channels/telegram.py` | Modify — voice note transcription, voice replies |
| `pyproject.toml` | Modify — add optional deps |
