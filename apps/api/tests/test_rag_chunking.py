import pytest

from ai_notebook_api.rag.chunking import chunk_text


def test_chunker_preserves_exact_source_offsets_and_order() -> None:
    source = ("Paragraph one contains useful source text. " * 12) + "\n\n" + ("Second paragraph. " * 12)
    chunks = chunk_text(source, chunk_size=160, overlap=24)

    assert len(chunks) > 1
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert source[chunk.start_char : chunk.end_char] == chunk.text
        assert chunk.end_char > chunk.start_char


def test_chunker_has_overlap_between_adjacent_chunks() -> None:
    source = "word " * 100
    chunks = chunk_text(source, chunk_size=100, overlap=20)

    assert len(chunks) > 1
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.start_char < previous.end_char


def test_chunker_rejects_empty_content_and_invalid_window() -> None:
    with pytest.raises(ValueError, match="empty"):
        chunk_text(" \n\t ")
    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("valid text", chunk_size=8)
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("valid text", chunk_size=16, overlap=16)


def test_chunker_handles_short_text_as_one_chunk() -> None:
    source = "A short source document."
    chunks = chunk_text(source)

    assert len(chunks) == 1
    assert chunks[0].text == source
    assert chunks[0].start_char == 0
    assert chunks[0].end_char == len(source)
