from __future__ import annotations

from langchain_core.tools import tool

from ingestion.vector_store import search_collection


def create_rag_search_tool(collection_name: str):
    @tool
    def rag_search(query: str) -> str:
        """Search the course material for relevant information.
        Use this when you need to find explanations, definitions,
        examples, or details from the student's uploaded documents."""
        results = search_collection(collection_name, query, k=4)
        chunks = []
        for i, doc in enumerate(results, 1):
            source = doc.metadata.get("source", "unknown")
            page = doc.metadata.get("page", "?")
            chunks.append(f"[{i}] (source: {source}, page: {page})\n{doc.page_content}")
        return "\n\n".join(chunks) if chunks else "No relevant content found in the course material."

    return rag_search
