"""Orchestra — multi-agent orchestrator built on the Claude Agent SDK.

Yengil dispatcher (LLM emas) bazadan tugamagan vazifalarni o'qiydi, Planner →
Executor(parallel) → Reviewer agentlarni izolyatsiyalangan sessiyalarda chaqiradi.
Telegram bot (chat bilan), web admin-panel (RBAC), SSH server nazorati va dinamik
shifrlangan secrets bilan kengaytirilgan. Yagona haqiqat manbai — ma'lumotlar bazasi.
"""

__version__ = "2.0.0"
