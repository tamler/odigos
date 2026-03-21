"""Providers plugin -- placeholder for additional LLM/embedding providers."""


def register(ctx):
    return {"status": "available", "error_message": "No additional providers configured"}
