from __future__ import annotations

import json

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from config import build_llm_with_fallback

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an academic syllabus analyzer. Extract all distinct topics
from the given syllabus text.

RULES:
- Extract individual topics, not broad module/unit names
- Keep topic names concise but descriptive (3-8 words each)
- Order topics as they appear in the syllabus
- Include subtopics as separate entries when they are substantial enough to study independently
- Aim for 8-20 topics depending on syllabus breadth

Return ONLY a valid JSON array of topic strings. No other text.
Example: ["Arrays and Time Complexity", "Linked Lists", "Stacks and Queues"]"""),
    ("human", "Extract topics from this syllabus:\n\n{syllabus_text}"),
])


def extract_topics(syllabus_text: str) -> list[str]:
    llm = build_llm_with_fallback(temperature=0.1)
    chain = _PROMPT | llm | StrOutputParser()
    raw = chain.invoke({"syllabus_text": syllabus_text})

    if isinstance(raw, list):
        raw = "\n".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in raw)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]

    return json.loads(raw)
