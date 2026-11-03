"""Minimal OpenAI-compatible chat client (e.g. LM Studio's local server). Standard library only."""

import json
import re
import time
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

THINK = re.compile(r"<think>.*?</think>", re.S)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never redirect locally submitted benchmark prompts to a different host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LLMError(Exception):
    pass


@dataclass(frozen=True)
class Completion:
    text: str
    finish_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    seconds: float


class ChatClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 16384,
        timeout: int = 1800,
    ):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Benchmark model endpoint must be a loopback HTTP URL")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def complete(self, messages: list[dict]) -> Completion:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        request = urllib.request.Request(  # noqa: S310 - scheme and host checked above
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(request, timeout=self.timeout) as response:
                payload = json.load(response)
            choice = payload["choices"][0]
            text = choice["message"].get("content") or ""
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        usage = payload.get("usage") or {}
        return Completion(
            text=THINK.sub("", text).strip(),
            finish_reason=choice.get("finish_reason"),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            seconds=time.monotonic() - started,
        )
