from pathlib import Path
import unittest

from rag_app.core import Retriever, load_documents

ROOT = Path(__file__).resolve().parent.parent


class AnswererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.retriever = Retriever(load_documents(ROOT / "data" / "corpus.jsonl"))

    def test_extractive_answer_has_citation_and_sources(self):
        result = self.retriever.answer("作画工程有哪三个主要检查点？", top_k=5)
        self.assertFalse(result["insufficient"])
        self.assertIn("[1]", result["answer"])
        self.assertGreaterEqual(len(result["sources"]), 1)

    def test_out_of_scope_question_abstains(self):
        result = self.retriever.answer("制作委员会如何分配收益？", top_k=5)
        self.assertTrue(result["insufficient"])
        self.assertIn("资料", result["answer"])

    def test_comparison_answer_uses_multiple_sources(self):
        result = self.retriever.answer("原画和动画有什么区别？", top_k=3)
        self.assertGreaterEqual(len(result["sources"]), 2)
        self.assertIn("[2]", result["answer"])


if __name__ == "__main__":
    unittest.main()
