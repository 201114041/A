from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CJK_PATTERN = re.compile(r"[a-z0-9]+|[\u3040-\u30ff\u3400-\u9fff]+")

ALIASES: dict[str, list[str]] = {
    "制作进行": ["制作進行", "现场协调", "日程"],
    "分镜": ["絵コンテ", "コンテ"],
    "布局": ["レイアウト", "画面构成"],
    "作画监督": ["作画監督", "修正"],
    "动画检查": ["動画チェック", "動画検査"],
    "角色设计": ["キャラクターデザイン", "角色设定"],
    "角色设定": ["キャラ設定", "キャラクターデザイン"],
    "美术设定": ["美術設定"],
    "美术监督": ["美術監督"],
    "后期": ["ポストプロダクション"],
    "摄影": ["撮影", "合成"],
    "上色": ["仕上", "彩色"],
    "中间画": ["動画", "补间"],
    "补间": ["動画"],
    "企划": ["企画"],
    "脚本": ["シナリオ"],
    "剧本": ["シナリオ"],
    "监督": ["監督"],
    "演出": ["演出"],
    "碰头会": ["打ち合わせ"],
    "会议": ["打ち合わせ"],
    "返工": ["リテイク", "重画"],
    "检查": ["チェック"],
    "色彩设定": ["色彩設定"],
    "音响": ["音響"],
    "配音": ["アフレコ"],
    "剪辑": ["編集"],
    "原画": ["原画", "关键动作"],
    "背景": ["背景"],
}

OUT_OF_SCOPE_MARKERS = [
    "总作画监督",
    "總作畫監督",
    "制作委员会",
    "製作委員會",
    "收益分配",
    "薪资",
    "薪水",
    "加班",
    "快捷键",
    "2026年",
    "新番",
]


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower().strip()


def tokenize(text: str) -> Counter[str]:
    normalized = normalize_text(text)
    tokens: Counter[str] = Counter()
    for sequence in CJK_PATTERN.findall(normalized):
        if sequence.isascii():
            tokens[f"w:{sequence}"] += 1.5
            continue
        length = len(sequence)
        for size, weight in ((1, 0.25), (2, 1.0), (3, 1.25), (4, 0.75)):
            if length < size:
                continue
            for index in range(length - size + 1):
                tokens[f"c{size}:{sequence[index:index + size]}"] += weight
    return tokens


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    section: str
    page_start: int
    page_end: int
    text: str
    keywords: list[str]
    source_excerpt_ja: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "section": self.section,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "text": self.text,
            "keywords": self.keywords,
            "source_excerpt_ja": self.source_excerpt_ja,
        }


def load_documents(path: Path) -> list[Document]:
    documents = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            documents.append(
                Document(
                    id=raw["id"],
                    title=raw["title"],
                    section=raw.get("section", ""),
                    page_start=int(raw["page_start"]),
                    page_end=int(raw["page_end"]),
                    text=raw["text"],
                    keywords=list(raw.get("keywords", [])),
                    source_excerpt_ja=raw.get("source_excerpt_ja", ""),
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid corpus line {line_number}: {exc}") from exc
    if not documents:
        raise ValueError("Corpus is empty")
    if len({document.id for document in documents}) != len(documents):
        raise ValueError("Corpus contains duplicate document IDs")
    return documents


class Retriever:
    """Small BM25 retriever using Japanese/Chinese character n-grams."""

    def __init__(self, documents: list[Document]):
        self.documents = documents
        self.doc_tokens = [
            tokenize(
                " ".join(
                    [
                        document.title,
                        document.section,
                        document.text,
                        " ".join(document.keywords),
                        document.source_excerpt_ja,
                    ]
                )
            )
            for document in documents
        ]
        self.doc_lengths = [sum(tokens.values()) for tokens in self.doc_tokens]
        self.average_length = sum(self.doc_lengths) / len(self.doc_lengths)
        document_frequency: Counter[str] = Counter()
        for tokens in self.doc_tokens:
            document_frequency.update(tokens.keys())
        count = len(documents)
        self.idf = {
            term: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        expanded: Counter[str] = Counter(tokenize(query))
        normalized_query = normalize_text(query)
        for phrase, aliases in ALIASES.items():
            if phrase in normalized_query:
                for alias in aliases:
                    for token, weight in tokenize(alias).items():
                        expanded[token] += weight * 0.7

        scored: list[tuple[float, int, list[str]]] = []
        for index, document_tokens in enumerate(self.doc_tokens):
            score = 0.0
            matched = []
            document_length = self.doc_lengths[index]
            for term, query_weight in expanded.items():
                frequency = document_tokens.get(term, 0)
                if not frequency:
                    continue
                idf = self.idf.get(term, 1.0)
                denominator = frequency + 1.5 * (
                    1 - 0.75 + 0.75 * document_length / self.average_length
                )
                score += query_weight * idf * frequency * 2.5 / denominator
                if len(matched) < 8:
                    matched.append(term.split(":", 1)[-1])
            document = self.documents[index]
            normalized_title = normalize_text(document.title)
            if normalized_title and normalized_title in normalized_query:
                score += 8.0
            if normalized_query and normalized_query in normalize_text(document.title + "\n" + document.text):
                score += 2.0
            for keyword in document.keywords:
                normalized_keyword = normalize_text(keyword)
                if normalized_keyword and normalized_keyword in normalized_query:
                    score += 1.2
            if ("区别" in normalized_query or "不同" in normalized_query) and (
                "区别" in document.title or "对比" in document.title
            ):
                score += 0.8
            if score > 0:
                scored.append((score, index, matched))

        scored.sort(reverse=True)
        results = []
        for score, index, matched in scored[: max(1, top_k)]:
            document = self.documents[index]
            results.append(
                {
                    **document.to_public_dict(),
                    "score": round(score, 4),
                    "matched_terms": matched,
                }
            )
        return results

    def answer(self, question: str, top_k: int = 5) -> dict[str, Any]:
        started = time.perf_counter()
        results = self.search(question, top_k=top_k)
        retrieval_ms = round((time.perf_counter() - started) * 1000, 2)
        normalized_question = normalize_text(question)
        out_of_scope = any(marker in normalized_question for marker in OUT_OF_SCOPE_MARKERS)
        top_score = results[0]["score"] if results else 0.0
        insufficient = out_of_scope or not results or top_score < 1.0

        if insufficient:
            answer = (
                "当前知识库没有足够资料回答这个问题。"
                "请换一个与已收录的日本动画制作流程、岗位职责或术语有关的问题。"
            )
        elif "区别" in normalized_question or "不同" in normalized_question:
            selected = results[:3]
            lines = [
                f"{index + 1}. {item['text']} [{index + 1}]"
                for index, item in enumerate(selected)
            ]
            answer = "根据知识库中的相关条目，可以这样区分：\n\n" + "\n\n".join(lines)
        else:
            answer = "根据知识库：\n\n" + results[0]["text"] + " [1]"
        return {
            "answer": answer,
            "mode": "extractive",
            "insufficient": insufficient,
            "retrieval_ms": retrieval_ms,
            "sources": results,
        }

