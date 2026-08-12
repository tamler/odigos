"""Structured user profiler with dimensional scoring."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from odigos.core.capabilities import TextBlob

logger = logging.getLogger(__name__)

# Exponential moving average decay factor (0-1, higher = more recent weight)
EMA_ALPHA = 0.3


@dataclass
class UserProfile:
    """Structured user profile with 20+ scored dimensions."""

    # Communication preferences (0-1 scale)
    verbosity_preference: float = 0.5     # 0=terse, 1=detailed
    formality_level: float = 0.5          # 0=casual, 1=formal
    technical_depth: float = 0.5          # 0=simple, 1=deep technical
    emoji_tolerance: float = 0.0          # 0=none, 1=frequent

    # Expertise (0-1 scale)
    coding_expertise: float = 0.3
    data_analysis: float = 0.3
    writing_skill: float = 0.3
    design_awareness: float = 0.3
    domain_breadth: float = 0.3           # how many topics

    # Behavior patterns (0-1 scale)
    patience_level: float = 0.5           # 0=impatient, 1=patient
    correction_frequency: float = 0.3     # how often they correct
    exploration_tendency: float = 0.5     # 0=focused, 1=exploratory
    delegation_comfort: float = 0.5       # trusts agent with tasks
    follow_through: float = 0.5          # completes what they start

    # Engagement (0-1 scale)
    session_depth: float = 0.5            # avg messages per session
    tool_usage_comfort: float = 0.5       # comfortable with tools
    feedback_frequency: float = 0.3       # how often they give feedback
    multi_step_tolerance: float = 0.5     # patience for complex plans

    # Preferences (0-1 scale)
    prefers_code: float = 0.3             # wants code solutions
    prefers_explanations: float = 0.5     # wants reasoning
    prefers_actions: float = 0.5          # wants agent to just do it
    prefers_asking: float = 0.5           # wants to be asked first

    # Meta
    relationship_stage: str = "new"       # new/established/deep
    primary_use_case: str = "general"     # general/coding/writing/research
    timezone_hint: str = ""
    active_hours: str = ""                # e.g., "9-17" or "night"
    interaction_count: int = 0
    last_updated: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> UserProfile:
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid}
        return cls(**filtered)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, s: str) -> UserProfile:
        return cls.from_dict(json.loads(s))


def update_dimension(
    current: float, observation: float, alpha: float = EMA_ALPHA,
) -> float:
    """Update a dimension using exponential moving average."""
    return current + alpha * (observation - current)


def analyze_message_signals(
    message: str, role: str = "user",
) -> dict[str, float]:
    """Extract dimensional signals from a message.

    Returns dict of dimension_name -> observed_value (0-1).
    Only returns dimensions that can be inferred from this message.
    """
    signals: dict[str, float] = {}

    if role != "user":
        return signals

    words = message.split()
    word_count = len(words)

    # Verbosity: longer messages = higher preference
    if word_count <= 5:
        signals["verbosity_preference"] = 0.1
    elif word_count <= 20:
        signals["verbosity_preference"] = 0.4
    elif word_count <= 50:
        signals["verbosity_preference"] = 0.6
    else:
        signals["verbosity_preference"] = 0.9

    lower = message.lower()
    lower_words = lower.split()

    # Technical depth
    tech_keywords = {
        "api", "function", "class", "database", "query",
        "deploy", "server", "config", "debug", "error",
        "git", "docker", "sql", "json", "regex", "async",
    }
    tech_count = sum(1 for w in lower_words if w in tech_keywords)
    if tech_count > 0:
        signals["technical_depth"] = min(tech_count / 5, 1.0)
        signals["coding_expertise"] = min(tech_count / 3, 1.0)

    # Patience: short frustrated messages via textblob if available
    # TextBlob comes from the shared probe, which logs once at ERROR if the
    # declared dependency failed to import. LookupError is still caught here:
    # TextBlob imports fine but raises at call time without its NLTK corpora.
    if TextBlob is not None:
        try:
            blob = TextBlob(message)
            if blob.sentiment.polarity < -0.3 and word_count < 15:
                signals["patience_level"] = 0.1
            elif word_count > 50:
                signals["patience_level"] = 0.8
        except LookupError:
            if word_count > 50:
                signals["patience_level"] = 0.8
    elif word_count > 50:
        signals["patience_level"] = 0.8

    # Correction detection
    correction_starts = [
        "no", "wrong", "that's not", "actually",
        "i said", "not what i", "incorrect",
    ]
    if any(lower.startswith(c) for c in correction_starts):
        signals["correction_frequency"] = 0.9

    # Delegation: imperative commands = high delegation comfort
    imperative_words = {
        "do", "create", "make", "build", "fix", "update",
        "delete", "send", "check", "run", "deploy",
    }
    if lower_words and lower_words[0] in imperative_words:
        signals["delegation_comfort"] = 0.8
        signals["prefers_actions"] = 0.8

    # Wants explanations
    question_words = {"why", "how", "what", "explain", "tell"}
    if lower_words and lower_words[0] in question_words:
        signals["prefers_explanations"] = 0.8

    # Prefers code
    if "code" in lower or "script" in lower or "```" in message:
        signals["prefers_code"] = 0.8

    return signals


async def update_profile_from_message(
    db, message: str, role: str = "user",
) -> None:
    """Update the structured profile based on a single message."""
    signals = analyze_message_signals(message, role)
    if not signals:
        return

    # Load current profile
    row = await db.fetch_one(
        "SELECT profile_json FROM user_profile_v2 "
        "WHERE id = 'owner'"
    )
    if row and row["profile_json"]:
        profile = UserProfile.from_json(row["profile_json"])
    else:
        profile = UserProfile()

    # Apply EMA updates
    for dim, observed in signals.items():
        if hasattr(profile, dim):
            current = getattr(profile, dim)
            if isinstance(current, float):
                new_val = update_dimension(current, observed)
                setattr(profile, dim, round(new_val, 3))

    profile.interaction_count += 1
    profile.last_updated = datetime.now(timezone.utc).isoformat()

    # Save
    await db.execute(
        "INSERT OR REPLACE INTO user_profile_v2 "
        "(id, profile_json, updated_at) VALUES (?, ?, ?)",
        ("owner", profile.to_json(), profile.last_updated),
    )


def format_profile_for_context(profile: UserProfile) -> str:
    """Format the structured profile for the system prompt."""
    lines = ["## User Profile (Structured)"]

    # Communication
    verb = "detailed" if profile.verbosity_preference > 0.6 else (
        "concise" if profile.verbosity_preference < 0.4 else "moderate"
    )
    form = "formal" if profile.formality_level > 0.6 else (
        "casual" if profile.formality_level < 0.4 else "balanced"
    )
    tech = "technical" if profile.technical_depth > 0.6 else (
        "simple" if profile.technical_depth < 0.4 else "mixed"
    )
    lines.append(f"Communication: {verb}, {form}, {tech}")

    # Expertise
    high_expertise = []
    if profile.coding_expertise > 0.6:
        high_expertise.append("coding")
    if profile.data_analysis > 0.6:
        high_expertise.append("data")
    if profile.writing_skill > 0.6:
        high_expertise.append("writing")
    if profile.design_awareness > 0.6:
        high_expertise.append("design")
    if high_expertise:
        lines.append(f"Strong in: {', '.join(high_expertise)}")

    # Behavior
    if profile.patience_level < 0.3:
        lines.append("Prefers quick, direct responses")
    if profile.delegation_comfort > 0.7:
        lines.append("Comfortable with autonomous action")
    if profile.prefers_asking > 0.7:
        lines.append("Prefers to be asked before major actions")
    if profile.correction_frequency > 0.6:
        lines.append("Frequently corrects -- be precise")

    # Preferences
    if profile.prefers_code > 0.6:
        lines.append("Prefers code solutions")
    if profile.prefers_explanations > 0.6:
        lines.append("Values explanations and reasoning")

    lines.append(f"Relationship: {profile.relationship_stage}")
    lines.append(f"Primary use: {profile.primary_use_case}")

    return "\n".join(lines)
