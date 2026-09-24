import pytest

from app.services.ingest import (
    Chunk,
    UnsupportedFileType,
    chunk_paragraphs,
    parse_file,
    sha256_text,
)


def test_sha256_stable():
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abd")


def test_parse_txt():
    text = "第一段\n\n第二段"
    pieces = parse_file("a.txt", text.encode("utf-8"))
    assert [p[2] for p in pieces] == ["第一段", "第二段"]
    assert all(p[0] is None for p in pieces)


def test_parse_unsupported():
    with pytest.raises(UnsupportedFileType):
        parse_file("a.exe", b"\x00\x01")


def _para(page, idx, text):
    return (page, idx, text)


def test_chunk_grouping_respects_size():
    paragraphs = [_para(1, i, "字" * 300) for i in range(4)]
    chunks = chunk_paragraphs(paragraphs, size=500, overlap=50)
    # 每两个 300 字段落合为一个 chunk
    assert all(len(c.content) <= 500 + 50 + 1 for c in chunks)
    assert len(chunks) >= 2
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunk_hard_split_long_paragraph():
    chunks = chunk_paragraphs([_para(3, 0, "字" * 1200)], size=500, overlap=50)
    assert len(chunks) == 3
    assert all(c.page_number == 3 for c in chunks)


def test_chunk_overlap_carries_tail():
    paragraphs = [_para(1, 0, "A" * 400), _para(1, 1, "B" * 400)]
    chunks = chunk_paragraphs(paragraphs, size=500, overlap=50)
    assert len(chunks) == 2
    tail = chunks[0].content[-50:]
    assert chunks[1].content.startswith(tail)


def test_chunk_token_count_positive():
    chunks = chunk_paragraphs([_para(None, 0, "hello world")], size=500, overlap=0)
    assert chunks[0].token_count >= 1


def test_chunk_empty_input():
    assert chunk_paragraphs([], size=500, overlap=50) == []
