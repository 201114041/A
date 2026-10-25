from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def llm_config() -> dict[str, str] | None:
    base_url = os.getenv("RAG_LLM_BASE_URL", "").strip()
    api_key = os.getenv("RAG_LLM_API_KEY", "").strip()
    model = os.getenv("RAG_LLM_MODEL", "").strip()
    if not base_url or not api_key or not model:
        return None
    return {"base_url": base_url.rstrip("/"), "api_key": api_key, "model": model}


def build_rag_prompt(question: str, sources: list[dict[str, Any]]) -> str:
    passages = []
    for index, source in enumerate(sources, start=1):
        passages.append(
            f"[{index}] id={source['id']} | {source['title']} | "
            f"原书第{source['page_start']}-{source['page_end']}页\n{source['text']}"
        )
    context = "\n\n".join(passages)
    return (
        "你是一个严格依据给定资料回答问题的动画制作知识库助手。\n"
        "只允许使用下面提供的资料，不得补充资料中没有的常识或猜测。\n"
        "回答使用简体中文，保留必要的日文术语，并用 [1]、[2] 标注引用。\n"
        "如果资料不足以回答，必须明确说“当前知识库资料不足”，不要编造。\n\n"
        f"资料：\n{context}\n\n"
        f"问题：{question}\n\n"
        "请给出简洁但完整的答案。"
    )


def generate_rag_answer(
    question: str,
    sources: list[dict[str, Any]],
    config: dict[str, str] | None = None,
) -> dict[str, Any]:
    active = config or llm_config()
    if active is None:
        raise RuntimeError("LLM is not configured")
    if not sources:
        return {
            "answer": "当前知识库资料不足，无法回答这个问题。",
            "mode": "llm",
            "model": active["model"],
        }

    url = active["base_url"]
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    payload = {
        "model": active["model"],
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": "你是严格依据检索资料回答问题的 RAG 助手，必须给出引用。",
            },
            {"role": "user", "content": build_rag_prompt(question, sources)},
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {active['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("LLM response did not contain choices")
    content = choices[0].get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("LLM returned an empty answer")
    return {"answer": content, "mode": "llm", "model": active["model"]}


def generate_baseline_answer(
    question: str,
    config: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Ask the same model without retrieval context."""
    active = config or llm_config()
    if active is None:
        raise RuntimeError("LLM is not configured")

    url = active["base_url"]
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    payload = {
        "model": active["model"],
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": "你是动画制作知识问答助手。请直接回答问题，不要引用外部资料编号。",
            },
            {"role": "user", "content": question},
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {active['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("LLM response did not contain choices")
    content = choices[0].get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("LLM returned an empty answer")
    return {"answer": content, "mode": "baseline", "model": active["model"]}
