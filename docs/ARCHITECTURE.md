# StudyMate — System Architecture

## 1. Overview

StudyMate is a three-layer, multi-agent system for adaptive academic planning. Unlike monolithic AI chatbots, it uses specialized agents coordinated by an orchestrator, with a closed feedback loop that continuously adapts to student performance.

---

## 2. High-Level Architecture

```mermaid
flowchart TB
    subgraph IL["Interaction Layer"]
        UI["Streamlit Web UI<br/>(5 tabs + sidebar)"]
    end

    subgraph AOL["Agent Orchestration Layer — LangGraph StateGraph"]
        Orch{"Orchestrator<br/>(dispatch + context injection<br/>+ guardrails)"}
        PA["Planner Agent<br/>(ReAct)"]
        CA["Content Agent<br/>(ReAct + RAG tool)"]
        EA["Evaluator Agent<br/>(ReAct + RAG tool)"]
        TC["Topic Extraction<br/>(LCEL Chain)"]
    end

    subgraph DKL["Data / Knowledge Layer"]
        ChromaDB[("ChromaDB<br/>Persistent Vector Store<br/>(1 collection per subject)")]
        SQLite[("SQLite<br/>Central Database<br/>(students, plans, scores,<br/>agent_memory)")]
        LLM["LLM API<br/>(Gemini / Groq / Ollama)"]
    end

    UI -->|"Upload Syllabus"| Orch
    UI -->|"Ask Doubt"| Orch
    UI -->|"Take Quiz"| Orch
    UI -->|"View Plan / Force Replan"| Orch

    Orch -->|"inject agent_memory<br/>context"| PA & CA & EA
    Orch -->|ingest| TC
    TC --> PA
    Orch -->|ask_doubt| CA
    Orch -->|take_quiz| EA
    Orch -->|replan| PA

    CA <-->|"tool: rag_search"| ChromaDB
    EA <-->|"tool: rag_search"| ChromaDB
    PA & CA & EA <-->|"read/write<br/>student data +<br/>agent_memory"| SQLite

    EA -.->|"weak_topics trigger"| PA

    PA & CA & EA <-->|"LLM inference"| LLM
```

### Layer Responsibilities

| Layer | Components | Purpose |
|-------|-----------|---------|
| **Interaction** | Streamlit UI (5 tabs + sidebar) | Student-facing interface: upload, plan, chat, quiz, dashboard |
| **Agent Orchestration** | LangGraph StateGraph + Orchestrator | Routes actions, coordinates agents, manages cross-agent context |
| **Data / Knowledge** | ChromaDB + SQLite + LLM API | Vector storage for RAG, relational storage for student data, LLM inference |

---

## 3. The Closed-Loop Flow

This is the core innovation — the Plan → Learn → Test → Replan cycle:

```mermaid
flowchart LR
    Plan["1. PLAN<br/>Planner Agent<br/>generates day-wise<br/>study schedule"]
    Learn["2. LEARN<br/>Content Agent<br/>answers doubts<br/>via RAG"]
    Test["3. TEST<br/>Evaluator Agent<br/>generates quiz<br/>& grades answers"]
    Replan["4. REPLAN<br/>Planner Agent<br/>revises schedule<br/>for weak topics"]

    Plan --> Learn --> Test
    Test -->|"weak_topics<br/>score < 60%"| Replan
    Replan -->|"updated schedule"| Plan
    Test -->|"all topics<br/>mastered"| Done((Done))
```

**What makes this different from existing systems:**

| Aspect | Existing Systems | StudyMate |
|--------|-----------------|------------|
| Planning | Static, one-time timetable | Planner Agent replans based on quiz results |
| Content | Generic search / single chatbot | Content Agent uses RAG grounded in student's own syllabus |
| Assessment | Separate, disconnected from planning | Evaluator Agent's results feed directly back to Planner |
| Architecture | Monolithic single-model chatbot | Coordinated multi-agent system with specialization |
| Adaptivity | None or coarse (weekly review) | Continuous, per-topic adaptivity after every quiz |

---

## 4. LangGraph StateGraph Topology

