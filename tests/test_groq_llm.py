from types import SimpleNamespace

import pytest

from backend.pipeline import groq_llm
from tests.llm_fakes import FakeOpenAI, FakeRaw, RateLimitError


def make(replies):
    sleeps: list[float] = []
    fake = FakeOpenAI(replies)
    chat = groq_llm.GroqChat(fake, sleep=sleeps.append, clock=lambda: 0.0)
    return chat, fake, sleeps


def test_complete_sends_model_prompt_and_low_reasoning():
    chat, fake, _ = make([FakeRaw('[{"a": 1}]')])
    res = chat.complete("hello", max_tokens=100)
    assert (res.content, res.finish_reason) == ('[{"a": 1}]', "stop")
    call = fake.calls[0]
    assert call["model"] == groq_llm.GROQ_MODEL
    assert call["messages"] == [{"role": "user", "content": "hello"}]
    assert call["max_tokens"] == 100
    assert call["extra_body"] == {"reasoning_effort": "low"}


def test_waits_for_reset_when_minute_budget_is_used_up():
    headers = {"x-ratelimit-remaining-tokens": "1000", "x-ratelimit-reset-tokens": "30s"}
    chat, _, sleeps = make([FakeRaw(headers=headers), FakeRaw()])
    chat.complete("x", max_tokens=100)
    chat.complete("y", max_tokens=2000)
    assert sleeps == [30.0]


def test_no_wait_while_budget_remains():
    headers = {"x-ratelimit-remaining-tokens": "7000", "x-ratelimit-reset-tokens": "30s"}
    chat, _, sleeps = make([FakeRaw(headers=headers), FakeRaw()])
    chat.complete("x", max_tokens=100)
    chat.complete("y", max_tokens=2000)
    assert sleeps == []


def test_per_minute_429_waits_and_retries():
    err = RateLimitError("Error code: 429 - Rate limit reached on tokens per minute (TPM). Please try again in 7.5s.")
    chat, _, sleeps = make([err, FakeRaw("ok")])
    assert chat.complete("x", max_tokens=100).content == "ok"
    assert sleeps == [7.5]


def test_daily_429_raises_daily_limit_with_wait():
    err = RateLimitError("Error code: 429 - Rate limit reached for model on tokens per day (TPD): "
                         "Limit 200000, Used 199000. Please try again in 21m0.576s.")
    chat, _, _ = make([err])
    with pytest.raises(groq_llm.DailyLimit) as e:
        chat.complete("x", max_tokens=100)
    assert e.value.wait == "about 21 minutes"


def test_other_errors_propagate():
    chat, _, _ = make([RuntimeError("boom")])
    with pytest.raises(RuntimeError, match="boom"):
        chat.complete("x", max_tokens=100)


def test_parse_duration():
    assert groq_llm.parse_duration("7.66s") == 7.66
    assert groq_llm.parse_duration("1m2.5s") == 62.5
    assert groq_llm.parse_duration("2h") == 7200.0
    assert groq_llm.parse_duration("345ms") == 0.345
    assert groq_llm.parse_duration("soon") is None


def test_wait_label_under_a_minute():
    assert groq_llm.wait_label(RateLimitError("Please try again in 20s.")) == "about a minute"
    assert groq_llm.wait_label(RuntimeError("no hint")) is None


def test_build_chat_without_key(monkeypatch):
    monkeypatch.setenv("GROQ_KEY", "")
    assert groq_llm.build_chat() is None


def test_build_chat_shares_one_client_per_key_and_model(monkeypatch):
    monkeypatch.setenv("GROQ_KEY", "test-key")
    monkeypatch.setattr(groq_llm, "_chats", {})
    first = groq_llm.build_chat()
    second = groq_llm.build_chat()
    assert first is not None
    assert all(a is b for a, b in zip(first.chats, second.chats))


def test_complete_logs_token_usage(capsys):
    usage = SimpleNamespace(prompt_tokens=12, completion_tokens=3)
    chat, _, _ = make([FakeRaw('[]', usage=usage)])
    chat.complete("x", max_tokens=100)
    assert "[groq] openai/gpt-oss-20b prompt_tokens=12 completion_tokens=3" in capsys.readouterr().out


def test_complete_without_usage_does_not_log(capsys):
    chat, _, _ = make([FakeRaw('[]')])
    chat.complete("x", max_tokens=100)
    assert "[groq]" not in capsys.readouterr().out


