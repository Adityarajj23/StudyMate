# StudyMate — UI Walkthrough

A step-by-step guide from terminal setup to every feature of the app.

---

## 1. Getting Started

### Prerequisites
- Python 3.10+
- A free API key from at least one provider:
  - [Google AI Studio](https://aistudio.google.com/apikey) for Gemini 2.5 Flash (recommended)
  - [Groq Console](https://console.groq.com/keys) for Llama 3.3 70B (auto-fallback)
  - Or [Ollama](https://ollama.com/) installed locally (no key needed)

### Terminal Setup

```bash
# Clone or navigate to the project
cd studymate

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

# Install all dependencies
pip install -r requirements.txt

# Set up your API keys
cp .env.example .env
# Edit .env and add your keys:
#   GEMINI_API_KEY=your-key-here
#   GROQ_API_KEY=your-key-here   (for auto-fallback)

# Launch the app
streamlit run ui/app.py
```

The app opens at `http://localhost:8501`. On first launch you'll see a welcome screen asking you to enter your name in the sidebar.

---

## 2. Sidebar Setup

The sidebar is always visible on the left and controls your session:

| Element | What it does |
|---------|-------------|
| **Student Name** | Enter your name. This creates (or loads) your profile in the SQLite database. All your plans, quiz history, and performance data are tied to this name. |
| **Subject** | Dropdown of subjects you've uploaded. Empty until you upload your first syllabus. |
| **LLM Provider** | Switch between Gemini 2.5 Flash (best quality), Groq/Llama 3.3 70B (fastest), or Ollama/Qwen3:14B (local/offline). With dual-LLM mode, Gemini is primary and Groq auto-activates if Gemini hits rate limits. |
| **Active label** | Shows which model + provider is currently active. |

---

## 3. Tab 1: Upload Syllabus

This is where you start. Upload your course PDF and the system generates a personalized study plan.

### What you provide:
1. **Subject Name** — e.g., "Data Structures", "Operating Systems"
2. **Syllabus PDF** — your course material, lecture notes, or textbook PDF
3. **Study Duration** — two options (toggle with radio button):
   - **"Enter number of days"** — type any number (3-180 days)
   - **"I have an exam date"** — pick a date from the calendar, system calculates remaining days

### What happens behind the scenes:

```
Your PDF
  ↓
[PyMuPDF] extracts text page by page
  ↓
[RecursiveCharacterTextSplitter] breaks into 500-char chunks with 60-char overlap
  ↓
[HuggingFace all-MiniLM-L6-v2] converts each chunk to a 384-dimensional vector
  ↓
[ChromaDB] stores vectors in a persistent collection named after your subject
  ↓
[Topic Extraction Chain] LLM reads full syllabus text → extracts 8-20 topic names as JSON
  ↓
[Planner Agent] receives topics + your duration → generates a day-wise study schedule
  ↓
[SQLite] saves student profile, subject, topics, plan, and initial agent memory
```

### What you see:
- A progress bar stepping through each stage
- Extracted topics list in an expandable section
- Success message: "Created collection with X chunks. Extracted Y topics. Study plan generated!"

### Tips:
- The PDF can be your syllabus, textbook, or lecture notes — the more content, the better the RAG answers
- If topic extraction looks wrong, re-upload with a cleaner PDF
- You can upload multiple subjects (one at a time) — switch between them via the sidebar

---

## 4. Tab 2: Study Plan (Interactive Dashboard)

Your day-wise study schedule — the central hub of the app.

### What you see:

| Day | Date | Topics | Priority | Hours | Status |
|-----|------|--------|----------|-------|--------|
| 1 | 2026-08-27 | Arrays, Time Complexity | NORMAL | 2.0h | ☐ |
| 2 | 2026-08-28 | Linked Lists | HIGH | 3.0h | ☐ |
| 3 | 2026-08-29 | Revision: Arrays | REVISION | 1.5h | ☐ |
| ... | | | | | |

**Color coding:**
- **Normal** — regular study day
- **HIGH** (red) — weak topic that needs extra attention (set by auto-replan)
- **REVISION** (blue) — revision day added after poor quiz performance

### Mark as Finished:
Each topic has a checkbox. When you check it:
1. Topic status updates to "completed" in the database
2. A suggestion appears: **"You finished [topic]! Take a quick quiz to verify?"**
3. If you click **"Take Quiz"**, you jump to the Quiz tab with that topic pre-selected

### How auto-replan works:
After you take a quiz and score below 60%:
- The Planner Agent automatically generates a revised schedule
- Weak topics get added back as **REVISION** modules
- They're marked **HIGH priority** and moved earlier in the schedule
- You see the updated plan immediately — the revision number increments

### Force Replan:
Click this button to manually trigger a replan. The Planner Agent reads:
- All your quiz scores from SQLite
- All agent observations (what you asked about, where you struggled)
- Then generates a fresh schedule prioritizing your weak areas

---

## 5. Tab 3: Ask Doubts

A chat interface for asking questions about your course material.

### How to use:
Type any question in the chat input at the bottom, e.g.:
- "What is the difference between a stack and a queue?"
- "Explain binary search tree insertion with an example"
- "What is amortized analysis?"

### What happens behind the scenes:

```
Your question
  ↓
[Orchestrator] reads agent_memory — checks if you've asked about this topic before
  ↓
[ChromaDB] similarity search — retrieves top-4 most relevant chunks from your syllabus
  ↓
[Content Agent] (ReAct pattern) receives:
  - Your question
  - Retrieved chunks with source + page metadata
  - Prior observations from agent_memory
  ↓
[Content Agent] may call rag_search tool multiple times for deeper retrieval
  ↓
Answer with source citations: "(Source: lecture_notes.pdf, Page 12)"
  ↓
[SQLite agent_memory] logs: "Student asked about [topic]"
```

### What makes this special:
- Answers come **only** from your uploaded material — no hallucinated internet content
- Source citations tell you exactly where in your PDF the answer came from
- If you ask about the same topic repeatedly, the Content Agent notices (via agent_memory) and provides a different, more detailed explanation
- Chat history is preserved within the session

---

## 6. Tab 4: Take Quiz

Test your understanding with AI-generated MCQ quizzes.

### Step 1: Generate Quiz
1. Select a topic from the dropdown (pre-selected if coming from Study Plan suggestion)
2. Set number of questions (3-15, default 5)
3. Click **"Generate Quiz"**

Behind the scenes:
```
[Evaluator Agent] receives topic name
  ↓
Uses rag_search tool to find relevant content from ChromaDB
  ↓
LLM generates MCQ questions grounded in your actual course material
  ↓
Returns JSON: [{question, options[A-D], correct_answer, explanation, topic}]
```

### Step 2: Answer Questions
- Each question shows 4 radio button options (A, B, C, D)
- Select your answers and click **"Submit Answers"**

### Step 3: See Results

Behind the scenes:
```
[Evaluator Agent] compares your answers to correct answers
  ↓
Calculates score, identifies weak areas
  ↓
[SQLite] updates topic_performance (best score, avg, mastery level)
  ↓
[SQLite] saves full quiz result (questions, your answers, score)
  ↓
[check_replan] checks: any topic avg < 60%?
  ↓
YES → [Planner Agent] auto-generates revised schedule
       → weak topics added as REVISION/HIGH priority
NO  → done, show results
  ↓
[SQLite agent_memory] logs: "Scored X% on [topic]. Weak areas: [...]"
```

### What you see:
- **Score**: e.g., 60% (color-coded: green ≥60%, red <60%)
- **Correct count**: e.g., 3/5
- **Weak areas**: topics where you answered incorrectly
- **Detailed breakdown** (expandable): per-question correct/incorrect with explanations
- **Replan notification**: "Study plan has been automatically revised!" (if score was low)

---

## 7. Tab 5: Performance Dashboard

Track your progress across all quizzes and topics.

### Metrics Row (top):
| Topics Mastered | Average Score | Quizzes Taken | Plan Revision |
|----------------|--------------|---------------|---------------|
| 8/12 | 72% | 6 | 3 |

### Charts:
- **Bar chart**: Topic-wise scores (average + best) — instantly see which topics need work
- **Line chart**: Score trend over time — track improvement across quizzes

### Detailed Table:
| Topic | Best Score | Avg Score | Attempts | Mastery |
|-------|-----------|-----------|----------|---------|
| Arrays | 90% | 85% | 3 | Mastered |
| Linked Lists | 40% | 35% | 1 | Needs Work |
| Stacks | 70% | 70% | 1 | Proficient |

**Mastery levels:** Not Started → Needs Work (<40%) → Developing (40-59%) → Proficient (60-79%) → Mastered (80%+)

### Agent Observations (expandable):
Shows what the agents have noted about your learning:
- **[content]** "Student asked about linked list traversal 2x — likely struggling"
- **[evaluator]** "Scored 40% on Linked Lists — confused pointers and traversal"
- **[planner]** "Revised plan v3: added 2 extra days for Linked Lists"

These cross-agent observations are how the system adapts to you specifically.

---

## 8. The Closed Loop — How Everything Connects

This is the core innovation of StudyMate:

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│   1. UPLOAD syllabus → Planner generates schedule   │
│              ↓                                      │
│   2. STUDY using the plan → ask doubts (Content)    │
│              ↓                                      │
│   3. Mark topic FINISHED → system suggests quiz     │
│              ↓                                      │
│   4. TAKE QUIZ → Evaluator grades answers           │
│              ↓                                      │
│   5. Score ≥ 60%?                                   │
│      YES → topic confirmed, continue                │
│      NO  → Planner AUTO-REPLANS                     │
│            → weak topic added as REVISION            │
│            → go back to step 2                      │
│                                                     │
│   Repeat until all topics → MASTERED                │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**What makes this different from a regular chatbot:**
- The three agents coordinate through shared memory (SQLite `agent_memory` table)
- The Content Agent's observation that you asked about a topic 3 times informs the Planner Agent's decision to add revision days
- The Evaluator Agent's quiz results directly trigger schedule revisions
- No manual intervention needed — the system adapts automatically

For the full architecture diagrams, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No course material uploaded yet" | Upload a syllabus PDF first in Tab 1 |
| Gemini rate limit (429 error) | The dual-LLM system auto-falls back to Groq. If both fail, wait 1 minute and retry |
| Quiz generation returns empty | The PDF might not have enough content on that topic. Try a broader topic or upload more material |
| Plan has too few/many days | Re-upload with a different duration setting |
| Proxy errors (corporate network) | Set `HTTP_PROXY` in your `.env` file |
| Ollama not connecting | Ensure Ollama is running locally: `ollama serve` |
