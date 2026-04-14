from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _expand_env(value):
    """Recursively expand ${ENV_VAR} references in strings. Missing vars → empty string."""
    if isinstance(value, str):
        return _ENV_VAR_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


class AgentConfig(BaseModel):
    name: str = "Odigos"
    role: str = "personal_assistant"
    description: str = ""
    parent: str | None = None
    allow_external_evaluation: bool = False
    max_tool_turns: int = 25
    run_timeout_seconds: int = 300
    cite_sources: bool = True
    concise_mode: bool = False


class DatabaseConfig(BaseModel):
    path: str = "data/odigos.db"


class EmbeddingsConfig(BaseModel):
    mode: str = "auto"  # "auto" (detect toolkit), "local" (in-process), or "remote" (shared service)
    remote_url: str = "http://localhost:9000"


class ProviderConfig(BaseModel):
    """An OpenAI-compatible LLM provider endpoint. Defined once, referenced by models."""
    base_url: str
    api_key: str = ""  # Supports ${ENV_VAR} interpolation


class ModelConfig(BaseModel):
    """A model entry. Owns everything about the model — provider, id, cost, capabilities."""
    provider: str  # Key into Settings.providers
    id: str  # Actual model identifier sent to the API (e.g. "meta-llama/llama-4-scout")
    cost_in_per_mtok: float = 0.0  # $/million input tokens
    cost_out_per_mtok: float = 0.0  # $/million output tokens
    vision: bool = False
    context_window: int = 0
    notes: str = ""  # Free-form, shown in UI


class LLMConfig(BaseModel):
    """Routing — which model alias handles each intelligence tier.

    Values are aliases into Settings.models. Empty fields fall back to `fast`.
    """
    fast: str = "scout"  # Cheap default for most actions. Should support vision if possible.
    smart: str = "deepseek-v3.2"  # Reasoning-heavy work (planning, doc queries, hard classifications).
    background: str = ""  # Heartbeat / entity extraction / background loops. Defaults to fast.
    fallback: str = ""  # Safety net on primary failure. Defaults to fast.
    max_tokens: int = 4096
    temperature: float = 0.7
    request_timeout_seconds: float = 60.0
    connect_timeout_seconds: float = 10.0
    auto_route: bool = True  # If True, classifier tier drives intelligence automatically.


class TelegramConfig(BaseModel):
    mode: str = "polling"
    webhook_url: str = ""


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    ws_port: int = 8001


class BudgetConfig(BaseModel):
    daily_limit_usd: float = 1.00
    monthly_limit_usd: float = 20.00
    warn_threshold: float = 0.80


class SkillsConfig(BaseModel):
    path: str = "skills"


class HeartbeatConfig(BaseModel):
    interval_seconds: int = 30
    max_todos_per_tick: int = 3
    idle_think_interval: int = 900
    announce_interval_seconds: int = 60
    morning_briefing: bool = True


class ProactiveConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 900
    max_cycles_per_hour: int = 4
    max_per_cycle: int = 1
    safe_tools: list[str] = [
        "find_tools", "search", "scrape", "lookup_fact",
        "knowledge_lookup", "check_plan", "read_file",
    ]


class SandboxConfig(BaseModel):
    timeout_seconds: int = 5
    max_memory_mb: int = 512
    allow_network: bool = False


class FileAccessConfig(BaseModel):
    allowed_paths: list[str] = ["data/files"]


class MCPServerConfig(BaseModel):
    command: str
    args: list[str] = []
    env: dict[str, str] = {}


class MCPConfig(BaseModel):
    servers: dict[str, MCPServerConfig] = {}


class GWSConfig(BaseModel):
    enabled: bool = False
    timeout: int = 30


class BrowserConfig(BaseModel):
    enabled: bool = False
    timeout: int = 120


class MeshConfig(BaseModel):
    enabled: bool = False


