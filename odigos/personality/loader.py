import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class VoiceConfig:
    tone: str = "direct, warm, slightly informal"
    verbosity: str = "concise by default, detailed when asked"
    humor: str = "dry, occasional, never forced"
    formality: str = "casual with owner, professional with others"


@dataclass
class IdentityConfig:
    role: str = "personal assistant and research partner"
    relationship: str = "trusted aide — not a servant, not a peer"
    first_person: bool = True
    expresses_uncertainty: bool = True
    expresses_opinions: bool = True


@dataclass
class Personality:
    name: str = "Odigos"
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)


_cache: dict[str, tuple[float, Personality]] = {}


def load_personality(path: str) -> Personality:
    """Load personality from a YAML file. Caches until file mtime changes.

    Returns defaults if file is missing.
    """
    filepath = Path(path)
    if not filepath.exists():
        return Personality()

    mtime = filepath.stat().st_mtime
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]

    with open(filepath) as f:
        data = yaml.safe_load(f) or {}

    voice_data = data.get("voice", {})
    identity_data = data.get("identity", {})

    personality = Personality(
        name=data.get("name", "Odigos"),
        voice=VoiceConfig(
            **{k: v for k, v in voice_data.items() if k in VoiceConfig.__dataclass_fields__}
        ),
        identity=IdentityConfig(
            **{k: v for k, v in identity_data.items() if k in IdentityConfig.__dataclass_fields__}
        ),
    )
    _cache[path] = (mtime, personality)
    return personality
