from __future__ import annotations

import fitz
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=60,
    separators=["\n\n", "\n", ". ", " ", ""],
)


def load_pdf(pdf_bytes: bytes, source: str = "syllabus") -> list[Document]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    documents: list[Document] = []

    for page_num, page in enumerate(doc, start=1):
        text = page.get_text()
        if not text.strip():
            continue
        chunks = _splitter.split_text(text)
        for chunk in chunks:
            documents.append(
                Document(
                    page_content=chunk,
                    metadata={"source": source, "page": page_num},
                )
            )

    doc.close()
    return documents


def extract_full_text(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text_parts = []
    for page in doc:
        text = page.get_text()
        if text.strip():
            text_parts.append(text)
    doc.close()
    return "\n\n".join(text_parts)
