from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MasteryLevel(str, Enum):
    NOT_STARTED = "not_started"
    NEEDS_WORK = "needs_work"
    DEVELOPING = "developing"
    PROFICIENT = "proficient"
    MASTERED = "mastered"

    @classmethod
    def from_score(cls, score: float) -> MasteryLevel:
        if score >= 80:
            return cls.MASTERED
        if score >= 60:
            return cls.PROFICIENT
        if score >= 40:
            return cls.DEVELOPING
        if score > 0:
            return cls.NEEDS_WORK
        return cls.NOT_STARTED


class TopicPerformance(BaseModel):
    topic_name: str
    best_score: float = 0.0
    average_score: float = 0.0
    attempts: int = 0
    last_tested: datetime | None = None
    mastery_level: MasteryLevel = MasteryLevel.NOT_STARTED
    score_history: list[float] = Field(default_factory=list)


class QuizQuestion(BaseModel):
    question: str
    options: list[str]
    correct_answer: str
    explanation: str
    topic: str


class QuizResult(BaseModel):
    quiz_id: str
    topic: str
    questions: list[QuizQuestion]
    student_answers: list[str]
    score: float
    correct_count: int
    total_count: int
    weak_areas: list[str]
    timestamp: datetime = Field(default_factory=datetime.now)


class DayPlan(BaseModel):
    day: int
    date: str
    topics: list[str]
    status: str = "upcoming"
    priority: str = "normal"
    estimated_hours: float = 2.0


class StudyPlan(BaseModel):
    subject: str
    total_days: int
    start_date: str
    days: list[DayPlan]
    revision: int = 1
    notes: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
