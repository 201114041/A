from pathlib import Path
import unittest

from rag_app.core import Retriever, load_documents

ROOT = Path(__file__).resolve().parent.parent


class RetrieverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.documents = load_documents(ROOT / "data" / "corpus.jsonl")
        cls.retriever = Retriever(cls.documents)

    def test_corpus_is_unique(self):
        self.assertEqual(len(self.documents), 28)
        self.assertEqual(len({document.id for document in self.documents}), 28)

    def test_production_manager_query(self):
        results = self.retriever.search("制作进行为什么需要协调各环节？", top_k=5)
        self.assertIn("c14_production_manager", [item["id"] for item in results])

    def test_chinese_alias_matches_japanese_term(self):
        results = self.retriever.search("分镜里有什么信息？", top_k=5)
        self.assertEqual(results[0]["id"], "c08_storyboard")

    def test_comparison_retrieves_both_related_chunks(self):
        results = self.retriever.search("布局和原画有什么区别？", top_k=3)
        ids = [item["id"] for item in results]
        self.assertIn("c09_layout_key_animation", ids)
        self.assertIn("c21_layout_work", ids)

    def test_unanswerable_question_is_flagged(self):
        result = self.retriever.answer("2026年某部新番的监督是谁？", top_k=5)
        self.assertTrue(result["insufficient"])


if __name__ == "__main__":
    unittest.main()
