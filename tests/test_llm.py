import asyncio
from types import SimpleNamespace
import pytest
from pydantic import BaseModel
from job_intel.core.llm import RunLLM, use_llm, generate, extract_json_object


class Result(BaseModel):
    value: str


def test_json_first_object():
    assert extract_json_object('{"a":1} then {"b":2}') == {"a": 1}


def test_openai_uses_isolated_key_and_structured_output(monkeypatch):
    import openai

    requests = []

    class Client:
        def __init__(self, **kwargs):
            self.key = kwargs["api_key"]
            self.responses = SimpleNamespace(parse=self.parse)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def parse(self, **kwargs):
            requests.append((self.key, kwargs))
            return SimpleNamespace(
                output_parsed=Result(value=self.key), usage=SimpleNamespace(input_tokens=10, output_tokens=5)
            )

    monkeypatch.setattr(openai, "OpenAI", Client)

    async def call(key):
        with use_llm(RunLLM("openai", key, "model")):
            return await asyncio.to_thread(generate, Result, "Extract", {})

    async def both():
        return await asyncio.gather(call("key-a"), call("key-b"))

    results = asyncio.run(both())
    assert {r.value for r in results} == {"key-a", "key-b"}
    assert all(not kw["store"] and kw["text_format"] is Result for _, kw in requests)


def test_exceptions_do_not_expose_keys(monkeypatch):
    import openai

    def fail(**kwargs):
        raise RuntimeError("SECRET-API-KEY")

    monkeypatch.setattr(openai, "OpenAI", fail)
    with use_llm(RunLLM("openai", "SECRET-API-KEY", "model")):
        with pytest.raises(RuntimeError) as error:
            generate(Result, "Extract", {})
    assert "SECRET" not in str(error.value)


def test_call_and_size_budgets():
    with use_llm(RunLLM("openai", "test", "model", max_calls=0)):
        with pytest.raises(RuntimeError, match="budget"):
            generate(Result, "Extract", {})
    with use_llm(RunLLM("openai", "test", "model")):
        with pytest.raises(ValueError, match="size"):
            generate(Result, "Extract", {"text": "x" * 60001})


def test_anthropic_structured_tool_response(monkeypatch):
    import anthropic

    captured = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "personal-anthropic"
            self.messages = SimpleNamespace(create=self.create)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            captured.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", name="result", input={"value": "ok"})],
                usage=SimpleNamespace(input_tokens=10, output_tokens=2),
            )

    monkeypatch.setattr(anthropic, "Anthropic", Client)
    with use_llm(RunLLM("anthropic", "personal-anthropic", "model")):
        assert generate(Result, "Extract", {}).value == "ok"
    assert captured[0]["tool_choice"] == {"type": "tool", "name": "result"}
