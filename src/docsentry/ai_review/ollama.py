"""Narrow stdlib client for Ollama POST /api/chat. Loopback only; knows nothing else."""

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Protocol

from docsentry.ai_review.urlcheck import validate_ollama_base_url

MAX_RESPONSE_BYTES = 1_000_000


class OllamaError(Exception):
    def __init__(self, code: str, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Opener(Protocol):
    def open(self, fullurl: Any, data: Any = None, timeout: float = ...) -> Any: ...


def make_opener() -> Opener:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


class OllamaClient:
    PATH = "/api/chat"

    def __init__(self, base_url: str, timeout: float, opener: Opener | None = None) -> None:
        self._url = validate_ollama_base_url(base_url) + self.PATH  # raises before any request
        self._timeout = timeout
        self._opener = opener or make_opener()

    def _post(self, body: dict[str, Any]) -> str:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self._url, data=data, method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            resp = self._opener.open(req, timeout=self._timeout)
            with resp:
                length = resp.headers.get("Content-Length") if hasattr(resp, "headers") else None
                if length is not None and length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
                    raise OllamaError("ollama_invalid_response")
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
        except OllamaError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise OllamaError("ollama_model_unavailable") from None
            if exc.code in (500, 503):
                raise OllamaError("ollama_resource_unavailable") from None
            raise OllamaError("ollama_http_error", exc.code) from None
        except TimeoutError:
            raise OllamaError("ollama_timeout") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError | socket.timeout):
                raise OllamaError("ollama_timeout") from None
            raise OllamaError("ollama_unreachable") from None
        except OSError:
            raise OllamaError("ollama_unreachable") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise OllamaError("ollama_invalid_response")
        try:
            env = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise OllamaError("ollama_invalid_response") from None
        content = self._extract(env)
        if not isinstance(content, str):
            raise OllamaError("ollama_invalid_response")
        return content

    def _extract(self, env: Any) -> object:
        msg = env.get("message") if isinstance(env, dict) else None
        return msg.get("content") if isinstance(msg, dict) else None

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: dict[str, object],
        num_ctx: int,
        num_predict: int,
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": schema,
            "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": 0},
        }
        try:
            return self._post(body)
        except OllamaError as exc:
            if exc.status != 400:
                raise
        body["format"] = "json"  # server rejected the schema form: fall back once
        return self._post(body)


class LlamaCppClient(OllamaClient):
    """Same loopback boundary, for a local llama.cpp server (OpenAI-compatible chat API)."""

    PATH = "/v1/chat/completions"

    def _extract(self, env: Any) -> object:
        choices = env.get("choices") if isinstance(env, dict) else None
        first = choices[0] if isinstance(choices, list) and choices else None
        msg = first.get("message") if isinstance(first, dict) else None
        return msg.get("content") if isinstance(msg, dict) else None

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: dict[str, object],
        num_ctx: int,
        num_predict: int,
    ) -> str:
        body: dict[str, Any] = {
            "model": model or "local",
            "messages": messages,
            "stream": False,
            "max_tokens": num_predict,
            "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "review", "strict": True, "schema": schema},
            },
        }
        try:
            return self._post(body)
        except OllamaError as exc:
            if exc.status != 400:
                raise
        body["response_format"] = {"type": "json_object"}
        return self._post(body)
