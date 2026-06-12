"""Claude Agent SDK o'rami — `run_agent()`.

`claude_agent_sdk.query()` ni `ClaudeAgentOptions` bilan chaqiradi, in-process hook'lar
(PreToolUse → xavfli Bash deny; PostToolUse/SubagentStop → event signal) ulaydi, stream'dan
yakuniy natija matni va `session_id` ni ajratadi. JSON kutilganda toza parse qiladi.

SDK lazy import qilinadi (`claude_agent_sdk` o'rnatilmagan bo'lsa modul baribir import bo'ladi —
testlar mock orqali ishlaydi). Guard hook mantig'i alohida funksiya sifatida ham testlanadi.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Awaitable, Callable

from .agents import AGENT_SPECS, build_agent_definition
from .guards import is_dangerous, reason

# SDK ixtiyoriy — yo'q bo'lsa run_agent chaqirilganda aniq xato beriladi.
try:  # pragma: no cover - muhitga bog'liq
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, query as _sdk_query
except Exception:  # pragma: no cover
    ClaudeAgentOptions = None  # type: ignore[assignment]
    HookMatcher = None  # type: ignore[assignment]
    _sdk_query = None  # type: ignore[assignment]


# ── JSON ajratish ─────────────────────────────────────────────────────────────
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def extract_json(text: str) -> dict:
    """Matndan JSON ob'yektini ajratadi (```json fence'lar tozalanadi).

    Avval butun matnni parse qilishga urinadi; bo'lmasa birinchi {...} blokini qidiradi.
    Parse imkonsiz bo'lsa ValueError.
    """
    if text is None:
        raise ValueError("Bo'sh javob — JSON kutilgan edi")
    cleaned = text.strip()
    cleaned = _FENCE_RE.sub("", cleaned).strip()
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Fallback: birinchi muvozanatlangan {...} blok.
    start = cleaned.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(cleaned[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"Javobdan JSON ajratib bo'lmadi: {text[:200]!r}")


# ── Guard hook mantig'i (alohida testlanadi) ─────────────────────────────────
def _extract_bash_command(input_data: Any) -> str | None:
    """Hook input'idan Bash komandasini oladi (turli SDK shakllariga bardoshli)."""
    if isinstance(input_data, dict):
        tool_name = input_data.get("tool_name") or input_data.get("toolName")
        tool_input = input_data.get("tool_input") or input_data.get("toolInput") or {}
    else:
        tool_name = getattr(input_data, "tool_name", None)
        tool_input = getattr(input_data, "tool_input", {}) or {}
    if tool_name != "Bash":
        return None
    if isinstance(tool_input, dict):
        return tool_input.get("command")
    return getattr(tool_input, "command", None)


def evaluate_bash_safety(
    input_data: Any, patterns: list[str] | None = None
) -> tuple[bool, str | None]:
    """(bloklash_kerakmi, sabab) — xavfli Bash bo'lsa (True, pattern)."""
    cmd = _extract_bash_command(input_data)
    if cmd and is_dangerous(cmd, patterns):
        return True, reason(cmd, patterns)
    return False, None


def make_pretooluse_guard(
    on_block: Callable[[str, str], Awaitable[None]] | None = None,
    patterns: list[str] | None = None,
):
    """PreToolUse hook callback'ini yaratadi. Xavfli Bash bo'lsa `deny` qaytaradi va
    `on_block(command, reason)` chaqiriladi (audit/TG ogohlantirish uchun)."""

    async def _hook(input_data: Any, tool_use_id: Any = None, context: Any = None):
        blocked, why = evaluate_bash_safety(input_data, patterns)
        if blocked:
            cmd = _extract_bash_command(input_data) or ""
            if on_block:
                await on_block(cmd, why or "dangerous")
            # Claude Agent SDK PreToolUse deny shakli (hookSpecificOutput).
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Xavfli Bash komandasi bloklandi (guard): {why}"
                    ),
                }
            }
        return {}

    return _hook


# ── Stream'dan natija ajratish ────────────────────────────────────────────────
def _message_text(msg: Any) -> str | None:
    """Message'dan matn (result) ni ajratadi — ob'yekt yoki dict shaklida."""
    for attr in ("result", "text"):
        val = getattr(msg, attr, None)
        if isinstance(val, str):
            return val
    if isinstance(msg, dict):
        for k in ("result", "text"):
            if isinstance(msg.get(k), str):
                return msg[k]
    return None


def _message_session_id(msg: Any) -> str | None:
    for attr in ("session_id", "sessionId"):
        val = getattr(msg, attr, None)
        if isinstance(val, str):
            return val
    if isinstance(msg, dict):
        return msg.get("session_id") or msg.get("sessionId")
    return None


async def collect_stream(stream) -> tuple[str, str | None]:
    """Async message stream'dan yakuniy natija matni va session_id ni yig'adi."""
    result_text = ""
    session_id: str | None = None
    async for msg in stream:
        sid = _message_session_id(msg)
        if sid:
            session_id = sid
        txt = _message_text(msg)
        if txt is not None:
            result_text = txt  # oxirgi result matni g'olib
    return result_text, session_id


# ── Asosiy giriş nuqtasi ──────────────────────────────────────────────────────
async def run_agent(
    role: str,
    prompt: str,
    *,
    model: str,
    session_id: str | None = None,
    on_block: Callable[[str, str], Awaitable[None]] | None = None,
    dangerous_patterns: list[str] | None = None,
) -> tuple[str, str | None]:
    """Bitta agentni izolyatsiyalangan SDK sessiyasida ishga tushiradi.

    Returns: (natija_matni, session_id). `session_id` resume uchun saqlanadi.
    """
    if role not in AGENT_SPECS:
        raise ValueError(f"Noma'lum agent roli: {role!r}")
    if _sdk_query is None or ClaudeAgentOptions is None:
        raise RuntimeError(
            "claude-agent-sdk o'rnatilmagan. `pip install claude-agent-sdk` qiling."
        )

    spec = AGENT_SPECS[role]
    guard = make_pretooluse_guard(on_block=on_block, patterns=dangerous_patterns)

    # MUHIM: rol xulqi `system_prompt` orqali beriladi (agents={} — bu SDK'da subagent
    # ta'rifi, agent SIFATIDA ishlatmaydi). Har run_agent = bitta izolyatsiyalangan
    # sessiya: o'z system prompti + cheklangan tool to'plami.
    hooks = {"PreToolUse": [HookMatcher(matcher="Bash", hooks=[guard])]} if HookMatcher else None
    # Agentlar ilova kodini (/app) o'zgartirmasligi uchun alohida ish katalogi.
    workdir = os.environ.get("ORCHESTRA_WORKDIR") or None
    options = ClaudeAgentOptions(
        system_prompt=spec.system_prompt,
        allowed_tools=list(spec.tools),
        permission_mode="bypassPermissions",
        model=model,
        resume=session_id,
        hooks=hooks,
        cwd=workdir,
    )

    stream = _sdk_query(prompt=prompt, options=options)
    return await collect_stream(stream)
