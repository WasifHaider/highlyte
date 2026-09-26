"""Fakes for the Groq/OpenAI client used by clip selection tests."""
from __future__ import annotations

from types import SimpleNamespace

from backend.pipeline.groq_llm import ChatResult


class RateLimitError(Exception):
    """Same class name as openai.RateLimitError, which is what
    groq_llm.is_rate_limit checks."""


class FakeRaw:
    def __init__(self, content: str = "[]", finish: str = "stop", headers: dict | None = None):
        self.content, self.finish, self.headers = content, finish, headers or {}

    def parse(self):
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=self.finish)])


class FakeOpenAI:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            with_raw_response=SimpleNamespace(create=self._create)))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeChat:
    """Stands in for groq_llm.GroqChat. Replies are strings (content with
    finish_reason "stop"), ChatResults, or exceptions to raise."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, max_tokens: int) -> ChatResult:
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, str):
            return ChatResult(reply, "stop")
        return reply
