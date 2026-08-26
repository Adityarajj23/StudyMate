from __future__ import annotations

import chromadb
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_PERSIST_DIR = "./data/vector_store"

_embeddings: HuggingFaceEmbeddings | None = None
_chroma_client: chromadb.PersistentClient | None = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=_EMBEDDING_MODEL)
    return _embeddings


def _get_chroma_client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=_PERSIST_DIR)
    return _chroma_client


def create_or_update_collection(
    collection_name: str,
    documents: list[Document],
) -> str:
    client = _get_chroma_client()
    embeddings = _get_embeddings()

    try:
        client.delete_collection(collection_name)
    except Exception:
        pass

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    texts = [doc.page_content for doc in documents]
    metadatas = [doc.metadata for doc in documents]
    ids = [f"{collection_name}_{i}" for i in range(len(documents))]

    for start in range(0, len(texts), 100):
        batch_texts = texts[start:start + 100]
        batch_metas = metadatas[start:start + 100]
        batch_ids = ids[start:start + 100]
        batch_embeddings = embeddings.embed_documents(batch_texts)

        collection.add(
            documents=batch_texts,
            embeddings=batch_embeddings,
            metadatas=batch_metas,
            ids=batch_ids,
        )

    return collection_name


def search_collection(
    collection_name: str,
    query: str,
    k: int = 4,
) -> list[Document]:
    client = _get_chroma_client()
    embeddings = _get_embeddings()

    collection = client.get_collection(collection_name)
    query_embedding = embeddings.embed_query(query)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k,
    )

    documents = []
    for i, text in enumerate(results["documents"][0]):
        metadata = results["metadatas"][0][i] if results["metadatas"] else {}
        documents.append(Document(page_content=text, metadata=metadata))
    return documents


def list_collections() -> list[str]:
    client = _get_chroma_client()
    return [c.name for c in client.list_collections()]


def collection_exists(collection_name: str) -> bool:
    return collection_name in list_collections()


def sanitize_collection_name(subject_name: str) -> str:
    name = subject_name.lower().strip()
    name = name.replace(" ", "_")
    name = "".join(c for c in name if c.isalnum() or c == "_")
    return name or "default"