class FeedConfig(BaseModel):
    enabled: bool = False
    public: bool = False
    max_entries: int = 200


class STTConfig(BaseModel):
    enabled: bool = False
    model: str = "small"
    language: str = "en"


class TTSConfig(BaseModel):
    enabled: bool = False
    voice: str = "alba"


class TemplatesConfig(BaseModel):
    repo_url: str = "https://github.com/msitarzewski/agency-agents"
    cache_ttl_days: int = 7


class ApprovalConfig(BaseModel):
    enabled: bool = True
    tools: list[str] = ["run_code", "run_shell", "write_file"]
    timeout: int = 300


class EvolutionConfig(BaseModel):
    trial_duration_hours: int = 48
    min_evaluations: int = 5
    promote_threshold: float = 0.5
    revert_threshold: float = -0.3
    auto_trial_confidence: float = 0.7
    strategist_min_evals: int = 10
    qualified_evaluator_min_score: float = 7.0


class PeerConfig(BaseModel):
    """Configuration for a trusted peer agent."""
    name: str
    netbird_ip: str = ""
    ws_port: int = 8001
    api_key: str = ""
    url: str = ""  # Legacy field -- auto-converted to netbird_ip + ws_port

    def model_post_init(self, __context) -> None:
        """Normalize legacy 'url' field into netbird_ip + ws_port."""
        if self.url and not self.netbird_ip:
            import re
            m = re.search(r"://([^:/]+)", self.url)
            if m:
                self.netbird_ip = m.group(1)
            m = re.search(r":(\d+)$", self.url.rstrip("/"))
            if m:
                self.ws_port = int(m.group(1))
            self.url = ""  # Clear after conversion


class NotebooksConfig(BaseModel):
    enabled: bool = True


class KanbanConfig(BaseModel):
    enabled: bool = True


class ImageGenerationConfig(BaseModel):
    default_aspect_ratio: str = "1:1"
    nsfw_filter: bool = True
    max_poll_seconds: int = 120


class MusicGenerationConfig(BaseModel):
    model: str = "V5_5"  # V5_5, V5, V4_5PLUS, V4_5, V4
    max_poll_seconds: int = 180


class AccessConfig(BaseModel):
    supervised: bool = False  # True = managed agent, protected settings locked. False = full admin access.


class CalendarConfig(BaseModel):
    url: str = ""  # CalDAV server URL — set this to enable calendar
    username: str = ""
    password: str = ""


class AutoUpdateConfig(BaseModel):
    enabled: bool = False
    check_interval_ticks: int = 60  # heartbeat ticks between checks (~30min at 30s)
    auto_apply: bool = False  # True = apply immediately, False = notify only
    branch: str = "main"


class EmailConfig(BaseModel):
    address: str = ""
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    check_interval_ticks: int = 10  # heartbeat ticks between inbox checks (0 = agent decides)


class AssistantConfig(BaseModel):
    enabled: bool = True
    show_transcript: bool = True
    text_input: bool = True
    voice_input: bool = True
    auto_read: bool = False
    position: str = "bottom-right"  # "bottom-right" or "bottom-left"


class VoiceConfig(BaseModel):
    stt_provider: str = "groq"  # "groq", "local" (moonshine), or "disabled"
    tts_provider: str = "edge"  # "edge" (edge-tts), "local" (pocket-tts), or "disabled"
    tts_voice: str = "en-US-AriaNeural"  # edge-tts voice name
    groq_model: str = "whisper-large-v3-turbo"


class StorageConfig(BaseModel):
    warn_gb: float = 10.0
    cap_gb: float = 12.0


