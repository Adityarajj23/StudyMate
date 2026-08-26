from __future__ import annotations

from typing import Callable

from db.database import get_subject, init_db
from graph import build_graph

init_db()

_graph = build_graph()


def _build_state(**kwargs) -> dict:
    defaults = {
        "action": "view_plan",
        "student_id": "",
        "subject": "",
        "collection_name": "",
        "agent_memories": [],
        "syllabus_bytes": b"",
        "syllabus_filename": "",
        "syllabus_docs": [],
        "extracted_topics": [],
        "study_duration_days": 0,
        "exam_date": "",
        "study_plan": {},
        "plan_revision": 0,
        "user_question": "",
        "rag_context": "",
        "rag_answer": "",
        "quiz_topic": "",
        "num_questions": 5,
        "quiz_questions": [],
        "student_answers": [],
        "quiz_result": {},
        "topic_performance": {},
        "weak_topics": [],
        "needs_replan": False,
        "error": "",
    }
    defaults.update(kwargs)
    return defaults


def _resolve_collection(student_id: str, subject: str) -> str:
    subj = get_subject(student_id, subject)
    return subj["collection_name"] if subj else ""


def run_ingest(
    syllabus_bytes: bytes,
    syllabus_filename: str,
    student_id: str,
    subject: str,
    study_duration_days: int = 0,
    exam_date: str = "",
    on_step: Callable[[str, str], None] | None = None,
) -> dict:
    state = _build_state(
        action="ingest",
        student_id=student_id,
        subject=subject,
        syllabus_bytes=syllabus_bytes,
        syllabus_filename=syllabus_filename,
        study_duration_days=study_duration_days,
        exam_date=exam_date,
    )

    final_state = {}
    for update in _graph.stream(state, stream_mode="updates"):
        for node_name, node_output in update.items():
            if node_output:
                final_state.update(node_output)
            if on_step:
                on_step(node_name, "completed")

    return final_state


def run_doubt(
    question: str,
    student_id: str,
    subject: str,
    on_step: Callable[[str, str], None] | None = None,
) -> str:
    collection_name = _resolve_collection(student_id, subject)
    state = _build_state(
        action="ask_doubt",
        student_id=student_id,
        subject=subject,
        collection_name=collection_name,
        user_question=question,
    )

    final_state = {}
    for update in _graph.stream(state, stream_mode="updates"):
        for node_name, node_output in update.items():
            if node_output:
                final_state.update(node_output)
            if on_step:
                on_step(node_name, "completed")

    return final_state.get("rag_answer", "Sorry, I could not generate an answer.")


def run_generate_quiz(
    topic: str,
    student_id: str,
    subject: str,
    num_questions: int = 5,
    on_step: Callable[[str, str], None] | None = None,
) -> list[dict]:
    collection_name = _resolve_collection(student_id, subject)
    state = _build_state(
        action="generate_quiz",
        student_id=student_id,
        subject=subject,
        collection_name=collection_name,
        quiz_topic=topic,
        num_questions=num_questions,
    )

    final_state = {}
    for update in _graph.stream(state, stream_mode="updates"):
        for node_name, node_output in update.items():
            if node_output:
                final_state.update(node_output)
            if on_step:
                on_step(node_name, "completed")

    return final_state.get("quiz_questions", [])


def run_grade_and_replan(
    quiz_questions: list[dict],
    student_answers: list[str],
    quiz_topic: str,
    student_id: str,
    subject: str,
    on_step: Callable[[str, str], None] | None = None,
) -> dict:
    collection_name = _resolve_collection(student_id, subject)
    state = _build_state(
        action="grade_quiz",
        student_id=student_id,
        subject=subject,
        collection_name=collection_name,
        quiz_topic=quiz_topic,
        quiz_questions=quiz_questions,
        student_answers=student_answers,
    )

    final_state = {}
    for update in _graph.stream(state, stream_mode="updates"):
        for node_name, node_output in update.items():
            if node_output:
                final_state.update(node_output)
            if on_step:
                on_step(node_name, "completed")

    return final_state


def run_replan(
    student_id: str,
    subject: str,
    on_step: Callable[[str, str], None] | None = None,
) -> dict:
    collection_name = _resolve_collection(student_id, subject)
    state = _build_state(
        action="replan",
        student_id=student_id,
        subject=subject,
        collection_name=collection_name,
    )

    final_state = {}
    for update in _graph.stream(state, stream_mode="updates"):
        for node_name, node_output in update.items():
            if node_output:
                final_state.update(node_output)
            if on_step:
                on_step(node_name, "completed")

    return final_state
