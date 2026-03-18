from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class AgentConfig(BaseModel):
    name: str = "Odigos"
    role: str = "personal_assistant"
    description: str = ""
    parent: str | None = None
    allow_external_evaluation: bool = False
    max_tool_turns: int = 25
    run_timeout_seconds: int = 300
    cite_sources: bool = True


class DatabaseConfig(BaseModel):
    path: str = "data/odigos.db"


class LLMConfig(BaseModel):
    base_url: str = "https://openrouter.ai/api/v1"
    default_model: str = "anthropic/claude-sonnet-4"
    fallback_model: str = "google/gemini-2.0-flash-001"
    background_model: str = ""
    reasoning_model: str = ""  # Used for document_query and complex classifications. Falls back to default_model if empty.
    max_tokens: int = 4096
    temperature: float = 0.7
    request_timeout_seconds: float = 60.0
    connect_timeout_seconds: float = 10.0


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


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    llm_api_key: str = ""
    api_key: str = ""
    session_secret: str = ""
    search_provider: str = ""
    searxng_url: str = ""
    searxng_username: str = ""
    searxng_password: str = ""
    brave_api_key: str = ""
    google_search_api_key: str = ""
    google_search_cx: str = ""
    notebooklm_cookie: str = ""

    agent: AgentConfig = AgentConfig()
    database: DatabaseConfig = DatabaseConfig()
    llm: LLMConfig = LLMConfig()
    telegram: TelegramConfig = TelegramConfig()
    server: ServerConfig = ServerConfig()
    budget: BudgetConfig = BudgetConfig()
    skills: SkillsConfig = SkillsConfig()
    heartbeat: HeartbeatConfig = HeartbeatConfig()
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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def load_settings(config_path: str = "config.yaml") -> Settings:
    """Load settings from environment variables and a YAML config file."""
    yaml_config: dict = {}
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            yaml_config = yaml.safe_load(f) or {}

    return Settings(**yaml_config)
