"""文档加载：把 pdf / docx / md / txt 统一解析成 Document。

不依赖 langchain_community（少一个重依赖），直接用手写解析：
    - .md/.txt  直接读，保留标题行
    - .pdf      pypdf 逐页抽取
    - .docx     python-docx 按段落抽取
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


@dataclass
class Document:
    """一篇原始文档。text 是全文，meta 记来源。"""
    doc_id: str
    text: str
    meta: dict = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.meta.get("title") or self.doc_id


def _read_md(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _read_pdf(path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
        if t.strip():
            pages.append(f"[第 {i+1} 页]\n{t}")
    return "\n\n".join(pages)


def _read_docx(path: str) -> str:
    import docx
    d = docx.Document(path)
    parts = []
    for p in d.paragraphs:
        t = (p.text or "").strip()
        if not t:
            continue
        # 保留标题层级（Word 的 Heading 样式）
        style = getattr(p.style, "name", "") or ""
        m = re.match(r"Heading (\d)", style)
        if m:
            level = int(m.group(1))
            parts.append("#" * level + " " + t)
        else:
            parts.append(t)
    # 表格也抽出来（很多规范在表里）
    for tbl in d.tables:
        for row in tbl.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)


LOADERS = {
    ".md": _read_md,
    ".txt": _read_md,
    ".pdf": _read_pdf,
    ".docx": _read_docx,
}


def load_file(path: str) -> Document:
    ext = os.path.splitext(path)[1].lower()
    fn = LOADERS.get(ext)
    if not fn:
        raise ValueError(f"不支持的格式：{ext}（支持 {list(LOADERS)}）")
    text = fn(path)
    name = os.path.basename(path)
    return Document(
        doc_id=name,
        text=text,
        meta={"source": path, "title": os.path.splitext(name)[0],
              "ext": ext, "size": len(text)},
    )


def load_dir(path: str) -> list[Document]:
    """递归加载目录下所有支持的文档。"""
    docs = []
    for root, _, files in os.walk(path):
        for fn in sorted(files):
            ext = os.path.splitext(fn)[1].lower()
            if ext in LOADERS:
                try:
                    docs.append(load_file(os.path.join(root, fn)))
                except Exception as e:  # noqa: BLE001
                    print(f"⚠️ 跳过 {fn}：{e}")
    return docs
