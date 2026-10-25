from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag_app.core import Retriever, load_documents  # noqa: E402
from rag_app.llm import generate_baseline_answer, generate_rag_answer, llm_config  # noqa: E402


def load_questions(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare plain LLM baseline with RAG")
    parser.add_argument("--limit", type=int, default=0, help="Only evaluate the first N questions")
    args = parser.parse_args()

    config = llm_config()
    if config is None:
        print(
            "LLM is not configured. Set RAG_LLM_BASE_URL, RAG_LLM_API_KEY and RAG_LLM_MODEL.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    retriever = Retriever(load_documents(ROOT / "data" / "corpus.jsonl"))
    questions = load_questions(ROOT / "data" / "eval" / "questions.jsonl")
    if args.limit > 0:
        questions = questions[: args.limit]

    output_path = ROOT / "data" / "eval" / "llm_eval_samples.jsonl"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_path = ROOT / "data" / "eval" / "answer_review_results.csv"
    if review_path.exists():
        review_path = review_path.with_name(f"answer_review_results_{timestamp}.csv")
    rows = []
    with output_path.open("w", encoding="utf-8") as stream:
        for index, question in enumerate(questions, start=1):
            retrieval = retriever.answer(question["question"], top_k=5)
            baseline = generate_baseline_answer(question["question"], config)
            rag = generate_rag_answer(question["question"], retrieval["sources"], config)
            sample = {
                "id": question["id"],
                "question": question["question"],
                "category": question.get("category", ""),
                "gold_answer": question.get("answer", ""),
                "key_points": question.get("key_points", []),
                "baseline_answer": baseline["answer"],
                "rag_answer": rag["answer"],
                "llm_model": config["model"],
                "sources": retrieval["sources"],
                "retrieval_insufficient": retrieval["insufficient"],
            }
            stream.write(json.dumps(sample, ensure_ascii=False) + "\n")
            rows.append(sample)
            print(f"[{index}/{len(questions)}] {question['id']} completed", flush=True)

    with review_path.open("w", encoding="utf-8-sig", newline="") as stream:
        fieldnames = [
            "id",
            "question",
            "gold_answer",
            "key_points",
            "baseline_answer",
            "rag_answer",
            "baseline_score_0_5",
            "rag_correctness_0_5",
            "rag_faithfulness_0_5",
            "rag_citation_0_5",
            "rag_abstention_0_5",
            "notes",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "id": row["id"],
                    "question": row["question"],
                    "gold_answer": row["gold_answer"],
                    "key_points": " | ".join(row["key_points"]),
                    "baseline_answer": row["baseline_answer"],
                    "rag_answer": row["rag_answer"],
                }
            )
    print(f"Saved {len(rows)} samples to {output_path}")
    print(f"Manual review template: {review_path}")


if __name__ == "__main__":
    main()

