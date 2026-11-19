"""ragscope 单元测试：切分/检索/指标/加载。

全部离线，不调 LLM、不依赖外部服务。
"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ragscope.diagnose import _match, aggregate, diagnose_retrieval
from ragscope.splitter import Chunk, split_document
from ragscope.loader import Document, load_file


class TestSplitter(unittest.TestCase):
    def _doc(self, text):
        return Document(doc_id="t.md", text=text, meta={"source": "t.md"})

    def test_heading_chain_preserved(self):
        """标题链要保留，chunk 才知道自己属于哪一节。"""
        text = """# 一级

## 二级

这是一段足够长的正文内容，用来测试切分是否保留标题链。

## 另一个二级

第二段正文，也足够长以满足最小长度限制。
"""
        chunks = split_document(self._doc(text), min_chars=10)
        self.assertGreaterEqual(len(chunks), 2)
        # 至少有一个 chunk 的 heading 含两级标题
        self.assertTrue(any("一级" in c.heading and "二级" in c.heading
                            for c in chunks))

    def test_short_chunk_dropped(self):
        """过短的片段（噪音）要丢掉。"""
        text = "# 标题\n\n短\n\n## 节\n\n这是一段足够长的正文内容用于通过最小长度检查。"
        chunks = split_document(self._doc(text), min_chars=20)
        self.assertTrue(all(len(c.text) >= 20 for c in chunks))

    def test_long_text_split_with_overlap(self):
        """超长段落要二次切分，且带重叠避免断句丢上下文。"""
        long_para = "这是一个很长的句子。" * 100
        text = "# 标题\n\n" + long_para
        chunks = split_document(self._doc(text), max_chars=200, min_chars=10)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c.text) <= 400 for c in chunks))

    def test_plain_text_without_heading(self):
        """没有标题的纯文本也要能切。"""
        text = "这是一段没有任何 markdown 标题的纯文本内容，长度足够通过检查。"
        chunks = split_document(self._doc(text), min_chars=10)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].heading, "")

    def test_citation_format(self):
        text = "# 文档\n\n## 第一节\n\n正文内容足够长以通过最小长度限制检查。"
        chunks = split_document(self._doc(text), min_chars=10)
        c = chunks[0]
        self.assertIn("t.md", c.citation)
        self.assertIn("第一节", c.citation)


class TestMatch(unittest.TestCase):
    def test_match_first(self):
        self.assertEqual(_match("a.md", ["a.md · 节1", "b.md"]), 1)

    def test_match_second(self):
        self.assertEqual(_match("b.md", ["a.md", "b.md · 节"]), 2)

    def test_match_miss(self):
        self.assertEqual(_match("c.md", ["a.md", "b.md"]), 0)

    def test_match_multiple_acceptable(self):
        """expect 用 | 分隔多个可接受答案。"""
        self.assertEqual(_match("x.md|b.md", ["a.md", "b.md"]), 2)

    def test_match_empty_expect(self):
        self.assertEqual(_match("", ["a.md"]), 0)


class TestDiagnose(unittest.TestCase):
    def test_aggregate_metrics(self):
        from ragscope.diagnose import QueryResult
        results = [
            QueryResult("q1", "a.md", ["a.md", "b.md"], {1: 1.0, 3: 1.0, 5: 1.0}, 1.0),
            QueryResult("q2", "b.md", ["a.md", "b.md"], {1: 1.0, 3: 1.0, 5: 1.0}, 0.5),
            QueryResult("q3", "c.md", ["a.md", "b.md"], {1: 0.0, 3: 0.0, 5: 0.0}, 0.0),
        ]
        agg = aggregate(results)
        self.assertEqual(agg["n"], 3)
        self.assertEqual(agg["recall@1"], 66.7)   # 2/3
        self.assertEqual(agg["miss"], 1)

    def test_diagnose_attributes_rank_failure(self):
        """命中但排名靠后 → 归因要说「排第几位」，而不是「没召回」。"""
        class FakeRetriever:
            def search(self, q, top_k=5, rerank=True):
                class H:
                    def __init__(self, c): self.citation = c
                return [H("x.md"), H("y.md"), H("z.md"), H("target.md")]
        cases = [{"question": "q", "expect_citation": "target.md"}]
        res = diagnose_retrieval(FakeRetriever(), cases, k_max=5)
        self.assertIn("第 4 位", res[0].failure)
        self.assertFalse(res[0].hit)


class TestLoader(unittest.TestCase):
    def test_markdown_loader(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as f:
            f.write("# 标题\n\n内容")
            path = f.name
        try:
            doc = load_file(path)
            self.assertIn("标题", doc.text)
            self.assertEqual(doc.meta["ext"], ".md")
        finally:
            os.unlink(path)

    def test_unsupported_format_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            path = f.name
        try:
            with self.assertRaises(ValueError):
                load_file(path)
        finally:
            os.unlink(path)

    def test_docx_loader_preserves_headings(self):
        try:
            import docx
        except ImportError:
            self.skipTest("python-docx 未安装")
        d = docx.Document()
        d.add_heading("一级", level=1)
        d.add_paragraph("正文内容")
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            path = f.name
        try:
            d.save(path)
            doc = load_file(path)
            self.assertIn("# 一级", doc.text)   # 标题被转成 markdown
        finally:
            os.unlink(path)


class TestEmbedderRetriever(unittest.TestCase):
    def setUp(self):
        from ragscope.embedder import Embedder
        self.emb = Embedder(n_components=8)

    def test_fit_transform_shape(self):
        texts = ["住宿标准 450", "报销周期 15 日", "会议纪要 三季度"]
        vecs = self.emb.embed(texts)
        self.assertEqual(vecs.shape[0], 3)
        self.assertGreater(vecs.shape[1], 0)

    def test_transform_before_fit_raises(self):
        from ragscope.embedder import Embedder
        e = Embedder()
        with self.assertRaises(RuntimeError):
            e.transform(["x"])

    def test_retriever_finds_relevant_chunk(self):
        from ragscope.embedder import Embedder
        from ragscope.retriever import HybridRetriever
        chunks = [
            Chunk("1", "跨省差旅住宿标准 450 元每晚", "policy.md", "差旅标准"),
            Chunk("2", "报销周期每月 15 日和 30 日", "policy.md", "经费报销"),
            Chunk("3", "部门例会讨论三季度工作", "meeting.md", "例会"),
        ]
        r = HybridRetriever(embedder=Embedder(n_components=8))
        r.build(chunks)
        hits = r.search("住宿标准是多少", top_k=2)
        self.assertGreater(len(hits), 0)
        self.assertIn("住宿", hits[0].chunk.text)


if __name__ == "__main__":
    unittest.main()
