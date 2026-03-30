---
priority: 4
always_include: false
---
[simple]
skip_rag: true
skip_reranker: true
skip_documents: true
skip_profile: true
skip_experiences: true
tools: all

[standard]
skip_rag: false
skip_documents: false
skip_profile: false
tools: all

[document_query]
skip_rag: false
skip_documents: false
skip_profile: false
tools: all

[complex]
skip_rag: false
skip_documents: false
skip_profile: false
tools: all

[planning]
skip_rag: false
skip_documents: true
skip_profile: false
tools: all
