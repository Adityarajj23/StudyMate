from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_provider_label, get_settings
from db.database import (
    get_agent_memories,
    get_completed_topics,
    get_latest_plan,
    get_or_create_student,
    get_quiz_history,
    get_subject,
    get_subjects,
    get_topic_performance,
    init_db,
    mark_topic_completed,
)

init_db()


@st.cache_resource(show_spinner=False)
def _warmup_embeddings_bg():
    import threading

    def _load():
        try:
            from ingestion.vector_store import _get_embeddings
            emb = _get_embeddings()
            emb.embed_query("warmup")
        except Exception:
            pass

    t = threading.Thread(target=_load, daemon=True)
    t.start()
    return t


_warmup_embeddings_bg()

st.set_page_config(
    page_title="StudyMate",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────

st.markdown("""
<style>
    /* Navigation pills */
    div[data-testid="stHorizontalBlock"] .stRadio > div {
        gap: 0.5rem;
    }
    /* Priority badges */
    .priority-high { color: #ff4444; font-weight: bold; }
    .priority-revision { color: #4488ff; font-weight: bold; }
    .priority-normal { color: #888; }
    /* Metric cards */
    [data-testid="stMetric"] {
        border: 1px solid #333;
        border-radius: 8px;
        padding: 12px;
    }
</style>
""", unsafe_allow_html=True)


# ── Helper: page navigation ──────────────────────────────

_PAGES = ["Upload Syllabus", "Study Plan", "Ask Doubts", "Take Quiz", "Performance"]


def switch_page(page_name: str):
    try:
        st.query_params["page"] = page_name
    except Exception:
        pass


# ── Sidebar ───────────────────────────────────────────────

with st.sidebar:
    st.title("StudyMate")
    st.caption("Adaptive AI Study Planner")

    st.divider()

    student_name = st.text_input("Student Name", value=st.session_state.get("student_name", ""))
    if student_name:
        st.session_state.student_name = student_name
        st.session_state.student_id = get_or_create_student(student_name)

    student_id = st.session_state.get("student_id", "")
    subjects = get_subjects(student_id) if student_id else []
    subject_names = [s["name"] for s in subjects]

    if subject_names:
        selected_subject = st.selectbox("Subject", subject_names)
        st.session_state.selected_subject = selected_subject
    else:
        st.info("Upload a syllabus to get started")
        st.session_state.selected_subject = ""

    st.divider()

    s = get_settings()
    _PROVIDERS = {
        "Auto (Recommended)": "auto",
        f"Gemini ({s.gemini_model})": "gemini",
        f"Groq ({s.groq_model})": "groq",
        f"Ollama ({s.ollama_model})": "ollama",
    }
    current_provider = s.llm_provider.lower().strip()
    provider_values = list(_PROVIDERS.values())
    current_idx = provider_values.index(current_provider) if current_provider in provider_values else 0
    selected_label = st.selectbox("LLM Provider", list(_PROVIDERS.keys()), index=current_idx)
    new_provider = _PROVIDERS[selected_label]
    if new_provider != current_provider:
        os.environ["LLM_PROVIDER"] = new_provider
        get_settings.cache_clear()

    st.caption(f"Active: {get_provider_label()}")

# ── Guard ─────────────────────────────────────────────────

if not st.session_state.get("student_name"):
    st.title("Welcome to StudyMate")
    st.markdown(
        "Enter your **name** in the sidebar to begin. "
        "Then upload a syllabus to generate your personalized study plan."
    )
    st.stop()

# ── Page Navigation ───────────────────────────────────────

_default_page = _PAGES[0]
qp_page = st.query_params.get("page", "")
if qp_page in _PAGES:
    _default_page = qp_page
    st.query_params.clear()

active = st.radio(
    "nav", _PAGES, index=_PAGES.index(_default_page),
    horizontal=True, label_visibility="collapsed",
)

student_id = st.session_state.student_id
selected_subject = st.session_state.get("selected_subject", "")

st.divider()

# ══════════════════════════════════════════════════════════
# PAGE 1: Upload Syllabus
# ══════════════════════════════════════════════════════════

if active == "Upload Syllabus":
    st.header("Upload Syllabus")

    subject_input = st.text_input("Subject Name", placeholder="e.g. Data Structures")
    uploaded_file = st.file_uploader("Upload Syllabus PDF", type=["pdf"])

    st.subheader("Study Duration")
    from datetime import date, timedelta

    duration_mode = st.radio(
        "How would you like to set the schedule?",
        ["Enter number of days", "I have an exam date"],
        horizontal=True,
    )

    if duration_mode == "Enter number of days":
        study_days = st.number_input("How many days do you have?", min_value=3, max_value=180, value=14)
        exam_date_str = ""
    else:
        exam_date_input = st.date_input("Exam date", min_value=date.today() + timedelta(days=1))
        study_days = (exam_date_input - date.today()).days
        exam_date_str = exam_date_input.isoformat()
        st.info(f"That gives you **{study_days} days** to prepare.")

    if st.button("Parse & Create Study Plan", type="primary", disabled=not (subject_input and uploaded_file)):
        from main import run_ingest

        pdf_bytes = uploaded_file.read()
        progress = st.status("Processing syllabus...", expanded=True)

        step_labels = {
            "orchestrator": "Initializing orchestrator...",
            "parse_syllabus": "Parsing PDF...",
            "embed_documents": "Embedding in ChromaDB...",
            "extract_topics": "Extracting topics with AI...",
            "generate_initial_plan": "Generating study plan...",
            "save_ingest_to_db": "Saving to database...",
        }

        def on_step(node: str, status: str) -> None:
            label = step_labels.get(node, node)
            progress.update(label=label)
            progress.write(f"  {label}")

        result = run_ingest(
            syllabus_bytes=pdf_bytes,
            syllabus_filename=uploaded_file.name,
            student_id=student_id,
            subject=subject_input,
            study_duration_days=study_days,
            exam_date=exam_date_str,
            on_step=on_step,
        )

        progress.update(label="Done!", state="complete")

        topics = result.get("extracted_topics", [])
        st.success(f"Extracted {len(topics)} topics. Study plan generated!")

        st.session_state.selected_subject = subject_input
        switch_page("Study Plan")
        st.rerun()

# ══════════════════════════════════════════════════════════
# PAGE 2: Study Plan
# ══════════════════════════════════════════════════════════

elif active == "Study Plan":
    st.header("Study Plan")

    if not selected_subject:
        st.info("Upload a syllabus first to see your study plan.")
    else:
        subj = get_subject(student_id, selected_subject)
        if not subj:
            st.warning("Subject not found. Please upload a syllabus.")
        else:
            plan_row = get_latest_plan(student_id, subj["id"])
            if not plan_row:
                st.info("No plan generated yet.")
            else:
                plan_data = plan_row["plan_data"]
                revision = plan_row["revision"]
                completed = set(get_completed_topics(student_id, subj["id"]))

                st.subheader(f"{selected_subject} — Revision {revision}")

                if plan_data.get("notes"):
                    st.caption(plan_data["notes"])

                days = plan_data.get("days", [])
                if days:
                    for d in days:
                        day_num = d.get("day", "")
                        day_date = d.get("date", "")
                        topics_list = d.get("topics", [])
                        priority = d.get("priority", "normal").upper()
                        hours = d.get("estimated_hours", 2.0)

                        with st.container(border=True):
                            cols = st.columns([0.8, 1.2, 4, 1.2, 1])
                            cols[0].markdown(f"**Day {day_num}**")
                            cols[1].write(day_date)

                            if priority == "HIGH":
                                cols[3].markdown('<span class="priority-high">HIGH</span>', unsafe_allow_html=True)
                            elif priority == "REVISION":
                                cols[3].markdown('<span class="priority-revision">REVISION</span>', unsafe_allow_html=True)
                            else:
                                cols[3].markdown('<span class="priority-normal">NORMAL</span>', unsafe_allow_html=True)

                            cols[4].write(f"{hours}h")

                            for topic in topics_list:
                                is_done = topic in completed
                                tcol1, tcol2 = cols[2].columns([0.1, 0.9])

                                checked = tcol1.checkbox(
                                    "done", value=is_done,
                                    key=f"done_{day_num}_{topic}",
                                    label_visibility="collapsed",
                                )

                                if is_done:
                                    tcol2.markdown(f"~~{topic}~~ (completed)")
                                else:
                                    tcol2.write(topic)

                                if checked and not is_done:
                                    mark_topic_completed(student_id, subj["id"], topic)
                                    st.session_state.suggest_quiz_topic = topic
                                    st.rerun()

                    if st.session_state.get("suggest_quiz_topic"):
                        topic = st.session_state.suggest_quiz_topic
                        st.info(f"You finished **{topic}**! Take a quick quiz to verify your understanding?")
                        col1, col2 = st.columns(2)
                        if col1.button(f"Take Quiz on '{topic}'", type="primary"):
                            st.session_state.quiz_topic_preselect = topic
                            st.session_state.suggest_quiz_topic = None
                            switch_page("Take Quiz")
                            st.rerun()
                        if col2.button("Skip for now"):
                            st.session_state.suggest_quiz_topic = None
                            st.rerun()
                else:
                    st.json(plan_data)

                st.divider()
                if st.button("Force Replan", type="secondary"):
                    from main import run_replan

                    with st.spinner("Replanning based on current performance..."):
                        result = run_replan(student_id, selected_subject)

                    if result.get("study_plan"):
                        st.success(f"Plan revised to version {result.get('plan_revision', '?')}!")
                        st.rerun()
                    else:
                        st.error("Replan failed. " + result.get("error", ""))

# ══════════════════════════════════════════════════════════
# PAGE 3: Ask Doubts
# ══════════════════════════════════════════════════════════

elif active == "Ask Doubts":
    st.header("Ask Doubts")

    if not selected_subject:
        st.info("Upload a syllabus first to ask doubts about your course material.")
    else:
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        chat_container = st.container()
        with chat_container:
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        if prompt := st.chat_input("Ask a doubt about your course material..."):
            st.session_state.chat_history.append({"role": "user", "content": prompt})

            with chat_container:
                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):
                    with st.spinner("Searching course material..."):
                        from main import run_doubt

                        answer = run_doubt(
                            question=prompt,
                            student_id=student_id,
                            subject=selected_subject,
                        )
                    st.markdown(answer)

            st.session_state.chat_history.append({"role": "assistant", "content": answer})
            st.rerun()

