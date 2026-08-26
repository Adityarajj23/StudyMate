from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "studymate.db"


@contextmanager
def _get_conn():
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS students (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT REFERENCES students(id),
                name TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                topics TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(student_id, name)
            );

            CREATE TABLE IF NOT EXISTS study_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT REFERENCES students(id),
                subject_id INTEGER REFERENCES subjects(id),
                revision INTEGER NOT NULL DEFAULT 1,
                plan_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS completed_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT REFERENCES students(id),
                subject_id INTEGER REFERENCES subjects(id),
                topic_name TEXT NOT NULL,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(student_id, subject_id, topic_name)
            );

            CREATE TABLE IF NOT EXISTS topic_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT REFERENCES students(id),
                subject_id INTEGER REFERENCES subjects(id),
                topic_name TEXT NOT NULL,
                best_score REAL DEFAULT 0,
                average_score REAL DEFAULT 0,
                attempts INTEGER DEFAULT 0,
                mastery_level TEXT DEFAULT 'not_started',
                score_history TEXT DEFAULT '[]',
                last_tested TIMESTAMP,
                UNIQUE(student_id, subject_id, topic_name)
            );

            CREATE TABLE IF NOT EXISTS quiz_results (
                id TEXT PRIMARY KEY,
                student_id TEXT REFERENCES students(id),
                subject_id INTEGER REFERENCES subjects(id),
                topic TEXT NOT NULL,
                questions TEXT NOT NULL,
                student_answers TEXT NOT NULL,
                score REAL NOT NULL,
                correct_count INTEGER NOT NULL,
                total_count INTEGER NOT NULL,
                weak_areas TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT REFERENCES students(id),
                subject_id INTEGER REFERENCES subjects(id),
                agent_name TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)


# ── Students ──────────────────────────────────────────────


def get_or_create_student(name: str) -> str:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM students WHERE name = ?", (name,)
        ).fetchone()
        if row:
            return row["id"]
        student_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO students (id, name) VALUES (?, ?)",
            (student_id, name),
        )
        return student_id


def get_student(student_id: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM students WHERE id = ?", (student_id,)
        ).fetchone()
        return dict(row) if row else None


# ── Subjects ──────────────────────────────────────────────


def save_subject(
    student_id: str,
    name: str,
    collection_name: str,
    topics: list[str],
) -> int:
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO subjects (student_id, name, collection_name, topics)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(student_id, name) DO UPDATE SET
                   collection_name = excluded.collection_name,
                   topics = excluded.topics""",
            (student_id, name, collection_name, json.dumps(topics)),
        )
        row = conn.execute(
            "SELECT id FROM subjects WHERE student_id = ? AND name = ?",
            (student_id, name),
        ).fetchone()
        return row["id"]


def get_subjects(student_id: str) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM subjects WHERE student_id = ? ORDER BY name",
            (student_id,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["topics"] = json.loads(d["topics"])
            result.append(d)
        return result


def get_subject(student_id: str, subject_name: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM subjects WHERE student_id = ? AND name = ?",
            (student_id, subject_name),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["topics"] = json.loads(d["topics"])
        return d


# ── Study Plans ───────────────────────────────────────────


def save_study_plan(
    student_id: str, subject_id: int, revision: int, plan_data: dict
) -> int:
    with _get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO study_plans (student_id, subject_id, revision, plan_data)
               VALUES (?, ?, ?, ?)""",
            (student_id, subject_id, revision, json.dumps(plan_data)),
        )
        return cursor.lastrowid


def get_latest_plan(student_id: str, subject_id: int) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM study_plans
               WHERE student_id = ? AND subject_id = ?
               ORDER BY revision DESC LIMIT 1""",
            (student_id, subject_id),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["plan_data"] = json.loads(d["plan_data"])
        return d


def get_plan_history(student_id: str, subject_id: int) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM study_plans
               WHERE student_id = ? AND subject_id = ?
               ORDER BY revision DESC""",
            (student_id, subject_id),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["plan_data"] = json.loads(d["plan_data"])
            result.append(d)
        return result


# ── Topic Performance ─────────────────────────────────────


