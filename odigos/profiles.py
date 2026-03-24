"""Agent profiles -- pre-built configurations for common use cases.

Profiles set the agent's role, enabled features, and default skills.
Applied on first setup or when switching profiles via settings.
"""
from __future__ import annotations

PROFILES = {
    "personal": {
        "name": "Personal Assistant",
        "description": "General-purpose personal AI assistant",
        "config": {
            "agent": {"role": "personal_assistant"},
            "notebooks": {"enabled": True},
            "kanban": {"enabled": True},
            "access": {"supervised": False},
        },
        "skills": ["deep-research", "journal", "kanban", "summarize-doc", "summarize-page"],
    },
    "learner": {
        "name": "Learner",
        "description": "Personal AI tutor that adapts to your pace and style (supervised)",
        "config": {
            "agent": {"role": "learner"},
            "notebooks": {"enabled": True},
            "kanban": {"enabled": True},
            "access": {"supervised": True},
        },
        "skills": ["tutor", "deep-research", "journal", "kanban"],
    },
    "mentor": {
        "name": "Mentor",
        "description": "Manages learning and tracks progress across connected agents",
        "config": {
            "agent": {"role": "mentor"},
            "notebooks": {"enabled": True},
            "kanban": {"enabled": True},
            "access": {"supervised": False},
            "mesh": {"enabled": True},
        },
        "skills": ["mentor", "deep-research", "kanban"],
    },
    "researcher": {
        "name": "Researcher",
        "description": "Deep research and document analysis specialist",
        "config": {
            "agent": {"role": "researcher"},
            "notebooks": {"enabled": True},
            "kanban": {"enabled": False},
            "access": {"supervised": False},
        },
        "skills": ["deep-research", "summarize-doc", "summarize-page", "journal"],
    },
    "sales": {
        "name": "Sales Agent",
        "description": "Public-facing agent for product inquiries and lead qualification",
        "config": {
            "agent": {"role": "sales_agent"},
            "notebooks": {"enabled": False},
            "kanban": {"enabled": False},
            "access": {"supervised": False},
            "mesh": {"enabled": True},
        },
        "skills": ["qualify-lead", "handle-objections", "product-demo"],
    },
}


def get_profile(name: str) -> dict | None:
    """Get a profile by name."""
    return PROFILES.get(name)


def list_profiles() -> list[dict]:
    """List all available profiles."""
    return [
        {"id": k, "name": v["name"], "description": v["description"]}
        for k, v in PROFILES.items()
    ]
