from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.documents import Document


class StudyMateState(TypedDict):
    # Routing
    action: str  # "ingest" | "ask_doubt" | "take_quiz" | "replan" | "view_plan"

    # Student context
    student_id: str
    subject: str
    collection_name: str

    # Cross-agent memory (injected by orchestrator from SQLite)
    agent_memories: list[dict]

    # Ingest inputs/outputs
    syllabus_bytes: bytes
    syllabus_filename: str
    syllabus_docs: list[Document]
    extracted_topics: list[str]

    # Study duration (from user input)
    study_duration_days: int
    exam_date: str

    # Study plan
    study_plan: dict
    plan_revision: int

    # Doubt / RAG
    user_question: str
    rag_context: str
    rag_answer: str

    # Quiz
    quiz_topic: str
    num_questions: int
    quiz_questions: list[dict]
    student_answers: list[str]
    quiz_result: dict

    # Performance
    topic_performance: dict
    weak_topics: list[str]
    needs_replan: bool

    # Error handling
    error: str
