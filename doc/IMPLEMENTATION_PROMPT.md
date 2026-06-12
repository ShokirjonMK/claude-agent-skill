# Implementation Prompt — "Orchestra" v2.0 (0 dan)
## Multi-Agent Orchestrator + Telegram bot (chat) + Web admin-panel (RBAC) + SSH server nazorati + dinamik secrets

> Bu promptni to'liq nusxalab Claude Code'ga (yoki boshqa AI agentga) bering.
> U butun loyihani noldan quradi. Prompt ichidagi talablar majburiy (MUST).
> To'liq talablar `TZ_Orchestra_v2.md` da; bu prompt amalga oshirish bo'yicha aniq ko'rsatma.

---

## ROLE

Sen tajribali Python backend muhandisisan. Vazifa — **Claude Agent SDK** (`claude-agent-sdk`)
asosida ishlovchi, ishonchli, qayta tiklanadigan (resumable) **multi-agent orkestratsiya
platformasini** noldan qurish. Platforma quyidagilarni o'z ichiga oladi: yengil orchestrator
dispatcher, to'liq ikki tomonlama Telegram bot (chat bilan), web admin-panel (FastAPI+HTMX,
RBAC, real-vaqt), SSH orqali server nazorati, va admin-paneldan dinamik shifrlangan
konfiguratsiya. Kod toza, type-hinted, async va testlar bilan bo'lsin.

## MAQSAD