class Settings(BaseSettings):
    # --- External services: one key per provider, auto-enables capabilities ---
    services: dict[str, str] = {}
    # Known service names:
    #   kie_ai      → image gen + music gen
    #   groq        → Whisper STT
    #   brave       → web search (Brave)
    #   google      → web search (Google), value = "api_key:cx_id"
    #   telegram    → Telegram bot channel
    #   notebooklm  → NotebookLM integration
    #   searxng     → SearxNG search (value = URL, auth via searxng_username/password)

    # --- LLM providers and models (the new unified config) ---
    providers: dict[str, ProviderConfig] = {}
    models: dict[str, ModelConfig] = {}

    # --- Core credentials ---
    api_key: str = ""  # Dashboard auth key
    session_secret: str = ""
    search_provider: str = ""
    searxng_url: str = ""  # Legacy — prefer services.searxng
    searxng_username: str = ""
    searxng_password: str = ""

    agent: AgentConfig = AgentConfig()
    database: DatabaseConfig = DatabaseConfig()
    embeddings: EmbeddingsConfig = EmbeddingsConfig()
    llm: LLMConfig = LLMConfig()
    telegram: TelegramConfig = TelegramConfig()
    server: ServerConfig = ServerConfig()
    budget: BudgetConfig = BudgetConfig()
    skills: SkillsConfig = SkillsConfig()
    heartbeat: HeartbeatConfig = HeartbeatConfig()
    proactive: ProactiveConfig = ProactiveConfig()
    sandbox: SandboxConfig = SandboxConfig()
    mcp: MCPConfig = MCPConfig()
    gws: GWSConfig = GWSConfig()
    browser: BrowserConfig = BrowserConfig()
    file_access: FileAccessConfig = FileAccessConfig()
    approval: ApprovalConfig = ApprovalConfig()
    evolution: EvolutionConfig = EvolutionConfig()
    mesh: MeshConfig = MeshConfig()
    feed: FeedConfig = FeedConfig()
    stt: STTConfig = STTConfig()
    tts: TTSConfig = TTSConfig()
    templates: TemplatesConfig = TemplatesConfig()
    peers: list[PeerConfig] = []
    notebooks: NotebooksConfig = NotebooksConfig()
    kanban: KanbanConfig = KanbanConfig()
    access: AccessConfig = AccessConfig()
    voice: VoiceConfig = VoiceConfig()
    assistant: AssistantConfig = AssistantConfig()
    calendar: CalendarConfig = CalendarConfig()
    email: EmailConfig = EmailConfig()
    image_generation: ImageGenerationConfig = ImageGenerationConfig()
    music_generation: MusicGenerationConfig = MusicGenerationConfig()
    auto_update: AutoUpdateConfig = AutoUpdateConfig()
    storage: StorageConfig = StorageConfig()

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    def service_key(self, name: str) -> str:
        """Get API key for an external service. Returns empty string if not configured."""
        return self.services.get(name, "")

    # Compat properties — code that reads old field names still works
    @property
    def telegram_bot_token(self) -> str:
        return self.service_key("telegram")

    @property
    def groq_api_key(self) -> str:
        return self.service_key("groq")

    @property
    def brave_api_key(self) -> str:
        return self.service_key("brave")

    @property
    def notebooklm_cookie(self) -> str:
        return self.service_key("notebooklm")


def load_settings(config_path: str = "config.yaml") -> Settings:
    """Load settings from environment variables and a YAML config file.

    Supports ${ENV_VAR} interpolation in any string value — used primarily to
    keep provider API keys in .env while referencing them from config.yaml.
    Loads .env into the process environment first so interpolation works even
    when the process wasn't started via the expected launcher.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except ImportError:
        pass

    yaml_config: dict = {}
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            yaml_config = yaml.safe_load(f) or {}

    yaml_config = _expand_env(yaml_config)
    return Settings(**yaml_config)


def reload_into(target: Settings, config_path: str = "config.yaml") -> None:
    """Reload settings from disk and atomically replace all fields on target.

    Validates the new config via Pydantic before mutating anything.
    If validation fails, target is unchanged and the exception propagates.
    """
    fresh = load_settings(config_path)
    for field in fresh.model_fields:
        object.__setattr__(target, field, getattr(fresh, field))