```mermaid
flowchart TD
    classDef process fill:#e3f2fd,stroke:#1565C0,stroke-width:2px,color:#0D47A1
    classDef agent fill:#e8f5e9,stroke:#2E7D32,stroke-width:2px,color:#1B5E20
    classDef decision fill:#fff3e0,stroke:#E65100,stroke-width:2px,color:#BF360C
    classDef store fill:#f3e5f5,stroke:#6A1B9A,stroke-width:2px,color:#4A148C
    classDef terminal fill:#263238,stroke:#263238,color:#fff

    START((START)):::terminal --> orchestrator

    orchestrator{"Orchestrator<br/>read agent_memory<br/>from SQLite"}:::decision

    orchestrator -->|"action = ingest"| parse_syllabus
    orchestrator -->|"action = ask_doubt"| rag_retrieve
    orchestrator -->|"action = take_quiz"| generate_quiz
    orchestrator -->|"action = replan"| replan
    orchestrator -->|"action = view_plan"| END_VP((END)):::terminal

    subgraph INGEST["INGEST SUBGRAPH"]
        direction TB
        parse_syllabus["parse_syllabus<br/>tool: PyMuPDF"]:::process
        embed_documents["embed_documents<br/>tool: HuggingFace → ChromaDB"]:::store
        extract_topics["extract_topics<br/>LLM call → JSON topic list"]:::agent
        generate_initial_plan["generate_initial_plan<br/>Planner Agent → day-wise schedule"]:::agent
        save_ingest["save_to_db<br/>SQLite: student + subject + plan"]:::store

        parse_syllabus --> embed_documents --> extract_topics --> generate_initial_plan --> save_ingest
    end
    save_ingest --> END_I((END)):::terminal

    subgraph DOUBT["DOUBT SUBGRAPH"]
        direction TB
        rag_retrieve["rag_retrieve<br/>tool: ChromaDB search k=4"]:::process
        content_agent["Content Agent<br/>tool: rag_search<br/>LLM call → explanation"]:::agent
        save_doubt["save observation<br/>SQLite: agent_memory"]:::store

        rag_retrieve --> content_agent --> save_doubt
    end
    save_doubt --> END_D((END)):::terminal

    subgraph QUIZ["QUIZ + REPLAN SUBGRAPH"]
        direction TB
        generate_quiz["generate_quiz<br/>Evaluator Agent<br/>tool: rag_search → MCQ JSON"]:::agent
        grade_quiz["grade_quiz<br/>Evaluator Agent<br/>LLM call → score + weak areas"]:::agent
        update_perf["update_performance<br/>SQLite: topic_performance"]:::store
        check{"check_replan<br/>any topic avg < 60%?"}:::decision

        generate_quiz --> grade_quiz --> update_perf --> check
    end

    check -->|"YES"| replan
    check -->|"NO"| END_Q((END)):::terminal

    replan["replan<br/>Planner Agent<br/>reads agent_memory + scores<br/>LLM call → revised schedule"]:::agent
    save_replan["save_to_db<br/>SQLite: plan revision++"]:::store
    replan --> save_replan --> END_R((END)):::terminal
```

**Legend:** Blue = data processing, Green = LLM agent call, Orange = decision, Purple = data store read/write, Black = start/end

### Node Summary (13 nodes)

| Node | Type | LLM? | Description |
|------|------|------|-------------|
| `orchestrator` | Coordinator | No | Dispatches action, injects cross-agent memory |
| `parse_syllabus` | Data processing | No | PyMuPDF PDF extraction + chunking (500 chars, 60 overlap) |
| `embed_documents` | Data processing | No | Embed chunks into ChromaDB collection |
| `extract_topics` | LCEL Chain | Yes | Syllabus text → structured topic list (JSON) |
| `generate_initial_plan` | Planner Agent | Yes | Topics → day-wise study plan |
| `rag_retrieve` | Data processing | No | ChromaDB similarity search (k=4) |
| `content_agent` | ReAct Agent | Yes | RAG-grounded doubt answering |
| `generate_quiz` | Evaluator Agent | Yes | Topic → MCQ questions (JSON) |
| `grade_quiz` | Evaluator Agent | Yes | Answers → score + weak areas |
| `update_performance` | Pure Python | No | Update SQLite `topic_performance` table |
| `check_replan` | Pure Python | No | Check if weak topics warrant a replan |
| `replan` | Planner Agent | Yes | Current plan + weak topics + agent memories → revised plan |
| `save_ingest_to_db` | Pure Python | No | Persist ingest results to SQLite |

---

## 5. Cross-Agent Memory via SQLite

Agents coordinate through a shared `agent_memory` table in SQLite. Each agent reads observations from other agents and writes its own:

```mermaid
sequenceDiagram
    participant S as Student
    participant O as Orchestrator
    participant DB as SQLite (agent_memory)
    participant CA as Content Agent
    participant EA as Evaluator Agent
    participant PA as Planner Agent

    Note over S,PA: Student studies and takes quiz

    S->>O: Ask doubt: "Explain linked list traversal"
    O->>DB: Read agent_memory for this student
    O->>CA: Dispatch with context
    CA->>DB: Write: "Student asked about linked list traversal"
    CA-->>S: Answer with RAG citations

    S->>O: Ask doubt: "Still confused about linked list pointers"
    O->>DB: Read agent_memory (sees prior observation)
    O->>CA: Dispatch: "student asked about linked lists before"
    CA->>DB: Write: "Student asked about linked lists 2x — likely struggling"
    CA-->>S: Simplified explanation with examples

    S->>O: Take quiz on "Linked Lists"
    O->>DB: Read agent_memory (sees Content Agent's observations)
    O->>EA: Dispatch: "student struggles with linked lists"
    EA->>DB: Write: "Scored 40% — weak on pointers"
    EA-->>O: Quiz result: score=40%, weak_areas=["Linked Lists"]

    O->>DB: Read all agent memories for replanning
    O->>PA: Dispatch replan with all observations
    PA->>DB: Write: "Added 2 extra days for Linked Lists, moved earlier"
    PA-->>S: Updated study plan
```

