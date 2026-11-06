from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextChunk:
    ordinal: int
    start_char: int
    end_char: int
    text: str


def chunk_text(text: str, *, chunk_size: int = 1200, overlap: int = 160) -> list[TextChunk]:
    """Split source text into deterministic overlapping chunks with exact character offsets."""
    if not isinstance(text, str):
        raise TypeError("document content must be text")
    if not text.strip():
        raise ValueError("document content must not be empty")
    if chunk_size < 16:
        raise ValueError("chunk_size must be at least 16")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be between zero and chunk_size - 1")

    chunks: list[TextChunk] = []
    start = 0
    text_length = len(text)

    while start < text_length:
        hard_end = min(start + chunk_size, text_length)
        end = hard_end

        if hard_end < text_length:
            window = text[start:hard_end]
            minimum_boundary = int(chunk_size * 0.6)
            candidates = [
                (window.rfind(separator), len(separator))
                for separator in ("\n\n", "\n", ". ", " ")
            ]
            boundary, separator_length = max(candidates, key=lambda item: item[0])
            if boundary >= minimum_boundary:
                end = start + boundary + separator_length

        if end <= start:
            end = hard_end

        piece = text[start:end]
        if piece.strip():
            chunks.append(
                TextChunk(
                    ordinal=len(chunks),
                    start_char=start,
                    end_char=end,
                    text=piece,
                )
            )

        if end >= text_length:
            break

        next_start = max(end - overlap, start + 1)
        if next_start <= start:
            raise RuntimeError("chunker failed to advance")
        start = next_start

    if not chunks:
        raise ValueError("document content produced no searchable chunks")
    return chunks
