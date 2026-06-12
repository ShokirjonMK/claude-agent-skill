"""Agent registri — Planner / Executor / Reviewer / Chat.

Agentlar spetsifikatsiyasi (rol, model kaliti, tool'lar, system prompt) toza ma'lumot
sifatida saqlanadi (SDK importisiz). `build_agent_definition` ularni runtime'da
`claude_agent_sdk.AgentDefinition` ga aylantiradi (runner.py'da chaqiriladi).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    role: str
    model_key: str  # secrets/config kaliti (masalan "EXECUTOR_MODEL")
    default_model: str  # to'liq ID fallback
    tools: tuple[str, ...]
    system_prompt: str
    expects_json: bool = False


PLANNER_PROMPT = """Sen Planner agentsan. Berilgan vazifani tahlil qil, qisqa strategiya yoz va
uni mustaqil, kichik subtask'larga bo'l. Faqat o'qish tool'lari (Read, Grep, Glob) bor.

MUHIM: Javobing FAQAT quyidagi JSON bo'lsin — boshqa hech narsa, markdown ham, izoh ham YO'Q:
{"strategy": "...", "subtasks": [{"id": "s1", "title": "...", "deps": []}, {"id": "s2", "title": "...", "deps": ["s1"]}]}

Qoidalar:
- `id` — qisqa local identifikator (s1, s2, ...).
- `deps` — shu subtask boshlanishidan oldin tugashi kerak bo'lgan subtask id'lari.
- Mustaqil ishlarni alohida subtask qil (parallel ishlashi uchun deps bo'sh bo'lsin)."""

EXECUTOR_PROMPT = """Sen Executor agentsan. Senga BITTA subtask beriladi. Uni oxirigacha bajar
(Read, Write, Edit, Bash, Grep, Glob bor). Tugatgach, nima qilganing va o'zgartirgan
fayllaring xulosasini qisqa matn ko'rinishida qaytar. Xavfli buyruqlardan saqlan —
ular bloklanadi."""

REVIEWER_PROMPT = """Sen Reviewer/Tester agentsan. Bajarilgan ishni ko'rib chiq va testlarni
ishga tushir (Read, Bash, Grep, Glob bor; Write/Edit YO'Q).

MUHIM: Javobing FAQAT quyidagi JSON bo'lsin — boshqa hech narsa YO'Q:
{"passed": true, "report": "qisqa xulosa: nima tekshirildi, testlar holati"}
Test o'tmasa yoki ish noto'g'ri bo'lsa: {"passed": false, "report": "muammo tavsifi"}"""

CHAT_PROMPT = """Sen yordamchi agentsan. Foydalanuvchi bilan suhbatlashib, vazifa yoki uning
natijasi bo'yicha muammolarni hal qilishga yordam berasan. O'qish tool'lari (Read, Grep,
Glob) bor. Aniq, qisqa va amaliy javob ber. Kontekstni suhbat davomida saqlaysan."""


AGENT_SPECS: dict[str, AgentSpec] = {
    "planner": AgentSpec(
        role="planner",
        model_key="PLANNER_MODEL",
        default_model="claude-opus-4-8",
        tools=("Read", "Grep", "Glob"),
        system_prompt=PLANNER_PROMPT,
        expects_json=True,
    ),
    "executor": AgentSpec(
        role="executor",
        model_key="EXECUTOR_MODEL",
        default_model="claude-sonnet-4-6",
        tools=("Read", "Write", "Edit", "Bash", "Grep", "Glob"),
        system_prompt=EXECUTOR_PROMPT,
        expects_json=False,
    ),
    "reviewer": AgentSpec(
        role="reviewer",
        model_key="REVIEWER_MODEL",
        default_model="claude-sonnet-4-6",
        tools=("Read", "Bash", "Grep", "Glob"),  # Write/Edit YO'Q
        system_prompt=REVIEWER_PROMPT,
        expects_json=True,
    ),
    "chat": AgentSpec(
        role="chat",
        model_key="CHAT_MODEL",
        default_model="claude-sonnet-4-6",
        tools=("Read", "Grep", "Glob"),
        system_prompt=CHAT_PROMPT,
        expects_json=False,
    ),
}


def build_agent_definition(spec: AgentSpec, model: str):
    """`AgentSpec` → `claude_agent_sdk.AgentDefinition` (SDK runtime'da kerak)."""
    from claude_agent_sdk import AgentDefinition  # lazy: SDK faqat ishga tushganda

    return AgentDefinition(
        description=f"Orchestra {spec.role} agent",
        prompt=spec.system_prompt,
        tools=list(spec.tools),
        model=model,
    )