### Database Schema

| Table | Purpose |
|-------|---------|
| `students` | Student identity (id, name) |
| `subjects` | Subjects per student (name, ChromaDB collection, topics) |
| `study_plans` | Versioned day-wise plans (plan_data JSON, revision number) |
| `topic_performance` | Per-topic scores (best, average, attempts, mastery level) |
| `quiz_results` | Full quiz history (questions, answers, score, weak areas) |
| `agent_memory` | Cross-agent observations (agent_name, memory_type, content) |

---

## 6. Agent Specifications

### Planner Agent
- **Pattern:** `create_react_agent()` (LangGraph ReAct)
- **Tools:** None (receives structured data)
- **Temperature:** 0.3
- **Input:** Topic list + performance data + agent observations
- **Output:** JSON day-wise schedule with priorities

### Content Agent
- **Pattern:** `create_react_agent()` with RAG tool
- **Tools:** `rag_search` (ChromaDB)
- **Temperature:** 0.4
- **Input:** Student question + retrieved context + agent observations
- **Output:** Explanation with source citations

### Evaluator Agent
- **Pattern:** `create_react_agent()` with RAG tool
- **Tools:** `rag_search` (ChromaDB)
- **Temperature:** 0.2
- **Dual mode:** Generate quiz OR grade answers
- **Output:** MCQ questions (JSON) or grading results (JSON)

---

## 7. RAG Pipeline

```mermaid
flowchart LR
    PDF["Syllabus PDF"] --> PyMuPDF["PyMuPDF<br/>Text Extraction"]
    PyMuPDF --> Chunker["RecursiveCharacterTextSplitter<br/>500 chars, 60 overlap"]
    Chunker --> Embed["HuggingFace<br/>all-MiniLM-L6-v2<br/>384-dim vectors"]
    Embed --> Store["ChromaDB<br/>Persistent Collection<br/>(cosine similarity)"]

    Query["Student Question"] --> QEmbed["Embed Query"]
    QEmbed --> Search["Similarity Search<br/>k=4"]
    Store --> Search
    Search --> Context["Retrieved Chunks<br/>with source + page metadata"]
    Context --> Agent["Content/Evaluator Agent"]
```

---

## 8. Multi-Provider LLM Configuration

All agents and chains use `build_llm()` from `config.py`, which reads `LLM_PROVIDER` from `.env`:

| Provider | Model | Free Tier | Best For |
|----------|-------|-----------|----------|
| Gemini | `gemini-2.5-flash` | 15 RPM | Primary — best free model |
| Groq | `llama-3.3-70b-versatile` | 30 RPM | Fastest inference |
| Ollama | `qwen3:14b` | Unlimited | Offline / local development |

Switching providers requires no code changes — just update `LLM_PROVIDER` in `.env` or use the Streamlit sidebar dropdown.

---

## 9. Future Scope

### Orchestrator Guardrails
- Input validation (reject non-academic content)
- Content safety filtering
- Rate limiting for free-tier LLM APIs
- Prompt injection protection

### Advanced Adaptive Learning
- Spaced repetition (Ebbinghaus forgetting curve)
- Bloom's taxonomy quiz levels
- Learning style detection from interaction patterns

### Tiered LLM Routing
- Route tasks to models by complexity instead of using one model for everything
- **High tier** (Gemini 3.6/3.7 Flash): Planner Agent scheduling and replanning — requires complex multi-factor reasoning
- **Medium tier** (Gemini 3.5 Flash): Quiz generation and grading — needs accurate structured JSON
- **Low tier** (Groq/Flash-Lite): Topic extraction and doubt answering — mostly retrieval and summarization
- Saves premium model quota for genuinely hard tasks; becomes cost-saving on paid tiers

### Production Deployment
- PostgreSQL (replace SQLite for multi-user concurrency)
- Authentication (student login)
- LangFuse observability
- Cloud deployment with self-hosted LLM (vLLM/Ollama)

### Research Extensions
- A/B testing: adaptive vs. static plan
- Multi-LLM comparison study
- Longitudinal time-to-mastery tracking