# ══════════════════════════════════════════════════════════
# PAGE 4: Take Quiz
# ══════════════════════════════════════════════════════════

elif active == "Take Quiz":
    st.header("Take Quiz")

    if not selected_subject:
        st.info("Upload a syllabus first to take quizzes.")
    else:
        subj = get_subject(student_id, selected_subject)
        topics = subj["topics"] if subj else []

        if not topics:
            st.warning("No topics extracted yet.")
        else:
            default_idx = 0
            if st.session_state.get("quiz_topic_preselect"):
                preselect = st.session_state.quiz_topic_preselect
                if preselect in topics:
                    default_idx = topics.index(preselect)
                st.session_state.quiz_topic_preselect = None

            col1, col2 = st.columns([2, 1])
            with col1:
                quiz_topic = st.selectbox("Select Topic", topics, index=default_idx, key="quiz_topic_select")
            with col2:
                num_q = st.slider("Questions", min_value=3, max_value=15, value=5, key="quiz_num_q")

            if st.button("Generate Quiz", type="primary"):
                from main import run_generate_quiz

                with st.spinner(f"Generating {num_q} questions on '{quiz_topic}'..."):
                    questions = run_generate_quiz(
                        topic=quiz_topic,
                        student_id=student_id,
                        subject=selected_subject,
                        num_questions=num_q,
                    )

                if questions:
                    st.session_state.current_quiz = questions
                    st.session_state.quiz_topic = quiz_topic
                    st.session_state.quiz_submitted = False
                    st.session_state.quiz_result = None
                    st.rerun()
                else:
                    st.error("Failed to generate quiz. Try again.")

            if st.session_state.get("current_quiz") and not st.session_state.get("quiz_submitted"):
                questions = st.session_state.current_quiz
                st.subheader(f"Quiz: {st.session_state.get('quiz_topic', '')}")

                with st.form("quiz_form"):
                    answers = []
                    for i, q in enumerate(questions):
                        st.markdown(f"**Q{i+1}.** {q.get('question', '')}")
                        options = q.get("options", [])
                        answer = st.radio(
                            f"Select answer for Q{i+1}:",
                            options,
                            key=f"q_{i}",
                            label_visibility="collapsed",
                        )
                        answers.append(answer)
                        st.divider()

                    submitted = st.form_submit_button("Submit Answers", type="primary")

                    if submitted:
                        from main import run_grade_and_replan

                        with st.spinner("Grading your answers..."):
                            result = run_grade_and_replan(
                                quiz_questions=questions,
                                student_answers=answers,
                                quiz_topic=st.session_state.quiz_topic,
                                student_id=student_id,
                                subject=selected_subject,
                            )

                        st.session_state.quiz_submitted = True
                        st.session_state.quiz_result = result.get("quiz_result", {})
                        st.session_state.quiz_replanned = result.get("needs_replan", False)
                        st.rerun()

            if st.session_state.get("quiz_submitted") and st.session_state.get("quiz_result"):
                qr = st.session_state.quiz_result
                score = qr.get("score", 0)
                correct = qr.get("correct_count", 0)
                total = qr.get("total_count", 0)

                st.divider()
                col1, col2, col3 = st.columns(3)
                with col1:
                    color = "normal" if score >= 60 else "inverse"
                    st.metric("Score", f"{score:.0f}%", delta_color=color)
                with col2:
                    st.metric("Correct", f"{correct}/{total}")
                with col3:
                    weak = qr.get("weak_areas", [])
                    st.metric("Weak Areas", len(weak))

                if weak:
                    st.warning(f"Weak areas identified: {', '.join(weak)}")

                if st.session_state.get("quiz_replanned"):
                    st.success("Study plan has been automatically revised to prioritize your weak topics! Check the Study Plan page.")

                with st.expander("Detailed Breakdown", expanded=True):
                    for detail in qr.get("per_question", []):
                        num = detail.get("question_num", "?")
                        is_correct = detail.get("correct", False)
                        icon = "+" if is_correct else "-"
                        st.markdown(f"**Q{num}** {'Correct' if is_correct else 'Incorrect'}: {detail.get('explanation', '')}")

                col1, col2 = st.columns(2)
                if col1.button("Take Another Quiz", type="primary"):
                    st.session_state.current_quiz = None
                    st.session_state.quiz_submitted = False
                    st.session_state.quiz_result = None
                    st.rerun()
                if col2.button("View Updated Plan"):
                    st.session_state.current_quiz = None
                    st.session_state.quiz_submitted = False
                    st.session_state.quiz_result = None
                    switch_page("Study Plan")
                    st.rerun()

