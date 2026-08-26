from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from agents.content_agent import create_content_agent
from agents.evaluator_agent import create_evaluator_agent
from agents.planner_agent import create_planner_agent
from chains.topic_extraction_chain import extract_topics
from db.database import (
    add_agent_memory,
    get_agent_memories,
    get_latest_plan,
    get_subject,
    get_topic_performance,
    save_study_plan,
    save_subject,
    upsert_topic_performance,
    save_quiz_result,
)
from ingestion.pdf_loader import extract_full_text, load_pdf
from ingestion.vector_store import (
    create_or_update_collection,
    sanitize_collection_name,
    search_collection,
)
from models.state import StudyMateState
from tools.rag_search_tool import create_rag_search_tool


def _extract_text(content) -> str:
    """Extract plain text from an LLM response content field.

    Newer Gemini models return content as a list of dicts like
    [{'type': 'text', 'text': '...'}] instead of a plain string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text", str(item)))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


# ── Orchestrator ──────────────────────────────────────────


def orchestrator(state: StudyMateState) -> dict:
    student_id = state.get("student_id", "")
    subject = state.get("subject", "")
    memories = []

    if student_id and subject:
        subj = get_subject(student_id, subject)
        if subj:
            raw = get_agent_memories(student_id, subj["id"], limit=15)
            memories = raw

    return {"agent_memories": memories}


def route_by_action(state: StudyMateState) -> str:
    return state.get("action", "view_plan")


# ── Ingest Subgraph ──────────────────────────────────────


def parse_syllabus(state: StudyMateState) -> dict:
    pdf_bytes = state["syllabus_bytes"]
    filename = state.get("syllabus_filename", "syllabus.pdf")
    docs = load_pdf(pdf_bytes, source=filename)
    return {"syllabus_docs": docs}


def embed_documents(state: StudyMateState) -> dict:
    subject = state["subject"]
    collection_name = sanitize_collection_name(subject)
    docs = state["syllabus_docs"]
    create_or_update_collection(collection_name, docs)
    return {"collection_name": collection_name}


def run_extract_topics(state: StudyMateState) -> dict:
    full_text = extract_full_text(state["syllabus_bytes"])
    topics = extract_topics(full_text)
    return {"extracted_topics": topics}


def generate_initial_plan(state: StudyMateState, config: RunnableConfig) -> dict:
    topics = state["extracted_topics"]
    subject = state["subject"]
    student_id = state["student_id"]

    start_date = datetime.now() + timedelta(days=1)
    total_days = state.get("study_duration_days") or max(len(topics), 7)

    message = (
        f"Create a {total_days}-day study plan for the subject '{subject}'.\n\n"
        f"Topics to cover:\n{json.dumps(topics, indent=2)}\n\n"
        f"Start date: {start_date.strftime('%Y-%m-%d')}\n"
    )

    if state.get("exam_date"):
        message += f"Exam date: {state['exam_date']}. The plan MUST complete before this date.\n"

    message += "This is the initial plan — no performance data yet."

    agent = create_planner_agent()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config=config,
    )
    raw_output = _extract_text(result["messages"][-1].content)

    try:
        cleaned = raw_output.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            cleaned = cleaned.rsplit("```", 1)[0]
        plan_data = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        plan_data = {
            "total_days": total_days,
            "days": [
                {
                    "day": i + 1,
                    "date": (start_date + timedelta(days=i)).strftime("%Y-%m-%d"),
                    "topics": [topics[i]] if i < len(topics) else ["Revision"],
                    "priority": "normal",
                    "estimated_hours": 2.0,
                }
                for i in range(total_days)
            ],
            "notes": "Fallback linear plan — LLM output was not valid JSON.",
        }

    return {"study_plan": plan_data, "plan_revision": 1}


def save_ingest_to_db(state: StudyMateState) -> dict:
    student_id = state["student_id"]
    subject = state["subject"]
    collection_name = state["collection_name"]
    topics = state["extracted_topics"]
    plan = state["study_plan"]

    subject_id = save_subject(student_id, subject, collection_name, topics)
    save_study_plan(student_id, subject_id, 1, plan)
    add_agent_memory(
        student_id, subject_id, "orchestrator", "observation",
        f"Syllabus ingested: {len(topics)} topics extracted, initial plan created.",
    )
    return {}


# ── Doubt Subgraph ────────────────────────────────────────


def rag_retrieve(state: StudyMateState) -> dict:
    collection_name = state.get("collection_name", "")
    if not collection_name:
        subj = get_subject(state["student_id"], state["subject"])
        collection_name = subj["collection_name"] if subj else ""

    if not collection_name:
        return {"rag_context": "No course material uploaded yet."}

    results = search_collection(collection_name, state["user_question"], k=4)
    context_parts = []
    for i, doc in enumerate(results, 1):
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", "?")
        context_parts.append(f"[{i}] (source: {source}, page: {page})\n{doc.page_content}")

    return {"rag_context": "\n\n".join(context_parts) if context_parts else "No relevant content found."}


def run_content_agent(state: StudyMateState, config: RunnableConfig) -> dict:
    collection_name = state.get("collection_name", "")
    if not collection_name:
        subj = get_subject(state["student_id"], state["subject"])
        collection_name = subj["collection_name"] if subj else ""

    memories = state.get("agent_memories", [])
    memory_context = ""
    if memories:
        recent = [m for m in memories if m["agent_name"] in ("content", "evaluator")][:5]
        if recent:
            memory_context = "\n\nPrevious observations about this student:\n" + "\n".join(
                f"- [{m['agent_name']}] {m['content']}" for m in recent
            )

    question = state["user_question"]
    rag_context = state.get("rag_context", "")

    message = (
        f"Student's question: {question}\n\n"
        f"Retrieved context from course material:\n{rag_context}"
        f"{memory_context}"
    )

    tools = [create_rag_search_tool(collection_name)] if collection_name else []
    agent = create_content_agent(tools=tools)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config=config,
    )
    answer = _extract_text(result["messages"][-1].content)

    subj = get_subject(state["student_id"], state["subject"])
    if subj:
        add_agent_memory(
            state["student_id"], subj["id"], "content", "observation",
            f"Student asked: '{question[:100]}'"
        )

    return {"rag_answer": answer}


# ── Quiz Subgraph ─────────────────────────────────────────


def run_generate_quiz(state: StudyMateState, config: RunnableConfig) -> dict:
    topic = state["quiz_topic"]
    num_questions = state.get("num_questions", 5)
    collection_name = state.get("collection_name", "")

    if not collection_name:
        subj = get_subject(state["student_id"], state["subject"])
        collection_name = subj["collection_name"] if subj else ""

    message = (
        f"Generate {num_questions} MCQ questions on the topic: '{topic}'.\n"
        f"Subject: {state['subject']}\n"
        f"Use the rag_search tool to find relevant content from the course material "
        f"to create accurate, syllabus-aligned questions."
    )

    tools = [create_rag_search_tool(collection_name)] if collection_name else []
    agent = create_evaluator_agent(tools=tools)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config=config,
    )
    raw = _extract_text(result["messages"][-1].content)

    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            cleaned = cleaned.rsplit("```", 1)[0]
        questions = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        questions = []

    return {"quiz_questions": questions}


def run_grade_quiz(state: StudyMateState, config: RunnableConfig) -> dict:
    questions = state["quiz_questions"]
    answers = state["student_answers"]
    topic = state["quiz_topic"]
    collection_name = state.get("collection_name", "")

    if not collection_name:
        subj = get_subject(state["student_id"], state["subject"])
        collection_name = subj["collection_name"] if subj else ""

    message = (
        f"Grade the following quiz answers on '{topic}'.\n\n"
        f"Questions:\n{json.dumps(questions, indent=2)}\n\n"
        f"Student's answers:\n{json.dumps(answers, indent=2)}\n\n"
        f"Provide the score and identify weak areas."
    )

    tools = [create_rag_search_tool(collection_name)] if collection_name else []
    agent = create_evaluator_agent(tools=tools)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config=config,
    )
    raw = _extract_text(result["messages"][-1].content)

    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            cleaned = cleaned.rsplit("```", 1)[0]
        quiz_result = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        correct = sum(
            1 for q, a in zip(questions, answers)
            if a.strip().lower() == q.get("correct_answer", "").strip().lower()
        )
        total = len(questions)
        quiz_result = {
            "score": (correct / total * 100) if total > 0 else 0,
            "correct_count": correct,
            "total_count": total,
            "weak_areas": [topic] if correct < total * 0.6 else [],
            "per_question": [],
        }

    return {"quiz_result": quiz_result}


def update_performance(state: StudyMateState) -> dict:
    student_id = state["student_id"]
    subject = state["subject"]
    topic = state["quiz_topic"]
    quiz_result = state["quiz_result"]

    subj = get_subject(student_id, subject)
    if not subj:
        return {"topic_performance": {}, "weak_topics": []}

    subject_id = subj["id"]
    score = quiz_result.get("score", 0)

    upsert_topic_performance(student_id, subject_id, topic, score)

    save_quiz_result(
        student_id=student_id,
        subject_id=subject_id,
        topic=topic,
        questions=state.get("quiz_questions", []),
        student_answers=state.get("student_answers", []),
        score=score,
        correct_count=quiz_result.get("correct_count", 0),
        total_count=quiz_result.get("total_count", 0),
        weak_areas=quiz_result.get("weak_areas", []),
    )

    all_perf = get_topic_performance(student_id, subject_id)
    perf_dict = {p["topic_name"]: p for p in all_perf}
    weak = [p["topic_name"] for p in all_perf if p["average_score"] < 60]

    add_agent_memory(
        student_id, subject_id, "evaluator", "observation",
        f"Quiz on '{topic}': score {score:.0f}%. "
        f"Weak areas: {', '.join(quiz_result.get('weak_areas', [])) or 'none'}.",
    )

    return {"topic_performance": perf_dict, "weak_topics": weak}


def check_replan(state: StudyMateState) -> dict:
    weak = state.get("weak_topics", [])
    needs = len(weak) > 0
    return {"needs_replan": needs}


def should_replan(state: StudyMateState) -> bool:
    return state.get("needs_replan", False)


# ── Replan ────────────────────────────────────────────────


def run_replan(state: StudyMateState, config: RunnableConfig) -> dict:
    student_id = state["student_id"]
    subject = state["subject"]

    subj = get_subject(student_id, subject)
    if not subj:
        return {"error": "Subject not found for replanning."}

    subject_id = subj["id"]
    topics = subj["topics"]
    all_perf = get_topic_performance(student_id, subject_id)
    memories = get_agent_memories(student_id, subject_id, limit=10)

    current_plan_row = get_latest_plan(student_id, subject_id)
    current_revision = current_plan_row["revision"] if current_plan_row else 0
    new_revision = current_revision + 1

    perf_summary = "\n".join(
        f"- {p['topic_name']}: avg {p['average_score']:.0f}%, "
        f"mastery={p['mastery_level']}, attempts={p['attempts']}"
        for p in all_perf
    ) or "No performance data yet."

    memory_summary = "\n".join(
        f"- [{m['agent_name']}] {m['content']}" for m in memories[:10]
    ) or "No agent observations."

    start_date = datetime.now() + timedelta(days=1)
    remaining_days = max(len(topics) - len([p for p in all_perf if p["mastery_level"] == "mastered"]), 5)

    message = (
        f"REVISE the study plan for '{subject}' (Revision #{new_revision}).\n\n"
        f"All topics: {json.dumps(topics)}\n\n"
        f"Student performance:\n{perf_summary}\n\n"
        f"Agent observations:\n{memory_summary}\n\n"
        f"Start date: {start_date.strftime('%Y-%m-%d')}\n"
        f"Available days: {remaining_days}\n\n"
        f"IMPORTANT: Prioritize weak topics (score < 60%) — move them EARLIER "
        f"and mark them as 'high' priority. Add revision sessions for struggling topics."
    )

    agent = create_planner_agent()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config=config,
    )
    raw = _extract_text(result["messages"][-1].content)

    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            cleaned = cleaned.rsplit("```", 1)[0]
        plan_data = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        plan_data = state.get("study_plan", {})
        plan_data["notes"] = "Replan failed — LLM output was not valid JSON. Keeping previous plan."

    save_study_plan(student_id, subject_id, new_revision, plan_data)

    weak = state.get("weak_topics", [])
    if weak:
        from db.database import unmark_topics_completed
        unmark_topics_completed(student_id, subject_id, weak)

    add_agent_memory(
        student_id, subject_id, "planner", "recommendation",
        f"Plan revised to v{new_revision}. Weak topics prioritized: {', '.join(weak)}",
    )

    return {"study_plan": plan_data, "plan_revision": new_revision}


# ── Graph Assembly ────────────────────────────────────────


def build_graph():
    g = StateGraph(StudyMateState)

    # Orchestrator
    g.add_node("orchestrator", orchestrator)

    # Ingest subgraph
    g.add_node("parse_syllabus", parse_syllabus)
    g.add_node("embed_documents", embed_documents)
    g.add_node("extract_topics", run_extract_topics)
    g.add_node("generate_initial_plan", generate_initial_plan)
    g.add_node("save_ingest_to_db", save_ingest_to_db)

    # Doubt subgraph
    g.add_node("rag_retrieve", rag_retrieve)
    g.add_node("content_agent", run_content_agent)

    # Quiz subgraph
    g.add_node("generate_quiz", run_generate_quiz)
    g.add_node("grade_quiz", run_grade_quiz)
    g.add_node("update_performance", update_performance)
    g.add_node("check_replan", check_replan)

    # Shared
    g.add_node("replan", run_replan)

    # Edges
    g.add_edge(START, "orchestrator")
    g.add_conditional_edges("orchestrator", route_by_action, {
        "ingest": "parse_syllabus",
        "ask_doubt": "rag_retrieve",
        "generate_quiz": "generate_quiz",
        "grade_quiz": "grade_quiz",
        "replan": "replan",
        "view_plan": END,
    })

    # Ingest chain
    g.add_edge("parse_syllabus", "embed_documents")
    g.add_edge("embed_documents", "extract_topics")
    g.add_edge("extract_topics", "generate_initial_plan")
    g.add_edge("generate_initial_plan", "save_ingest_to_db")
    g.add_edge("save_ingest_to_db", END)

    # Doubt chain
    g.add_edge("rag_retrieve", "content_agent")
    g.add_edge("content_agent", END)

    # Quiz generate — stops after generating questions
    g.add_edge("generate_quiz", END)

    # Quiz grade — enters at grading, flows through performance + replan
    g.add_edge("grade_quiz", "update_performance")
    g.add_edge("update_performance", "check_replan")
    g.add_conditional_edges("check_replan", should_replan, {
        True: "replan",
        False: END,
    })
    g.add_edge("replan", END)

    return g.compile()
