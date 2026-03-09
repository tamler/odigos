# Odigos

Self-hosted personal AI agent.

## Prerequisites

- **Python 3.12+** -- [python.org/downloads](https://www.python.org/downloads/)
- **pip** -- included with Python 3.12+
- **Node.js / npm** -- [nodejs.org](https://nodejs.org/) (for CLI tool dependencies)
- **Telegram Bot Token** -- create via [@BotFather](https://t.me/BotFather)
- **OpenRouter API Key** -- [openrouter.ai/keys](https://openrouter.ai/keys)

## Install

```bash
git clone <repo-url> && cd odigos
./install.sh
```

The install script:
1. Installs Python dependencies
2. Installs CLI tools (Google Workspace CLI, etc.)
3. Creates `.env` and `config.yaml` from examples
4. Prompts for API keys
5. Offers authentication setup for CLI tools

Safe to re-run anytime to pick up new dependencies.

## Run

```bash
odigos
```

Or with a custom config:

```bash
odigos path/to/config.yaml
```

## Configuration

- `.env` -- API keys and secrets
- `config.yaml` -- agent settings, tool configuration, model selection

See `config.yaml.example` for all available options.
