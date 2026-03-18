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
tools: activate_skill, send_notification

[standard]
skip_rag: false
skip_documents: false
skip_profile: false
tools: all

[document_query]
skip_rag: false
skip_documents: false
skip_profile: false
tools: run_code, activate_skill, send_notification, check_plan, update_plan, remember_fact

[complex]
skip_rag: false
skip_documents: false
skip_profile: false
tools: run_code, decompose_query, check_plan, update_plan, activate_skill, send_notification, remember_fact

[planning]
skip_rag: false
skip_documents: true
skip_profile: false
tools: decompose_query, check_plan, update_plan, activate_skill, send_notification, create_goal, create_todo, create_reminder
