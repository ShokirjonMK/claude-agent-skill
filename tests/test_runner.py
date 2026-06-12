"""Runner testlari: JSON ajratish, stream yig'ish, guard hook (xavfli Bash deny)."""

from __future__ import annotations

import types

import pytest

from orchestra import runner
from orchestra.runner import (
    collect_stream,
    evaluate_bash_safety,
    extract_json,
    make_pretooluse_guard,
)


# ── extract_json ──────────────────────────────────────────────────────────────
def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    text = '```json\n{"strategy": "x", "subtasks": []}\n```'
    assert extract_json(text) == {"strategy": "x", "subtasks": []}


def test_extract_json_with_surrounding_text():
    text = 'Mana natija:\n{"passed": true, "report": "ok"}\nTamom.'
    assert extract_json(text) == {"passed": True, "report": "ok"}


def test_extract_json_invalid_raises():
    with pytest.raises(ValueError):
        extract_json("hech qanday json yo'q")


# ── Guard hook ────────────────────────────────────────────────────────────────
def test_evaluate_bash_safety_dangerous():
    inp = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
    blocked, why = evaluate_bash_safety(inp)
    assert blocked is True and why


def test_evaluate_bash_safety_safe():
    inp = {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}}
    assert evaluate_bash_safety(inp) == (False, None)


def test_evaluate_non_bash_ignored():
    inp = {"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}}
    assert evaluate_bash_safety(inp) == (False, None)


async def test_pretooluse_guard_denies_and_calls_on_block():
    blocked_calls = []

    async def on_block(cmd, why):
        blocked_calls.append((cmd, why))

    guard = make_pretooluse_guard(on_block=on_block)
    out = await guard({"tool_name": "Bash", "tool_input": {"command": "shutdown now"}})
    assert out.get("decision") == "block"
    assert blocked_calls and blocked_calls[0][0] == "shutdown now"


async def test_pretooluse_guard_allows_safe():
    guard = make_pretooluse_guard()
    out = await guard({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert out == {}


# ── collect_stream ────────────────────────────────────────────────────────────
async def _fake_stream(messages):
    for m in messages:
        yield m


async def test_collect_stream_extracts_result_and_session():
    msgs = [
        types.SimpleNamespace(session_id="sess-42"),
        types.SimpleNamespace(result="oraliq"),
        types.SimpleNamespace(result="yakuniy natija"),
    ]
    text, sid = await collect_stream(_fake_stream(msgs))
    assert text == "yakuniy natija"
    assert sid == "sess-42"


async def test_collect_stream_dict_messages():
    msgs = [{"session_id": "s1"}, {"result": "ok"}]
    text, sid = await collect_stream(_fake_stream(msgs))
    assert text == "ok" and sid == "s1"


# ── run_agent (SDK mock) ──────────────────────────────────────────────────────
async def test_run_agent_with_mocked_sdk(monkeypatch):
    captured = {}

    class FakeOptions:
        def __init__(self, **kw):
            captured.update(kw)

    def fake_query(*, prompt, options):
        async def gen():
            yield {"session_id": "sess-run"}
            yield {"result": '{"strategy":"s","subtasks":[]}'}

        return gen()

    monkeypatch.setattr(runner, "ClaudeAgentOptions", FakeOptions)
    monkeypatch.setattr(runner, "_sdk_query", fake_query)
    # AgentDefinition qurilishini ham mock qilamiz (SDK yo'q).
    monkeypatch.setattr(runner, "build_agent_definition", lambda spec, model: object())

    text, sid = await runner.run_agent("planner", "Vazifa", model="claude-opus-4-8")
    assert sid == "sess-run"
    assert extract_json(text) == {"strategy": "s", "subtasks": []}
    # Options to'g'ri qurildimi.
    assert captured["permission_mode"] == "bypassPermissions"
    assert "Agent" in captured["allowed_tools"]
    assert captured["model"] == "claude-opus-4-8"


async def test_run_agent_unknown_role():
    with pytest.raises(ValueError):
        await runner.run_agent("nobody", "x", model="m")