Bitta vazifa berilganda tizim avtomatik ravishda:
1. **Planner** agent vazifani tahlil qiladi, strategiya yozadi va subtask'larga bo'ladi (JSON).
2. Orchestrator mustaqil subtask'lar uchun **Executor** agentlarni **parallel** ishga tushiradi.
3. Har bir ish **Reviewer** agentga uzatiladi — testdan o'tkazadi va tasdiqlaydi (o'tmasa retry).
4. Har holat o'zgarishida **Telegram** va **Web (SSE)** orqali real-vaqt hisobot (rol+ID+task+status).
5. Foydalanuvchi **TG `/chat`** yoki **Web Chat** orqali agent bilan suhbatlashib muammoni hal qiladi.
6. **Web admin-panel** barcha agentlarni, audit'ni (kim/qachon/nima), task'larni boshqaradi.
7. **SSH** orqali admin serverni to'liq nazorat qiladi (har komanda audit'da).
8. **Secrets** (API kalit, TG token, modellar, SSH) admin-paneldan dinamik kiritiladi (DB'da Fernet).
9. Orchestrator LLM kontekstini to'ldirmaydi — yengil dispatcher; barcha holat bazada.

## ASOSIY TAMOYIL (eng muhim)

- **Yagona haqiqat manbasi — ma'lumotlar bazasi (PostgreSQL)**, LLM emas.
- Orchestrator har sikl bazadan tugamagan vazifalarni o'qiydi → process/server uzilsa, **idempotent**
  davom etadi (subtask'lar takrorlanmaydi).
- Har bir agent chaqiruvi **toza, izolyatsiyalangan SDK sessiyasi**.
- Har bir muhim amal `audit_log`'ga (append-only) yoziladi.

---

## TEXNOLOGIK STEK (MUST)

- Python 3.11+
- `claude-agent-sdk` (asosiy agent runtime — `query`, `ClaudeAgentOptions`, `AgentDefinition`, hooks)
- **PostgreSQL** (`asyncpg`) — default baza; `aiosqlite` (SQLite) test/local; ikkalasi `AsyncDB` interfeysi orqali
- `fastapi` + `uvicorn` + `jinja2` + HTMX + Tailwind (web admin-panel, SSE + WebSocket)
- `httpx` (Telegram HTTP)
- `asyncssh` (SSH terminal/exec)
- `cryptography` (Fernet — secrets shifrlash), `bcrypt`/`argon2-cffi` (parol hash), `pyjwt` (auth)
- `pydantic` / `pydantic-settings` (config + structured output validatsiya)
- `pytest` + `pytest-asyncio`
- Docker + docker-compose
- `uv` yoki `pip`

---

## CLAUDE AGENT SDK ESLATMALARI (MUST — to'g'ri ishlatish)

- `from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition`
- `query(prompt, options)` — async generator; message stream'dan yakuniy `result` matn va `session_id` ajratiladi.
- `ClaudeAgentOptions`: `agents={role: AgentDefinition(...)}`, `allowed_tools=[..., "Agent"]`,
  `permission_mode="bypassPermissions"`, `resume=session_id` (resume uchun), `model=<id>`, `hooks={...}`.
- **Model ID'lar (config/secrets'dan):** to'liq ID tavsiya etiladi — Opus 4.8 = `claude-opus-4-8`,
  Sonnet 4.6 = `claude-sonnet-4-6`, Haiku 4.5 = `claude-haiku-4-5`. SDK `opus`/`sonnet`/`haiku`
  aliaslarini ham qabul qiladi (default), lekin production'da to'liq ID barqarorroq.
- **Hooks:** `PreToolUse` (Bash matcher) — `guards.is_dangerous()` bilan deny; `SubagentStop`/`PostToolUse` —
  reporter'ga signal. Hook'lar in-process (`options.hooks`).
- Subagent o'z subagentini spawn qila olmaydi — ierarxiya bir qavatli.

---

## LOYIHA TUZILMASI (MUST — aynan shu tuzilma)

```
orchestra/
├─ pyproject.toml
├─ .env.example
├─ README.md
├─ Dockerfile
├─ docker-compose.yml
├─ src/orchestra/
│  ├─ __init__.py
│  ├─ config.py            # pydantic Settings (bootstrap .env)
│  ├─ models.py            # Task, AgentRun, TaskStatus(Enum), User, Server, Role(Enum)
│  ├─ db.py                # AsyncDB interfeys + PostgresDB + SQLiteDB + initdb
│  ├─ secrets.py           # Fernet, get_secret/set_secret, layered resolver
│  ├─ agents.py            # AgentDefinition registry (planner/executor/reviewer/chat)
│  ├─ runner.py            # run_agent(): SDK query() o'rami + hooks
│  ├─ guards.py            # is_dangerous(cmd)
│  ├─ reporter.py          # TelegramReporter (outbound)
│  ├─ orchestrator.py      # orchestrator_loop + handle_task (idempotent)
│  ├─ chat.py              # ChatSession: agent bilan suhbat (resume)
│  ├─ ssh.py               # SSHManager: asyncssh exec/terminal + audit
│  ├─ rbac.py              # Role enum, require_role
│  ├─ telegram_bot.py      # inbound: /task /status /tasks /chat /endchat
│  ├─ web/
│  │  ├─ __init__.py
│  │  ├─ app.py            # FastAPI ilova (sahifalarni ulaydi)
│  │  ├─ auth.py           # login, JWT/session, parol hash
│  │  ├─ sse.py            # event broadcaster (SSE)
│  │  ├─ routes/           # dashboard.py tasks.py chat.py audit.py ssh.py servers.py secrets.py users.py
│  │  ├─ templates/        # base.html + har sahifa (Jinja2 + HTMX + Tailwind CDN)
│  │  └─ static/           # app.js, terminal.js
│  └─ cli.py               # entrypoint: run / bot / web / submit / status / createadmin / initdb
├─ .claude/settings.json   # Claude Code PreToolUse hook (ixtiyoriy path)
├─ scripts/guard_bash.py   # PreToolUse hook skripti (exit 2 = bloklash)
└─ tests/
   ├─ test_db.py  test_runner.py  test_orchestrator.py
   ├─ test_secrets.py  test_rbac.py  test_chat.py  test_web.py
```

---

## MA'LUMOTLAR MODELI (MUST)

`TaskStatus` enum: `PENDING, ANALYZING, PLANNED, EXECUTING, REVIEWING, DONE, FAILED`
(v1'dagi o'lik `TESTING` YO'Q — Reviewer testni REVIEWING ichida bajaradi).
`Role` enum: `VIEWER, OPERATOR, ADMIN` (tartiblangan: viewer < operator < admin).

**tasks**: `id` TEXT PK (uuid4), `parent_id` TEXT NULL, `kind` TEXT (root|subtask), `title`, `description`,
`strategy` TEXT NULL, `deps` TEXT NULL (JSON), `status` TEXT, `result` TEXT NULL, `attempts` INT DEFAULT 0,
`agent_id` TEXT NULL, `session_id` TEXT NULL, `created_at`, `updated_at`.

**agent_runs**: `id` TEXT PK (`executor-ab12cd`), `task_id` FK, `role`, `model`, `status`, `started_at`, `finished_at`.

**events**: `id` PK serial/autoincrement, `task_id`, `agent_id`, `status`, `message`, `created_at`.

**users**: `id` TEXT PK (uuid4), `username` UNIQUE, `password_hash`, `role` TEXT, `is_active` BOOL, `last_login`, `created_at`.

**secrets**: `key` TEXT PK, `value_encrypted` TEXT (Fernet), `description` TEXT, `is_secret` BOOL, `updated_by` TEXT, `updated_at`.

**servers**: `id` TEXT PK (uuid4), `name`, `host`, `port` INT DEFAULT 22, `username`, `auth_method` TEXT (password|key), `secret_ref` TEXT (→secrets.key), `created_by`, `created_at`.

**ssh_commands**: `id` PK serial, `server_id` FK, `user_id` FK, `command`, `output` TEXT, `exit_code` INT, `duration_ms` INT, `created_at`.

**chat_messages**: `id` PK serial, `task_id` NULL, `chat_session_id` TEXT, `channel` TEXT (telegram|web), `direction` TEXT (in|out), `role` TEXT (user|agent), `content` TEXT, `user_id` NULL, `created_at`.

**audit_log** (append-only): `id` PK serial, `actor_type` TEXT (user|agent|system), `actor_id`, `action` TEXT, `target` TEXT, `details` TEXT (JSON), `created_at`.

`db.py`da `AsyncDB` abstrakt interfeys: `next_pending_root, save_task, save_subtasks, list_subtasks,
update_status, set_result, increment_attempts, log_event, has_subtasks` (idempotent resume uchun),
`get_user, save_user, list_users`, `get_secret_row, set_secret_row, list_secrets`, `save_server, list_servers,
log_ssh_command, save_chat_message, list_chat_messages, log_audit, list_audit`. `PostgresDB` (asyncpg) va
`SQLiteDB` (aiosqlite) implementatsiyalari. `initdb()` jadvallarni avtomatik yaratadi.

---

## AGENTLAR (MUST — `agents.py`)

`AgentDefinition` orqali to'rt agent. Modellar `secrets`/`config`'dan (default aliaslar):

1. **planner** (`PLANNER_MODEL`=opus, tools: Read, Grep, Glob) — FAQAT JSON:
   `{"strategy": "...", "subtasks": [{"id": "s1", "title": "...", "deps": []}]}` (markdown ham yo'q).
2. **executor** (`EXECUTOR_MODEL`=sonnet, tools: Read, Write, Edit, Bash, Grep, Glob) — bitta subtask'ni bajaradi, xulosa qaytaradi.
3. **reviewer** (`REVIEWER_MODEL`=sonnet, tools: Read, Bash, Grep, Glob) — FAQAT JSON: `{"passed": true, "report": "..."}`. (Write/Edit YO'Q.)
4. **chat** (`CHAT_MODEL`=sonnet, tools: Read, Grep, Glob) — foydalanuvchi bilan muammoni hal qilish suhbati.

---

## RUNNER (MUST — `runner.py`)

`async def run_agent(role, prompt, *, session_id=None) -> tuple[str, str]`:
- `claude_agent_sdk.query()` chaqiradi; `ClaudeAgentOptions` (yuqoridagi SDK eslatmalari bo'yicha).
- In-process hooks: `PreToolUse` (Bash) → `guards.is_dangerous` → deny + audit/TG; `SubagentStop`/`PostToolUse` → reporter.
- Stream'dan `result` va `session_id` ajratiladi.
- JSON kutilganda toza parse (```json fence tozalanadi); xato bo'lsa qayta so'rash.

---

## ORCHESTRATOR (MUST — `orchestrator.py`)

`async def handle_task(task)`:
1. **Idempotent:** agar `db.has_subtasks(task.id)` → rejalashtirishni o'tkazib, DONE bo'lmagan subtask'lardan davom et.
2. status → ANALYZING, hisobot.
3. `run_agent("planner", task.description)` → JSON → strategy + subtasks → `save_subtasks` → PLANNED.
4. `deps==[]` subtask'lar `asyncio.Semaphore(MAX_PARALLEL)` + `asyncio.gather` bilan parallel; bog'liqlari topologik tartibda.
5. Har subtask: EXECUTING → executor → REVIEWING → reviewer → `passed` ? DONE : (attempts+1, retry yoki FAILED). Har bosqichda reporter + SSE.
6. Barcha DONE → root DONE → yakuniy hisobot.

`async def orchestrator_loop()`: `db.next_pending_root()` → `handle_task` yoki `sleep(POLL_INTERVAL)`. Tugamagan vazifalar idempotent tiklanadi. `MAX_RETRY/POLL_INTERVAL/MAX_PARALLEL` resolverdan (secrets > .env > default).

---

## CHAT (MUST — `chat.py`)

`ChatSession`: foydalanuvchi xabari → `run_agent("chat", msg, session_id=chat_session_id)` → javob.
`session_id` saqlanadi (resume → kontekst). Har xabar `save_chat_message` + `log_audit`. TG va Web ikkalasi ishlatadi.

---

## TELEGRAM (MUST)

`reporter.py` — `TelegramReporter.report(agent_id, role, task_id, status_text)`: `httpx` `sendMessage`, format:
```
🤖 *{role}* `{agent_id}`
📋 task `{task_id[:8]}`
{status_text}
```
Har report `events` + `audit_log` + SSE broadcast.

`telegram_bot.py` (inbound, long-polling `getUpdates`): `/task <matn>` (PENDING root), `/status <id>`, `/tasks`,
`/chat <task_id>` (suhbat rejimi — keyingi xabarlar chat agentga, kontekst resume), `/endchat`.

---

## WEB ADMIN-PANEL (MUST — `web/`)

FastAPI + Jinja2 + HTMX + Tailwind (CDN). Real-vaqt: SSE (dashboard/task) + WebSocket (SSH terminal, chat).

**auth.py:** login (username+parol → bcrypt/argon2 tekshirish → JWT yoki imzolangan session cookie).
**rbac.py:** `require_role(min_role)` dependency. Rollar: viewer < operator < admin.

**Sahifalar (routes/):**
- `dashboard` (viewer): faol task/agent, real-vaqt oqim (SSE) — rol+ID+holat+joriy qadam.
- `tasks` (ko'rish: viewer; yaratish: operator): ro'yxat/filtr/batafsil; yangi task; retry.
- `chat` (operator): agent bilan suhbat (task bog'langan), WebSocket live.
- `audit` (viewer): `audit_log` timeline, actor/action/target/vaqt filtr.
- `ssh` (admin): server tanlash + to'liq WebSocket terminal; komanda tarixi.
- `servers` (admin): SSH serverlar CRUD.
- `secrets` (admin): dinamik konfiguratsiya — kalit/qiymat (shifrlangan), tahrir/qo'shish.
- `users` (admin): foydalanuvchilar + rollar CRUD.

Har muhim amal `log_audit(actor=user, action, target, details)`.

---

## SSH (MUST — `ssh.py`)

`SSHManager` (asyncssh):
- `run_command(server, command) -> (stdout, stderr, exit_code)` — bir martalik.
- `interactive_shell(server, websocket)` — to'liq PTY terminal WebSocket bilan.
- Auth ma'lumoti `servers.secret_ref` → `secrets` deshifr.
- **Audit majburiy:** har komanda `log_ssh_command` + `log_audit`.
- Helper'lar: `install_project`, `update_project`, `restart_services`, `tail_logs` (UI tugmalari).

> README'da: cheklovsiz SSH yuqori xavf — faqat admin, to'liq audit, HTTPS + IP cheklov, production izolyatsiya.

---

## SECRETS / DINAMIK CONFIG (MUST — `secrets.py` + `config.py`)

- `config.py` pydantic `Settings` — `.env` faqat **bootstrap**: `DB_DSN` (Postgres DSN yoki SQLite path),
  `SECRET_ENC_KEY` (Fernet master kalit), `WEB_JWT_SECRET`, birinchi admin (`BOOTSTRAP_ADMIN_USER/PASS`).
- `secrets.py`: `Fernet(SECRET_ENC_KEY)`; `get_secret(key)`, `set_secret(key, value, by_user)`;
  **layered resolver** `get_config(key, default)` → DB `secrets` > `.env` > default.
- Dinamik (UI'dan): `ANTHROPIC_API_KEY`, `TG_BOT_TOKEN`, `TG_CHAT_ID`, `PLANNER_MODEL`, `EXECUTOR_MODEL`,
  `REVIEWER_MODEL`, `CHAT_MODEL`, `MAX_RETRY`, `POLL_INTERVAL`, `MAX_PARALLEL`, SSH parol/kalitlar.
- Orchestrator/bot/web har sikl/so'rov boshida resolverdan o'qiydi → o'zgarish keyingi siklda qo'llanadi (qayta deploy'siz).
- `SECRET_ENC_KEY` hech qachon DB/kodda emas — faqat muhit.

---

## XAVFSIZLIK (MUST — `guards.py` + RBAC + `.claude/settings.json`)

- `guards.is_dangerous(cmd) -> bool` — `rm -rf`, `git push`, `:(){`, `mkfs`, `dd if=`, `curl ... | sh`,
  `shutdown`, `reboot` (konfiguratsiyalanadigan blacklist). **Faqat birinchi qatlam** — asosiysi izolyatsiya.
- Runner `PreToolUse` hook → xavfli bo'lsa deny + audit/TG.
- Executor: Bash bor; Reviewer: Write/Edit YO'Q.
- RBAC har endpoint'da; SSH/secrets/users faqat admin.
- Parol hash, JWT imzo, secrets Fernet, audit append-only.
- `.claude/settings.json` — `PreToolUse` Bash matcher `scripts/guard_bash.py` (exit 2 = bloklash).
- README: production'da executor'larni cheklangan Linux user/konteyner ostida; web panel HTTPS ortida.

---

## DOCKER (MUST)

- `Dockerfile`: `python:3.11-slim` + paketlar + `claude-agent-sdk`/Claude Code bog'liqliklari.
- `docker-compose.yml`: **postgres** (volume), **orchestrator** (`cli run`), **bot** (`cli bot`),
  **web** (`cli web`, port 8000). Umumiy `.env` (bootstrap), umumiy tarmoq.

---

## TESTLAR (MUST — `tests/`)

- `test_db`: jadvallar, CRUD, next_pending, `has_subtasks` idempotent resume.
- `test_runner`: SDK mock → JSON parse; xavfli Bash bloklanadi.
- `test_orchestrator`: planner mock (2 subtask) → 2 executor parallel → reviewer pass → DONE; retry; **resume idempotentligi** (subtask ikkilanmaydi).
- `test_secrets`: Fernet shifr/deshifr; layered resolver (DB > .env > default).
- `test_rbac`: viewer/operator/admin endpoint ruxsatlari.
- `test_chat`: chat agent resume kontekst saqlaydi (mock).
- `test_web`: login, asosiy sahifalar, SSE oqim (FastAPI TestClient).
- SDK chaqiruvlari mock orqali (haqiqiy API'siz).

---

## QABUL MEZONLARI (Acceptance — MUST)

1. `submit`/`/task` → `run` → TG va Web'da: planner, har executor (ID), har reviewer (ID), yakuniy xulosa.
2. Subtask'lar haqiqatan parallel (log/dashboard vaqtlar ustma-ust).
3. Reviewer fail → `MAX_RETRY` gacha qayta ijro.
4. Orchestrator to'xtatib qayta ishga tushirilsa, tugamagan vazifa **takrorlanmasdan** davom etadi.
5. Xavfli Bash bloklanadi + TG/audit ogohlantirish.
6. TG `/chat` orqali agent bilan suhbatlashib muammo hal qilinadi (kontekst saqlanadi).
7. Web dashboard real vaqtda agentlarni; audit kim/qachon/nimani ko'rsatadi.
8. SSH orqali admin serverga komanda yuboradi; har komanda audit'da.
9. Secrets UI'dan o'zgartiriladi, keyingi siklda qo'llanadi (qayta deploy'siz).
10. RBAC: viewer yoza olmaydi; operator secret/SSH/users'ga kira olmaydi; admin to'liq.
11. `pytest` to'liq yashil; README to'liq.

---

## ISH TARTIBI (sen, AI agent, quyidagicha ishla)

1. `pyproject.toml`, `config.py`, `models.py`, `db.py` (Postgres+SQLite+initdb), `secrets.py` → `test_db`, `test_secrets`.
2. `agents.py`, `runner.py`, `guards.py` → `test_runner`.
3. `reporter.py`, `orchestrator.py` (idempotent), `chat.py` → `test_orchestrator`, `test_chat`.
4. `telegram_bot.py` (inbound + chat).
5. `web/`: `auth.py`, `rbac.py`, `sse.py`, `app.py`, `routes/` (dashboard, tasks, audit) + templates → `test_rbac`, `test_web`.
6. `web/routes/` (ssh, servers, secrets, users), `ssh.py` (WebSocket terminal).
7. `cli.py` (run/bot/web/submit/status/createadmin/initdb), Docker, `.claude/settings.json`, `scripts/guard_bash.py`, `README.md`.
8. Har bosqichda `pytest` yashilga keltir, keyin davom et.
9. Tugagach, README'da: matn ko'rinishidagi arxitektura diagrammasi, o'rnatish (Docker + serverga SSH orqali),
   `.env` (bootstrap), RBAC, xavfsizlik, va misol ishga tushirish buyruqlari.

Boshla.
