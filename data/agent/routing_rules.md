---
priority: 85
always_include: false
exclude_from_prompt: true
---
# Routing rules control CONTEXT, not tools.
# Tool availability is handled by category in registry.py.
# Never add "tools:" lines here.

[simple]
skip_rag: true
skip_reranker: true
skip_documents: true
skip_profile: true
skip_experiences: true

[standard]
skip_rag: false
skip_documents: false
skip_profile: false

[document_query]
skip_rag: false
skip_documents: false
skip_profile: false

[complex]
skip_rag: false
skip_documents: false
skip_profile: false

[planning]
skip_rag: false
skip_documents: true
skip_profile: false
