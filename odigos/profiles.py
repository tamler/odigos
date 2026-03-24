"""Agent profiles -- pre-built configurations for common use cases.

Profiles set the agent's role, enabled features, default skills, and
behavior. Applied on first setup or when switching profiles via settings.
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
            "education": {"enabled": False},
        },
        "skills": ["deep-research", "journal", "kanban", "summarize-doc", "summarize-page"],
    },
    "student": {
        "name": "Student Tutor",
        "description": "Personal AI tutor that adapts to your learning style",
        "config": {
            "agent": {"role": "student"},
            "notebooks": {"enabled": True},
            "kanban": {"enabled": True},
            "education": {"enabled": True, "role": "student"},
        },
        "skills": ["tutor", "deep-research", "journal", "kanban"],
    },
    "teacher": {
        "name": "Teacher",
        "description": "Manages curriculum and student progress across the mesh",
        "config": {
            "agent": {"role": "teacher"},
            "notebooks": {"enabled": True},
            "kanban": {"enabled": True},
            "education": {"enabled": True, "role": "teacher"},
            "mesh": {"enabled": True},
        },
        "skills": ["teacher", "deep-research", "kanban"],
    },
    "researcher": {
        "name": "Researcher",
        "description": "Deep research and document analysis specialist",
        "config": {
            "agent": {"role": "researcher"},
            "notebooks": {"enabled": True},
            "kanban": {"enabled": False},
            "education": {"enabled": False},
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
            "education": {"enabled": False},
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
