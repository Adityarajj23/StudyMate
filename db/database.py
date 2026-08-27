from __future__ import annotations

import uuid
from datetime import datetime
from functools import lru_cache
from typing import Any

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection

from config import get_settings


# ── Connection ─────────────────────────────────────────────


@lru_cache(maxsize=1)
def _get_client() -> MongoClient:
    uri = get_settings().mongodb_uri
    return MongoClient(uri)


def _db():
    return _get_client()[get_settings().mongodb_db_name]


def _col(name: str) -> Collection:
    return _db()[name]


# ── Init ───────────────────────────────────────────────────


def init_db() -> None:
    """Create indexes (idempotent — safe to call on every startup)."""
    # students
    _col("students").create_index("name", unique=True)

    # subjects
    _col("subjects").create_index(
        [("student_id", ASCENDING), ("name", ASCENDING)], unique=True
    )

    # study_plans
    _col("study_plans").create_index(
        [("student_id", ASCENDING), ("subject_id", ASCENDING), ("revision", DESCENDING)]
    )

    # completed_topics
    _col("completed_topics").create_index(
        [("student_id", ASCENDING), ("subject_id", ASCENDING), ("topic_name", ASCENDING)],
        unique=True,
    )

    # topic_performance
    _col("topic_performance").create_index(
        [("student_id", ASCENDING), ("subject_id", ASCENDING), ("topic_name", ASCENDING)],
        unique=True,
    )

    # quiz_results
    _col("quiz_results").create_index("quiz_id", unique=True)
    _col("quiz_results").create_index(
        [("student_id", ASCENDING), ("subject_id", ASCENDING), ("created_at", DESCENDING)]
    )

    # agent_memory
    _col("agent_memory").create_index(
        [("student_id", ASCENDING), ("subject_id", ASCENDING), ("created_at", DESCENDING)]
    )


# ── Helpers ────────────────────────────────────────────────


def _strip_id(doc: dict | None) -> dict | None:
    """Remove MongoDB internal _id before returning to callers."""
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


# ── Students ──────────────────────────────────────────────


def get_or_create_student(name: str) -> str:
    col = _col("students")
    doc = col.find_one({"name": name})
    if doc:
        return doc["id"]
    student_id = str(uuid.uuid4())
    col.insert_one(
        {"id": student_id, "name": name, "created_at": datetime.utcnow().isoformat()}
    )
    return student_id


def get_student(student_id: str) -> dict | None:
    doc = _col("students").find_one({"id": student_id})
    return _strip_id(doc)


# ── Subjects ──────────────────────────────────────────────


def save_subject(
    student_id: str,
    name: str,
    collection_name: str,
    topics: list[str],
) -> str:
    col = _col("subjects")
    # Generate a stable id on first insert
    existing = col.find_one({"student_id": student_id, "name": name}, {"id": 1})
    subject_id = existing["id"] if existing else str(uuid.uuid4())
    col.update_one(
        {"student_id": student_id, "name": name},
        {
            "$set": {
                "collection_name": collection_name,
                "topics": topics,
            },
            "$setOnInsert": {
                "id": subject_id,
                "student_id": student_id,
                "name": name,
                "created_at": datetime.utcnow().isoformat(),
            },
        },
        upsert=True,
    )
    return subject_id


def get_subjects(student_id: str) -> list[dict]:
    docs = _col("subjects").find(
        {"student_id": student_id}, sort=[("name", ASCENDING)]
    )
    result = []
    for doc in docs:
        d = _strip_id(doc)
        # Ensure topics is always a list
        if not isinstance(d.get("topics"), list):
            d["topics"] = []
        result.append(d)
    return result


def get_subject(student_id: str, subject_name: str) -> dict | None:
    doc = _col("subjects").find_one({"student_id": student_id, "name": subject_name})
    if not doc:
        return None
    d = _strip_id(doc)
    if not isinstance(d.get("topics"), list):
        d["topics"] = []
    return d


# ── Study Plans ───────────────────────────────────────────


def save_study_plan(
    student_id: str, subject_id: str, revision: int, plan_data: dict
) -> str:
    doc = {
        "plan_id": str(uuid.uuid4()),
        "student_id": student_id,
        "subject_id": subject_id,
        "revision": revision,
        "plan_data": plan_data,
        "created_at": datetime.utcnow().isoformat(),
    }
    _col("study_plans").insert_one(doc)
    return doc["plan_id"]


def get_latest_plan(student_id: str, subject_id: str) -> dict | None:
    doc = _col("study_plans").find_one(
        {"student_id": student_id, "subject_id": subject_id},
        sort=[("revision", DESCENDING)],
    )
    return _strip_id(doc)


def get_plan_history(student_id: str, subject_id: str) -> list[dict]:
    docs = _col("study_plans").find(
        {"student_id": student_id, "subject_id": subject_id},
        sort=[("revision", DESCENDING)],
    )
    return [_strip_id(d) for d in docs]


# ── Topic Performance ─────────────────────────────────────


