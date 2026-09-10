def embedding_document_text(title: str, chunk: str) -> str:
    """Keep document identity in every chunk vector used for dense retrieval."""
    normalized_title = " ".join((title or "").split())
    normalized_chunk = " ".join((chunk or "").split())
    if normalized_title and normalized_chunk:
        return f"{normalized_title}\n{normalized_chunk}"
    return normalized_title or normalized_chunk
