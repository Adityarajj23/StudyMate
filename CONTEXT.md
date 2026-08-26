# StudyMate — Project Context

## What is this?

StudyMate is a **closed-loop multi-agent AI system** for personalized academic planning. Three specialized agents cooperate to adapt a student's study schedule based on their actual quiz performance:

1. **Planner Agent** — generates and revises day-wise study schedules
2. **Content Agent** — answers student doubts via RAG (retrieval-augmented generation), grounded in their own uploaded course material
3. **Evaluator Agent** — generates topic-wise MCQ quizzes, grades answers, and identifies weak areas

The core loop: **Plan → Learn → Test → Replan**

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent framework | LangChain + LangGraph (StateGraph with orchestrator) |
| Vector store | ChromaDB (persistent, one collection per subject) |
| Embeddings | HuggingFace `sentence-transformers/all-MiniLM-L6-v2` |
| Central database | SQLite (student profiles, plans, quiz results, cross-agent memory) |
| LLM providers | Gemini 2.5 Flash, Groq/Llama 3.3 70B, Ollama/Qwen3:14B (all free) |
| PDF parsing | PyMuPDF |
| UI | Streamlit (5-tab layout) |

## Folder Structure

```
studymate/
├── agents/          — 3 ReAct agents (planner, content, evaluator)
├── chains/          — LCEL chains (topic extraction)
├── ingestion/       — PDF loader + ChromaDB vector store
├── tools/           — LangChain @tool factory for RAG search
├── models/          — State TypedDict + Pydantic schemas
├── db/              — SQLite access layer
├── ui/              — Streamlit app
├── data/            — ChromaDB persistent dir + SQLite DB
├── docs/            — Architecture documentation
├── config.py        — Settings + build_llm() multi-provider factory
├── graph.py         — LangGraph StateGraph with orchestrator + 13 nodes
└── main.py          — Entry points: run_ingest(), run_doubt(), run_quiz(), etc.
```

## How to Run

```bash
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env — set GEMINI_API_KEY (or GROQ_API_KEY, or Ollama)

# 4. Run
streamlit run ui/app.py
```

## LangGraph Architecture

Orchestrator-based StateGraph with conditional routing:

- **Orchestrator** dispatches to the correct subgraph based on `action` field
- **Ingest path**: parse_syllabus → embed_documents → extract_topics → generate_initial_plan → save_to_db
- **Doubt path**: rag_retrieve → content_agent
- **Quiz path**: generate_quiz → grade_quiz → update_performance → check_replan → (optionally) replan
- **Replan path**: replan (reads all agent memories for context)

## Key Design Decisions

- **ChromaDB over FAISS**: persistent storage, per-subject collections, metadata filtering
- **SQLite over JSON files**: queryable, cross-agent shared memory via `agent_memory` table
- **Orchestrator over Router**: injects cross-agent context, logs decisions, future guardrails hook
- **Multi-provider LLM**: same `build_llm()` factory pattern as the resume-evaluator project

## Research Paper Context

This is a research paper project demonstrating that a coordinated multi-agent system outperforms a monolithic chatbot for adaptive academic planning. The `agent_memory` table enables inter-agent coordination (Content Agent's observations about student struggles inform the Planner Agent's schedule revisions).