def test_estimate_tokens():
    assert groq_llm.estimate_tokens("a" * 32) == 10


# --- fallback across models and keys ----------------------------------------


class _Stub:
    def __init__(self, label, replies):
        self.label, self.model, self.provider = label, label, "Groq"
        self.replies, self.calls = list(replies), 0

    def complete(self, prompt, *, max_tokens):
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return groq_llm.ChatResult(reply, "stop")


def test_overloaded_503_is_retried():
    err = RuntimeError("Error code: 503 - Groq is over capacity")
    chat, _, sleeps = make([err, FakeRaw("ok")])
    assert chat.complete("x", max_tokens=10).content == "ok"
    assert sleeps == [groq_llm.DEFAULT_RETRY_S]


def test_chat_sends_its_own_model():
    fake = FakeOpenAI([FakeRaw("ok")])
    groq_llm.GroqChat(fake, model=groq_llm.GROQ_BIG_MODEL).complete("x", max_tokens=10)
    assert fake.calls[0]["model"] == groq_llm.GROQ_BIG_MODEL


def test_fallback_uses_first_chat_that_answers():
    a = _Stub("main / 120b", [RuntimeError("500")])
    b = _Stub("main / 20b", ["ok"])
    assert groq_llm.FallbackChat([a, b]).complete("x", max_tokens=10).content == "ok"


def test_fallback_skips_a_chat_out_for_the_day():
    a = _Stub("main / 120b", [groq_llm.DailyLimit("about 5 minutes")])
    b = _Stub("main / 20b", ["one", "two"])
    chat = groq_llm.FallbackChat([a, b])
    assert chat.complete("x", max_tokens=10).content == "one"
    assert chat.complete("y", max_tokens=10).content == "two"
    assert a.calls == 1  # not asked again after its daily limit


def test_fallback_all_out_for_the_day_raises_daily_limit():
    a = _Stub("main / 120b", [groq_llm.DailyLimit(None)])
    b = _Stub("backup / 120b", [groq_llm.DailyLimit("about 3 minutes")])
    with pytest.raises(groq_llm.DailyLimit) as e:
        groq_llm.FallbackChat([a, b]).complete("x", max_tokens=10)
    assert (e.value.provider, e.value.wait) == ("Groq", "about 3 minutes")


def test_fallback_raises_last_error_when_all_fail():
    a = _Stub("main / 120b", [RuntimeError("first")])
    b = _Stub("main / 20b", [RuntimeError("second")])
    with pytest.raises(RuntimeError, match="second"):
        groq_llm.FallbackChat([a, b]).complete("x", max_tokens=10)


def test_build_chat_tries_both_models_on_main_then_backup(monkeypatch):
    monkeypatch.setenv("GROQ_KEY", "main")
    monkeypatch.setenv("GROQ_BACKUP_KEY", "backup")
    monkeypatch.setattr(groq_llm, "_chats", {})
    chat = groq_llm.build_chat()
    assert [c.label for c in chat.chats] == [
        f"main key / {groq_llm.GROQ_BIG_MODEL}", f"main key / {groq_llm.GROQ_MODEL}",
        f"backup key / {groq_llm.GROQ_BIG_MODEL}", f"backup key / {groq_llm.GROQ_MODEL}",
    ]


def test_backup_same_as_main_adds_nothing(monkeypatch):
    monkeypatch.setenv("GROQ_KEY", "same")
    monkeypatch.setenv("GROQ_BACKUP_KEY", "same")
    monkeypatch.setattr(groq_llm, "_chats", {})
    assert len(groq_llm.build_chat().chats) == len(groq_llm.GROQ_MODELS)


def test_backup_key_alone_is_enough(monkeypatch):
    monkeypatch.setenv("GROQ_KEY", "")
    monkeypatch.setenv("GROQ_BACKUP_KEY", "backup")
    monkeypatch.setattr(groq_llm, "_chats", {})
    assert groq_llm.build_chat() is not None


def test_chat_for_model_has_no_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_KEY", "main")
    monkeypatch.setattr(groq_llm, "_chats", {})
    chat = groq_llm.chat_for_model("gpt-oss-120b")
    assert isinstance(chat, groq_llm.GroqChat) and chat.model == groq_llm.GROQ_BIG_MODEL
    assert groq_llm.chat_for_model("groq").model == groq_llm.GROQ_MODEL
