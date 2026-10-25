from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag_app.core import Retriever, load_documents  # noqa: E402


def load_questions(path: Path) -> list[dict]:
    questions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            questions.append(json.loads(line))
    return questions


def write_results_csv(path: Path, rows: list[dict]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidates = [
        path,
        path.with_name(f"{path.stem}_{timestamp}{path.suffix}"),
    ]
    last_error = None
    for candidate in candidates:
        try:
            with candidate.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            return candidate
        except PermissionError as exc:
            last_error = exc
            print(f"CSV is locked, trying fallback path: {candidate}", file=sys.stderr)
    raise last_error or PermissionError("Unable to write CSV results")


def main() -> None:
    corpus_path = ROOT / "data" / "corpus.jsonl"
    questions_path = ROOT / "data" / "eval" / "questions.jsonl"
    json_path = ROOT / "data" / "eval" / "retrieval_results.json"
    csv_path = ROOT / "data" / "eval" / "retrieval_results.csv"

    retriever = Retriever(load_documents(corpus_path))
    questions = load_questions(questions_path)
    rows = []
    hit_at_1 = hit_at_3 = hit_at_5 = 0
    reciprocal_ranks = []
    answerable_count = 0
    no_answer_correct = 0
    no_answer_count = 0

    for question in questions:
        result = retriever.answer(question["question"], top_k=5)
        retrieved_ids = [source["id"] for source in result["sources"]]
        gold_ids = list(question.get("gold_ids", []))
        first_relevant_rank = 0
        for rank, document_id in enumerate(retrieved_ids, start=1):
            if document_id in gold_ids:
                first_relevant_rank = rank
                break

        if gold_ids:
            answerable_count += 1
            hit_at_1 += int(first_relevant_rank == 1)
            hit_at_3 += int(0 < first_relevant_rank <= 3)
            hit_at_5 += int(0 < first_relevant_rank <= 5)
            reciprocal_ranks.append(1 / first_relevant_rank if first_relevant_rank else 0)
        else:
            no_answer_count += 1
            no_answer_correct += int(bool(result["insufficient"]))

        rows.append(
            {
                "id": question["id"],
                "question": question["question"],
                "category": question.get("category", ""),
                "gold_ids": "|".join(gold_ids),
                "retrieved_ids": "|".join(retrieved_ids),
                "first_relevant_rank": first_relevant_rank,
                "hit_at_1": int(first_relevant_rank == 1) if gold_ids else "",
                "hit_at_3": int(0 < first_relevant_rank <= 3) if gold_ids else "",
                "hit_at_5": int(0 < first_relevant_rank <= 5) if gold_ids else "",
                "insufficient_detected": int(bool(result["insufficient"])) if not gold_ids else "",
                "top_score": result["sources"][0]["score"] if result["sources"] else 0,
            }
        )

    metrics = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus_documents": len(retriever.documents),
        "questions_total": len(questions),
        "answerable_questions": answerable_count,
        "no_answer_questions": no_answer_count,
        "hit_at_1": round(hit_at_1 / answerable_count, 4) if answerable_count else 0,
        "hit_at_3": round(hit_at_3 / answerable_count, 4) if answerable_count else 0,
        "hit_at_5": round(hit_at_5 / answerable_count, 4) if answerable_count else 0,
        "mrr": round(sum(reciprocal_ranks) / answerable_count, 4) if answerable_count else 0,
        "no_answer_detection_accuracy": (
            round(no_answer_correct / no_answer_count, 4) if no_answer_count else 0
        ),
        "retriever": "BM25 over Japanese/Chinese character 1-4 grams with term aliases",
    }
    json_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    output_csv_path = write_results_csv(csv_path, rows)
    print(f"CSV result: {output_csv_path}", file=sys.stderr)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