def upsert_topic_performance(
    student_id: str,
    subject_id: str,
    topic_name: str,
    new_score: float,
) -> dict:
    col = _col("topic_performance")
    doc = col.find_one(
        {"student_id": student_id, "subject_id": subject_id, "topic_name": topic_name}
    )

    now = datetime.utcnow().isoformat()

    from models.schemas import MasteryLevel

    if doc:
        history: list[float] = doc.get("score_history", [])
        history.append(new_score)
        attempts = doc.get("attempts", 0) + 1
        best = max(doc.get("best_score", 0.0), new_score)
        avg = sum(history) / len(history)
        level = MasteryLevel.from_score(avg).value

        col.update_one(
            {"student_id": student_id, "subject_id": subject_id, "topic_name": topic_name},
            {
                "$set": {
                    "best_score": best,
                    "average_score": avg,
                    "attempts": attempts,
                    "mastery_level": level,
                    "score_history": history,
                    "last_tested": now,
                }
            },
        )
    else:
        level = MasteryLevel.from_score(new_score).value
        col.update_one(
            {"student_id": student_id, "subject_id": subject_id, "topic_name": topic_name},
            {
                "$setOnInsert": {
                    "student_id": student_id,
                    "subject_id": subject_id,
                    "topic_name": topic_name,
                    "best_score": new_score,
                    "average_score": new_score,
                    "attempts": 1,
                    "mastery_level": level,
                    "score_history": [new_score],
                    "last_tested": now,
                }
            },
            upsert=True,
        )

    updated = col.find_one(
        {"student_id": student_id, "subject_id": subject_id, "topic_name": topic_name}
    )
    return _strip_id(updated)


def get_topic_performance(student_id: str, subject_id: str) -> list[dict]:
    docs = _col("topic_performance").find(
        {"student_id": student_id, "subject_id": subject_id},
        sort=[("topic_name", ASCENDING)],
    )
    return [_strip_id(d) for d in docs]


# ── Quiz Results ──────────────────────────────────────────


def save_quiz_result(
    student_id: str,
    subject_id: str,
    topic: str,
    questions: list[dict],
    student_answers: list[str],
    score: float,
    correct_count: int,
    total_count: int,
    weak_areas: list[str],
) -> str:
    quiz_id = str(uuid.uuid4())
    _col("quiz_results").insert_one(
        {
            "quiz_id": quiz_id,
            "student_id": student_id,
            "subject_id": subject_id,
            "topic": topic,
            "questions": questions,
            "student_answers": student_answers,
            "score": score,
            "correct_count": correct_count,
            "total_count": total_count,
            "weak_areas": weak_areas,
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    return quiz_id


def get_quiz_history(student_id: str, subject_id: str) -> list[dict]:
    docs = _col("quiz_results").find(
        {"student_id": student_id, "subject_id": subject_id},
        sort=[("created_at", DESCENDING)],
    )
    return [_strip_id(d) for d in docs]


# ── Agent Memory ──────────────────────────────────────────


def add_agent_memory(
    student_id: str,
    subject_id: str,
    agent_name: str,
    memory_type: str,
    content: str,
) -> str:
    memory_id = str(uuid.uuid4())
    _col("agent_memory").insert_one(
        {
            "memory_id": memory_id,
            "student_id": student_id,
            "subject_id": subject_id,
            "agent_name": agent_name,
            "memory_type": memory_type,
            "content": content,
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    return memory_id


def get_agent_memories(
    student_id: str,
    subject_id: str,
    agent_name: str | None = None,
    limit: int = 20,
) -> list[dict]:
    query: dict[str, Any] = {"student_id": student_id, "subject_id": subject_id}
    if agent_name:
        query["agent_name"] = agent_name
    docs = (
        _col("agent_memory")
        .find(query, sort=[("created_at", DESCENDING)])
        .limit(limit)
    )
    return [_strip_id(d) for d in docs]


# ── Completed Topics ──────────────────────────────────────


def mark_topic_completed(student_id: str, subject_id: str, topic_name: str) -> None:
    _col("completed_topics").update_one(
        {"student_id": student_id, "subject_id": subject_id, "topic_name": topic_name},
        {
            "$setOnInsert": {
                "student_id": student_id,
                "subject_id": subject_id,
                "topic_name": topic_name,
                "completed_at": datetime.utcnow().isoformat(),
            }
        },
        upsert=True,
    )


def unmark_topics_completed(
    student_id: str, subject_id: str, topic_names: list[str]
) -> None:
    if not topic_names:
        return
    _col("completed_topics").delete_many(
        {
            "student_id": student_id,
            "subject_id": subject_id,
            "topic_name": {"$in": topic_names},
        }
    )


def get_completed_topics(student_id: str, subject_id: str) -> list[str]:
    docs = _col("completed_topics").find(
        {"student_id": student_id, "subject_id": subject_id},
        {"topic_name": 1},
    )
    return [d["topic_name"] for d in docs]
