from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class AgentConfig(BaseModel):
    name: str = "Odigos"


class DatabaseConfig(BaseModel):
    path: str = "data/odigos.db"


class OpenRouterConfig(BaseModel):
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
    max_tasks_per_tick: int = 5


class SandboxConfig(BaseModel):
    timeout_seconds: int = 5
    max_memory_mb: int = 512
    allow_network: bool = False


class Settings(BaseSettings):
    telegram_bot_token: str
    openrouter_api_key: str
    searxng_url: str = ""
    searxng_username: str = ""
    searxng_password: str = ""

    agent: AgentConfig = AgentConfig()
    database: DatabaseConfig = DatabaseConfig()
    openrouter: OpenRouterConfig = OpenRouterConfig()
    personality: PersonalityConfig = PersonalityConfig()
    telegram: TelegramConfig = TelegramConfig()
    server: ServerConfig = ServerConfig()
    budget: BudgetConfig = BudgetConfig()
    router: RouterConfig = RouterConfig()
    context: ContextConfig = ContextConfig()
    skills: SkillsConfig = SkillsConfig()
    heartbeat: HeartbeatConfig = HeartbeatConfig()
    sandbox: SandboxConfig = SandboxConfig()

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def load_settings(config_path: str = "config.yaml") -> Settings:
    """Load settings from environment variables and a YAML config file."""
    yaml_config: dict = {}
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            yaml_config = yaml.safe_load(f) or {}

    return Settings(**yaml_config)
