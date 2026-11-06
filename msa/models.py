"""One way to call every model, so the tests treat them all the same.

A model name looks like "provider:model", for example "claude:claude-haiku-5-5",
"groq:llama-3.3-70b-versatile" or "ollama:llama3.1". "stub:" models are fake and
exist only to prove the tests can catch bad behaviour, at no cost.

Claude's automatic fallback to another model is deliberately not used here. A
test has to measure the model named, so a refusal counts as a failed call.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class Reply:
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    error: str = ""


def call_model(model: str, system: str, user: str, case: dict | None = None) -> Reply:
    """Call a model. Failures come back as Reply.error so a run can continue."""
    provider, _, name = model.partition(":")
    start = time.perf_counter()
    try:
        if provider == "claude":
            reply = _call_claude(name, system, user)
        elif provider == "groq":
            reply = _call_groq(name, system, user)
        elif provider == "ollama":
            reply = _call_ollama(name, system, user)
        elif provider == "stub":
            reply = _call_stub(name, case or {})
        else:
            raise ValueError(f"unknown provider in {model!r}")
    except Exception as exc:  # A failed call is a test result, not a crash.
        reply = Reply(error=f"{type(exc).__name__}: {str(exc)[:200]}")
    reply.seconds = round(time.perf_counter() - start, 2)
    return reply


def _call_claude(name: str, system: str, user: str) -> Reply:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=name,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if response.stop_reason == "refusal":
        return Reply(error="model refused the request",
                     input_tokens=response.usage.input_tokens,
                     output_tokens=response.usage.output_tokens)
    text = "".join(block.text for block in response.content if block.type == "text")
    return Reply(text=text, input_tokens=response.usage.input_tokens,
                 output_tokens=response.usage.output_tokens)


def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _call_groq(name: str, system: str, user: str) -> Reply:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set")
    data = _post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"model": name, "max_tokens": 1000, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}]},
        {"Authorization": f"Bearer {key}", "User-Agent": "model-switch-agent"}, 60)
    usage = data.get("usage", {})
    return Reply(text=data["choices"][0]["message"]["content"],
                 input_tokens=usage.get("prompt_tokens", 0),
                 output_tokens=usage.get("completion_tokens", 0))


def _call_ollama(name: str, system: str, user: str) -> Reply:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    data = _post_json(f"{host}/api/chat", {"model": name, "stream": False, "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": user}]}, {}, 300)
    return Reply(text=data.get("message", {}).get("content", ""),
                 input_tokens=data.get("prompt_eval_count", 0),
                 output_tokens=data.get("eval_count", 0))


def _call_stub(name: str, case: dict) -> Reply:
    """Fake models used to test the test."""
    if name == "broken":
        raise RuntimeError("simulated outage")
    if name == "liar":
        if case.get("kind") == "field":
            return Reply(text='{"action": "fill", "value": "Meera Joshi 123456"}', input_tokens=100, output_tokens=20)
        return Reply(text="She led 40 engineers at Nimbus Solutions Ltd and grew revenue 300%.",
                     input_tokens=100, output_tokens=20)
    if name == "perfect":
        if case.get("kind") == "field":
            action = case["want"]
            value = case.get("value", "") if action == "fill" else ""
            return Reply(text=json.dumps({"action": action, "value": value}), input_tokens=100, output_tokens=20)
        return Reply(text="She launched an auto-debit feature and served clinics.", input_tokens=100, output_tokens=20)
    raise ValueError(f"unknown stub {name!r}")