# ══════════════════════════════════════════════════════════
# PAGE 5: Performance Dashboard
# ══════════════════════════════════════════════════════════

elif active == "Performance":
    st.header("Performance Dashboard")

    if not selected_subject:
        st.info("Upload a syllabus and take some quizzes to see your performance.")
    else:
        subj = get_subject(student_id, selected_subject)
        if not subj:
            st.warning("Subject not found.")
        else:
            subject_id_db = subj["id"]
            all_perf = get_topic_performance(student_id, subject_id_db)
            quiz_history = get_quiz_history(student_id, subject_id_db)
            plan_row = get_latest_plan(student_id, subject_id_db)

            mastered = sum(1 for p in all_perf if p["mastery_level"] == "mastered")
            total_topics = len(subj["topics"])
            avg_score = sum(p["average_score"] for p in all_perf) / len(all_perf) if all_perf else 0
            revision = plan_row["revision"] if plan_row else 0

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Topics Mastered", f"{mastered}/{total_topics}")
            with col2:
                st.metric("Average Score", f"{avg_score:.0f}%")
            with col3:
                st.metric("Quizzes Taken", len(quiz_history))
            with col4:
                st.metric("Plan Revision", revision)

            if all_perf:
                import pandas as pd

                st.divider()
                st.subheader("Topic-wise Performance")

                perf_df = pd.DataFrame([
                    {
                        "Topic": p["topic_name"],
                        "Best Score": p["best_score"],
                        "Avg Score": p["average_score"],
                        "Attempts": p["attempts"],
                        "Mastery": p["mastery_level"].replace("_", " ").title(),
                    }
                    for p in all_perf
                ])

                st.bar_chart(perf_df.set_index("Topic")[["Avg Score", "Best Score"]])
                st.dataframe(perf_df, use_container_width=True, hide_index=True)
            else:
                st.divider()
                st.info("Take some quizzes to see your topic-wise performance here.")

            if quiz_history:
                import pandas as pd

                st.divider()
                st.subheader("Quiz Score Trend")
                trend_df = pd.DataFrame([
                    {"Quiz": f"#{i+1} ({q['topic']})", "Score": q["score"]}
                    for i, q in enumerate(reversed(quiz_history))
                ])
                st.line_chart(trend_df.set_index("Quiz"))

            st.divider()
            memories = get_agent_memories(student_id, subject_id_db, limit=10)
            if memories:
                st.subheader("Agent Observations")
                for m in memories:
                    agent_colors = {"content": "blue", "evaluator": "orange", "planner": "green", "orchestrator": "gray"}
                    color = agent_colors.get(m["agent_name"], "gray")
                    st.markdown(f":{color}[**[{m['agent_name']}]**] {m['content']}")
                    st.caption(m.get("created_at", ""))
            else:
                st.subheader("Agent Observations")
                st.info("Agent observations will appear here as you use the app.")
