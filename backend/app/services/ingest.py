"""文档解析与切块。

切块的 page/paragraph 定位信息是证据链的锚点（架构文档 §3.3），
任何情况下不得丢弃。
"""

import hashlib
from dataclasses import dataclass
from io import BytesIO

# 单 chunk 注入 token 数为估算值（约 3 字符/token），仅用于预算提示，不做精确计费
_APPROX_CHARS_PER_TOKEN = 3


class UnsupportedFileType(ValueError):
    pass


@dataclass
class Chunk:
    index: int
    content: str
    page_number: int | None = None
    paragraph_index: int | None = None
    token_count: int = 0


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def parse_file(filename: str, data: bytes) -> list[tuple[int | None, int, str]]:
    """解析为 (page_number, paragraph_index, text) 列表。"""
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        pieces: list[tuple[int | None, int, str]] = []
        for page_no, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            for idx, para in enumerate(_split_paragraphs(text)):
                pieces.append((page_no, idx, para))
        return pieces
    if suffix == "docx":
        from docx import Document as DocxDocument

        doc = DocxDocument(BytesIO(data))
        return [
            (None, idx, para.text.strip())
            for idx, para in enumerate(doc.paragraphs)
            if para.text.strip()
        ]
    if suffix in {"md", "markdown", "txt"}:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("gbk", errors="replace")
        return [
            (None, idx, para)
            for idx, para in enumerate(_split_paragraphs(text))
        ]
    raise UnsupportedFileType(f"不支持的文件类型 .{suffix}（支持 pdf/docx/md/txt）")


def _hard_split(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def chunk_paragraphs(
    paragraphs: list[tuple[int | None, int, str]],
    *,
    size: int,
    overlap: int,
) -> list[Chunk]:
    """按段落聚合成 ≤size 的 chunk；超长段落硬切；相邻 chunk 携带尾部 overlap 字符。"""
    pieces: list[tuple[int | None, int, str]] = []
    for page_no, para_idx, para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= size:
            pieces.append((page_no, para_idx, para))
        else:
            pieces.extend((page_no, para_idx, p) for p in _hard_split(para, size))

    chunks: list[Chunk] = []
    buf: list[tuple[int | None, int, str]] = []

    def flush() -> None:
        content = "\n".join(t for _, _, t in buf)
        if overlap > 0 and chunks:
            carry = chunks[-1].content[-overlap:]
            if carry:
                content = f"{carry}\n{content}"
        first_page, first_para, _ = buf[0]
        chunks.append(
            Chunk(
                index=len(chunks),
                content=content,
                page_number=first_page,
                paragraph_index=first_para,
                token_count=max(len(content) // _APPROX_CHARS_PER_TOKEN, 1),
            )
        )

    for piece in pieces:
        page_no, para_idx, text_piece = piece
        buf_len = sum(len(t) for _, _, t in buf)
        if buf and buf_len + len(text_piece) + len(buf) > size:
            flush()
            buf = []
        buf.append(piece)
    if buf:
        flush()
    return chunks
