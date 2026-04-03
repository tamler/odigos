"""Quiz and assessment tool for education mode."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from odigos.db import Database
from odigos.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class CreateQuizTool(BaseTool):
    name = "create_quiz"
    category = "analysis"
    description = (
        "Create a quiz or assessment for the student. Provide a title, questions "
        "with multiple choice options, and correct answers. The quiz is presented "
        "to the student interactively. Do not use for free-form Q&A — this tool is for structured multiple-choice assessments only."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Quiz title"},
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "correct": {"type": "integer", "description": "Index of correct option (0-based)"},
                        "explanation": {"type": "string", "description": "Why this answer is correct"},
                    },
                    "required": ["question", "options", "correct"],
                },
                "description": "List of quiz questions",
            },
        },
        "required": ["title", "questions"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        title = params.get("title", "Quiz")
        questions = params.get("questions", [])
        conversation_id = params.get("_conversation_id")

        if not questions:
            return ToolResult(success=False, data="", error="At least one question is required")

        quiz_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Store the quiz for tracking
        try:
            await self.db.execute(
                "INSERT INTO artifacts (id, conversation_id, filename, content_type, file_size, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (quiz_id, conversation_id, f"{title}.json", "application/json",
                 len(json.dumps(questions)), now),
            )
        except Exception:
            logger.debug("Could not store quiz metadata", exc_info=True)

        # Format the quiz for presentation
        lines = [f"**{title}** ({len(questions)} questions)\n"]
        for i, q in enumerate(questions):
            lines.append(f"**Q{i+1}.** {q['question']}")
            for j, opt in enumerate(q.get("options", [])):
                lines.append(f"  {chr(65+j)}) {opt}")
            lines.append("")

        return ToolResult(
            success=True,
            data="\n".join(lines),
            side_effect={
                "quiz": {
                    "id": quiz_id,
                    "title": title,
                    "questions": questions,
                    "total": len(questions),
                },
                "suggested_actions": [f"{chr(65+j)}) {q['options'][j]}" for j, _ in enumerate(questions[0].get("options", []))] if questions else [],
            },
        )


class GradeResponseTool(BaseTool):
    name = "grade_response"
    category = "analysis"
    description = (
        "Grade a student's answer to a quiz question. Provide feedback and "
        "track their score. Use this after the student answers a question."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question that was asked"},
            "student_answer": {"type": "string", "description": "What the student answered"},
            "correct_answer": {"type": "string", "description": "The correct answer"},
            "is_correct": {"type": "string", "enum": ["true", "false"], "description": "Whether the student's answer was correct, default 'false'"},
            "feedback": {"type": "string", "description": "Constructive feedback for the student"},
            "topic": {"type": "string", "description": "The topic/subject area of this question"},
        },
        "required": ["question", "student_answer", "correct_answer", "is_correct", "feedback"],
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    async def execute(self, params: dict) -> ToolResult:
        is_correct = str(params.get("is_correct", "false")).lower() == "true"
        feedback = params.get("feedback", "")
        topic = params.get("topic", "general")
        conversation_id = params.get("_conversation_id")

        # Store the grade as a fact for the student's learning profile
        try:
            from odigos.tools.remember_fact import RememberFactTool
            # We'll just log it -- the evaluator and memory system will pick it up
            result_text = "correct" if is_correct else "incorrect"
            logger.info("Grade: %s on topic '%s' (%s)", result_text, topic, feedback[:100])
        except Exception:
            pass

        emoji = "Correct!" if is_correct else "Not quite."
        return ToolResult(
            success=True,
            data=f"{emoji} {feedback}",
        )
