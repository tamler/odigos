from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class AgentConfig(BaseModel):
    name: str = "Odigos"
    role: str = "personal_assistant"
    description: str = ""
    parent: Optional[str] = None
    allow_external_evaluation: bool = False
    max_tool_turns: int = 25
    run_timeout_seconds: int = 300


class DatabaseConfig(BaseModel):
    path: str = "data/odigos.db"


class LLMConfig(BaseModel):
    base_url: str = "https://openrouter.ai/api/v1"
    default_model: str = "anthropic/claude-sonnet-4"
    fallback_model: str = "google/gemini-2.0-flash-001"
    max_tokens: int = 4096
    temperature: float = 0.7


class PersonalityConfig(BaseModel):
    path: str = "data/personality.yaml"


class TelegramConfig(BaseModel):
    mode: str = "polling"
    webhook_url: str = ""


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class BudgetConfig(BaseModel):
    daily_limit_usd: float = 1.00
    monthly_limit_usd: float = 20.00
    warn_threshold: float = 0.80


class RouterConfig(BaseModel):
    free_pool: list[str] = [
        "meta-llama/llama-4-scout:free",
        "google/gemma-3-27b-it:free",
        "mistralai/mistral-small-3.2-24b-instruct:free",
    ]
    rate_limit_rpm: int = 20


class ContextConfig(BaseModel):
    max_tokens: int = 12000


class SkillsConfig(BaseModel):
    path: str = "skills"


class HeartbeatConfig(BaseModel):
    interval_seconds: int = 30
    max_todos_per_tick: int = 3
    idle_think_interval: int = 900


class SandboxConfig(BaseModel):
    timeout_seconds: int = 5
    max_memory_mb: int = 512
    allow_network: bool = False


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


class ApprovalConfig(BaseModel):
    enabled: bool = False
    tools: list[str] = []
    timeout: int = 300


class DeployTargetConfig(BaseModel):
    """Configuration for a VPS deployment target."""
    name: str
    host: str
    method: str = "docker"
    ssh_user: str = "root"
    ssh_key_path: Optional[str] = None


class PeerConfig(BaseModel):
    """Configuration for a trusted peer agent."""
    name: str
    url: str = ""
    netbird_ip: str = ""
    ws_port: int = 8001
    api_key: str = ""


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    llm_api_key: str
    api_key: str = ""
    searxng_url: str = ""
    searxng_username: str = ""
    searxng_password: str = ""

    agent: AgentConfig = AgentConfig()
    database: DatabaseConfig = DatabaseConfig()
    llm: LLMConfig = LLMConfig()
    personality: PersonalityConfig = PersonalityConfig()
    telegram: TelegramConfig = TelegramConfig()
    server: ServerConfig = ServerConfig()
    budget: BudgetConfig = BudgetConfig()
    router: RouterConfig = RouterConfig()
    context: ContextConfig = ContextConfig()
    skills: SkillsConfig = SkillsConfig()
    heartbeat: HeartbeatConfig = HeartbeatConfig()
    sandbox: SandboxConfig = SandboxConfig()
    mcp: MCPConfig = MCPConfig()
    gws: GWSConfig = GWSConfig()
    browser: BrowserConfig = BrowserConfig()
    approval: ApprovalConfig = ApprovalConfig()
    peers: list[PeerConfig] = []
    deploy_targets: list[DeployTargetConfig] = []

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def load_settings(config_path: str = "config.yaml") -> Settings:
    """Load settings from environment variables and a YAML config file."""
    yaml_config: dict = {}
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            yaml_config = yaml.safe_load(f) or {}

    return Settings(**yaml_config)
