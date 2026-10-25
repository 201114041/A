from __future__ import annotations

import argparse
import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .core import Retriever, load_documents
from .llm import generate_rag_answer, llm_config

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"
CORPUS_PATH = ROOT_DIR / "data" / "corpus.jsonl"
EVAL_PATH = ROOT_DIR / "data" / "eval" / "retrieval_results.json"


class RagRequestHandler(BaseHTTPRequestHandler):
    retriever: Retriever

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            documents = self.retriever.documents
            self._send_json(
                {
                    "status": "ok",
                    "documents": len(documents),
                    "page_span": [
                        min(document.page_start for document in documents),
                        max(document.page_end for document in documents),
                    ],
                    "llm_configured": llm_config() is not None,
                    "modes": ["extractive", "llm"] if llm_config() else ["extractive"],
                }
            )
            return
        if path == "/api/corpus":
            self._send_json(
                {
                    "documents": [
                        {
                            "id": document.id,
                            "title": document.title,
                            "section": document.section,
                            "page_start": document.page_start,
                            "page_end": document.page_end,
                            "keywords": document.keywords,
                        }
                        for document in self.retriever.documents
                    ]
                }
            )
            return
        if path == "/api/eval/summary":
            if not EVAL_PATH.is_file():
                self._send_error_json(HTTPStatus.NOT_FOUND, "评测结果尚未生成")
                return
            self._send_json(json.loads(EVAL_PATH.read_text(encoding="utf-8")))
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/query":
            self._send_error_json(HTTPStatus.NOT_FOUND, "接口不存在")
            return
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return

        question = str(payload.get("question", "")).strip()
        if not question:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "问题不能为空")
            return
        if len(question) > 500:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "问题过长，最多 500 个字符")
            return
        try:
            top_k = max(1, min(int(payload.get("top_k", 5)), 10))
        except (TypeError, ValueError):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "top_k 必须是整数")
            return
        requested_mode = str(payload.get("mode", "auto"))
        if requested_mode not in {"auto", "extractive", "llm"}:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "mode 不合法")
            return

        started = time.perf_counter()
        extractive = self.retriever.answer(question, top_k=top_k)
        result: dict[str, Any] = {
            **extractive,
            "question": question,
            "llm_configured": llm_config() is not None,
        }
        if requested_mode in {"auto", "llm"} and llm_config() is not None:
            try:
                generated = generate_rag_answer(question, extractive["sources"])
                result.update(generated)
                result["answer"] = generated["answer"]
            except Exception as exc:
                if requested_mode == "llm":
                    self._send_error_json(HTTPStatus.BAD_GATEWAY, str(exc))
                    return
                result["llm_error"] = str(exc)
        elif requested_mode == "llm":
            self._send_error_json(
                HTTPStatus.CONFLICT,
                "未配置 LLM。请设置 RAG_LLM_BASE_URL、RAG_LLM_API_KEY、RAG_LLM_MODEL。",
            )
            return

        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        self._send_json(result)


    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length 不合法") from exc
        if length <= 0 or length > 100_000:
            raise ValueError("请求体为空或过大")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体必须是 UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("JSON 顶层必须是对象")
        return value

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path == "/" else path.removeprefix("/static/")
        candidate = (STATIC_DIR / relative).resolve()
        if candidate != STATIC_DIR and STATIC_DIR not in candidate.parents:
            self._send_error_json(HTTPStatus.NOT_FOUND, "文件不存在")
            return
        if not candidate.is_file():
            self._send_error_json(HTTPStatus.NOT_FOUND, "文件不存在")
            return
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }
        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_types.get(candidate.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[http] {self.address_string()} - {format % args}")


class RagServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def build_server(host: str, port: int) -> RagServer:
    documents = load_documents(CORPUS_PATH)
    retriever = Retriever(documents)
    handler = type("BoundRagHandler", (RagRequestHandler,), {"retriever": retriever})
    return RagServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Anime production RAG knowledge base")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = build_server(args.host, args.port)
    print(f"RAG knowledge base running at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("Stopping server...", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
