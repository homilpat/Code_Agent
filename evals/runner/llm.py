"""Minimal OpenAI-compatible chat client (e.g. LM Studio's local server). Standard library only."""

import json
import re
import time
import urllib.request
from dataclasses import dataclass

THINK = re.compile(r"<think>.*?</think>", re.S)


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
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
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