def upsert_topic_performance(
    student_id: str,
    subject_id: int,
    topic_name: str,
    new_score: float,
) -> dict:
    with _get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM topic_performance
               WHERE student_id = ? AND subject_id = ? AND topic_name = ?""",
            (student_id, subject_id, topic_name),
        ).fetchone()

        now = datetime.now().isoformat()

        if row:
            history = json.loads(row["score_history"])
            history.append(new_score)
            attempts = row["attempts"] + 1
            best = max(row["best_score"], new_score)
            avg = sum(history) / len(history)
            from models.schemas import MasteryLevel
            level = MasteryLevel.from_score(avg).value

            conn.execute(
                """UPDATE topic_performance SET
                       best_score = ?, average_score = ?, attempts = ?,
                       mastery_level = ?, score_history = ?, last_tested = ?
                   WHERE student_id = ? AND subject_id = ? AND topic_name = ?""",
                (best, avg, attempts, level, json.dumps(history), now,
                 student_id, subject_id, topic_name),
            )
        else:
            from models.schemas import MasteryLevel
            level = MasteryLevel.from_score(new_score).value
            conn.execute(
                """INSERT INTO topic_performance
                       (student_id, subject_id, topic_name, best_score,
                        average_score, attempts, mastery_level, score_history, last_tested)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (student_id, subject_id, topic_name, new_score,
                 new_score, level, json.dumps([new_score]), now),
            )

        updated = conn.execute(
            """SELECT * FROM topic_performance
               WHERE student_id = ? AND subject_id = ? AND topic_name = ?""",
            (student_id, subject_id, topic_name),
        ).fetchone()
        d = dict(updated)
        d["score_history"] = json.loads(d["score_history"])
        return d


def get_topic_performance(student_id: str, subject_id: int) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM topic_performance
               WHERE student_id = ? AND subject_id = ?
               ORDER BY topic_name""",
            (student_id, subject_id),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["score_history"] = json.loads(d["score_history"])
            result.append(d)
        return result


# ── Quiz Results ──────────────────────────────────────────


def save_quiz_result(
    student_id: str,
    subject_id: int,
    topic: str,
    questions: list[dict],
    student_answers: list[str],
    score: float,
    correct_count: int,
    total_count: int,
    weak_areas: list[str],
) -> str:
    quiz_id = str(uuid.uuid4())
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO quiz_results
                   (id, student_id, subject_id, topic, questions, student_answers,
                    score, correct_count, total_count, weak_areas)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (quiz_id, student_id, subject_id, topic,
             json.dumps(questions), json.dumps(student_answers),
             score, correct_count, total_count, json.dumps(weak_areas)),
        )
    return quiz_id


def get_quiz_history(student_id: str, subject_id: int) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM quiz_results
               WHERE student_id = ? AND subject_id = ?
               ORDER BY created_at DESC""",
            (student_id, subject_id),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["questions"] = json.loads(d["questions"])
            d["student_answers"] = json.loads(d["student_answers"])
            d["weak_areas"] = json.loads(d["weak_areas"])
            result.append(d)
        return result


# ── Agent Memory ──────────────────────────────────────────


def add_agent_memory(
    student_id: str,
    subject_id: int,
    agent_name: str,
    memory_type: str,
    content: str,
) -> int:
    with _get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO agent_memory
                   (student_id, subject_id, agent_name, memory_type, content)
               VALUES (?, ?, ?, ?, ?)""",
            (student_id, subject_id, agent_name, memory_type, content),
        )
        return cursor.lastrowid


def get_agent_memories(
    student_id: str,
    subject_id: int,
    agent_name: str | None = None,
    limit: int = 20,
) -> list[dict]:
    with _get_conn() as conn:
        if agent_name:
            rows = conn.execute(
                """SELECT * FROM agent_memory
                   WHERE student_id = ? AND subject_id = ? AND agent_name = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (student_id, subject_id, agent_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM agent_memory
                   WHERE student_id = ? AND subject_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (student_id, subject_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]


# ── Completed Topics ──────────────────────────────────────


def mark_topic_completed(student_id: str, subject_id: int, topic_name: str) -> None:
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO completed_topics (student_id, subject_id, topic_name)
               VALUES (?, ?, ?)
               ON CONFLICT(student_id, subject_id, topic_name) DO NOTHING""",
            (student_id, subject_id, topic_name),
        )


def unmark_topics_completed(student_id: str, subject_id: int, topic_names: list[str]) -> None:
    if not topic_names:
        return
    with _get_conn() as conn:
        placeholders = ",".join("?" for _ in topic_names)
        conn.execute(
            f"""DELETE FROM completed_topics
                WHERE student_id = ? AND subject_id = ? AND topic_name IN ({placeholders})""",
            [student_id, subject_id] + topic_names,
        )


def get_completed_topics(student_id: str, subject_id: int) -> list[str]:
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT topic_name FROM completed_topics
               WHERE student_id = ? AND subject_id = ?""",
            (student_id, subject_id),
        ).fetchall()
        return [row["topic_name"] for row in rows]
