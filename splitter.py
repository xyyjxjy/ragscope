"""结构感知切分：按 markdown 标题层级切，而不是固定字符窗口。

为什么不用固定窗口（LangChain 那种 chunk_size=500）：
    固定窗口会把「一、差旅标准」的标题和它的内容切到不同 chunk，
    检索时命中内容片段但丢了标题上下文，回答就不知道说的是哪一节。

这里保留 heading 链：每个 chunk 带着「它属于哪个一级/二级标题」。
回答时能给出「出处：xxx.md · 一、差旅标准」，这才是可用性。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ragscope.loader import Document


@dataclass
class Chunk:
    chunk_id: str
    text: str
    doc_id: str
    heading: str = ""          # 完整标题链，如 "一、差旅标准 > 1.1 住宿"
    level: int = 0
    meta: dict = field(default_factory=dict)

    @property
    def citation(self) -> str:
        """给回答用的出处字符串。"""
        base = f"{self.doc_id}"
        return f"{base} · {self.heading}" if self.heading else base


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def split_document(doc: Document, max_chars: int = 800,
                   min_chars: int = 40) -> list[Chunk]:
    """按标题层级切分，超长段落再按句号二次切。"""
    chunks: list[Chunk] = []
    stack: list[tuple[int, str]] = []   # (level, title)
    buf: list[str] = []

    def flush():
        nonlocal buf
        text = "\n".join(buf).strip()
        if len(text) >= min_chars:
            heading = " > ".join(t for _, t in stack)
            chunks.append(Chunk(
                chunk_id=f"{doc.doc_id}#{len(chunks)}",
                text=text,
                doc_id=doc.doc_id,
                heading=heading,
                level=stack[-1][0] if stack else 0,
                meta={"source": doc.meta.get("source", ""),
                      "title": doc.title},
            ))
        buf = []

    def emit_long(text: str):
        """超长文本按句子切，保留滑动重叠避免断句丢上下文。"""
        if len(text) <= max_chars:
            return [text]
        sents = re.split(r"(?<=[。！？；\n])", text)
        out, cur = [], ""
        for s in sents:
            if len(cur) + len(s) > max_chars and cur:
                out.append(cur)
                cur = cur[-100:] + s   # 100 字重叠
            else:
                cur += s
        if cur.strip():
            out.append(cur)
        return out

    for raw in doc.text.splitlines():
        m = _HEADING.match(raw.strip())
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2).strip()
            # 维护标题栈：同级替换，更低级弹出
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            buf.append(raw.strip())
        else:
            buf.append(raw)
    flush()

    # 对超长 chunk 二次切分
    final: list[Chunk] = []
    for c in chunks:
        if len(c.text) <= max_chars * 1.5:
            final.append(c)
            continue
        for i, part in enumerate(emit_long(c.text)):
            final.append(Chunk(
                chunk_id=f"{c.chunk_id}-{i}",
                text=part,
                doc_id=c.doc_id,
                heading=c.heading,
                level=c.level,
                meta=c.meta,
            ))
    return final


def split_all(docs: list[Document], **kw) -> list[Chunk]:
    out: list[Chunk] = []
    for d in docs:
        out.extend(split_document(d, **kw))
    return out
