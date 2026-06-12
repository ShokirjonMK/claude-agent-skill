# TEXNIK TOPSHIRIQ (TZ) — "Orchestra" v2.0
## Ko'p agentli orkestratsiya platformasi + Telegram bot + Web admin-panel + Server nazorati

> **Versiya:** 2.0
> **Sana:** 2026-06-12
> **Asos:** Claude Agent SDK (Python)
> **Holat:** Tasdiqlash uchun
> **v1.0 dan farqi:** TG bot (chat bilan), web admin-panel (RBAC), SSH server nazorati, dinamik konfiguratsiya (DB'da shifrlangan), PostgreSQL default, Docker-first deploy.

---

## 1. Hujjat haqida va maqsad

Ushbu TZ "Orchestra" tizimining **v2.0** talablarini belgilaydi. v1.0 yadro (Planner → Executor → Reviewer multi-agent dispatcher) saqlanadi va quyidagilar bilan kengaytiriladi:

1. **To'liq ikki tomonlama Telegram bot** — vazifa berish, natija olish, va muammolarni hal qilish uchun agent bilan **chatlashish**.
2. **Web admin-panel** — barcha agentlar nima qilayotganini real vaqtda kuzatish, kim/qachon/nima qilganini audit qilish, to'liq boshqaruv.
3. **Server nazorati** — proyekt serverga o'rnatiladi; admin-paneldan SSH orqali serverni boshqarish.
4. **Dinamik konfiguratsiya** — API kalitlar, tokenlar, modellar, SSH ma'lumotlari admin-panel orqali kiritiladi (DB'da Fernet bilan shifrlangan).
5. **RBAC** — admin / operator / viewer rollari.

### 1.1. Asosiy tamoyil (o'zgarmaydi)
- **Yagona haqiqat manbai — ma'lumotlar bazasi**, LLM emas.
- Orchestrator yengil dispatcher: bazadan o'qiydi, agentni izolyatsiyalangan sessiyada chaqiradi, natijani bazaga qaytaradi.
- Har bir holat o'zgarishi audit'ga yoziladi va real vaqtda (TG + Web SSE) ko'rsatiladi.
- Process/server uzilsa, bazadan davom etadi (resumable).

---

## 2. Arxitektura qarorlari (tasdiqlangan)

| Soha | Qaror | Sabab |
|------|-------|-------|
| Web admin UI | **FastAPI + Jinja2/HTMX + Tailwind**, real-vaqt SSE/WebSocket | Yengil, bitta Python backend, dashboard uchun ideal |
| Server nazorati | **To'liq SSH terminal** (asyncssh) — cheklovsiz, lekin to'liq audit'ga yoziladi | Foydalanuvchi to'liq nazoratni tanladi; xavf audit + RBAC bilan yumshatiladi |
| Ma'lumotlar bazasi | **PostgreSQL (asyncpg) default**; SQLite test/local uchun | Web + bot + orchestrator konkurent yozadi |
| Auth & secrets | **Ko'p foydalanuvchi + RBAC** (admin/operator/viewer); secrets DB'da Fernet bilan shifrlangan | Dinamik kalit boshqaruvi talabi |

---

## 3. Tizimning umumiy ko'rinishi

```
                          ┌─────────────────────────────────────────────┐
                          │              PostgreSQL (yagona manba)        │
                          │  tasks · agent_runs · events · chat_messages  │
                          │  users · roles · secrets · servers            │
                          │  ssh_commands · audit_log                     │
                          └───────▲───────────▲───────────────▲──────────┘
                                  │           │               │
              ┌───────────────────┘           │               └────────────────────┐
              │                                │                                    │
     ┌────────┴────────┐            ┌──────────┴──────────┐              ┌──────────┴──────────┐
     │  ORCHESTRATOR    │            │   TELEGRAM BOT       │              │   WEB ADMIN-PANEL    │
     │  (dispatcher)    │            │  (inbound+chat)      │              │  (FastAPI+HTMX)      │
     │                  │            │                      │              │                      │
     │ planner          │            │ /task, /status,      │              │ Dashboard (live SSE) │
     │ executor (xN ‖)  │            │ /tasks, /chat        │              │ Tasks / Agents       │
     │ reviewer         │            │ + agent bilan chat   │              │ Audit timeline       │
     │  ↕ Claude Agent  │            │ + outbound hisobot   │              │ SSH terminal         │
     │     SDK          │            │                      │              │ Secrets (dinamik)    │
     └──────┬───────────┘            └──────────────────────┘              │ Users / RBAC         │
            │ run_agent()                                                  └──────────────────────┘
            ▼
   ┌──────────────────┐    PreToolUse hook (guards) → xavfli Bash bloklanadi
   │ Claude Agent SDK │    SubagentStop / PostToolUse hook → reporter signal
   │ izolyatsiya      │
   └──────────────────┘
```

**Servislar (Docker Compose):** `postgres`, `orchestrator`, `bot`, `web`. Hammasi bitta tarmoq + bazaga ulanadi; konfiguratsiya `.env` (bootstrap) + DB (dinamik).

---

## 4. Funksional talablar

| Kod | Talab |
|-----|-------|
| **FR-1** | Vazifa CLI, Telegram (`/task`) yoki Web UI orqali qabul qilinadi. |
| **FR-2** | Planner agent vazifani tahlil qilib, strategiya + subtask JSON qaytaradi. |
| **FR-3** | Bog'liqliksiz subtask'lar `asyncio.gather` bilan parallel ishga tushadi (`MAX_PARALLEL` chegarasi). |
| **FR-4** | Bog'liq subtask'lar o'z `deps` tugagach, topologik tartibda bajariladi. |
| **FR-5** | Har subtask Reviewer agent tomonidan testdan o'tkaziladi (JSON: `{passed, report}`). |
| **FR-6** | Reviewer fail qaytarsa, subtask `MAX_RETRY` gacha qayta bajariladi. |
| **FR-7** | Har holat o'zgarishi TG (rol+ID+task+status) va Web (SSE) orqali real vaqtda ko'rsatiladi va `events`/`audit_log`'ga yoziladi. |
| **FR-8** | Barcha vazifa/agent/chat holatlari bazada saqlanadi. |
| **FR-9** | Tizim qayta ishga tushganda tugamagan vazifalarni **idempotent** tiklab davom ettiradi (subtask'lar takrorlanmaydi). |
| **FR-10** | Agentlar soni Planner natijasiga qarab runtime'da dinamik aniqlanadi. |
| **FR-11** | **TG chat:** foydalanuvchi `/chat <task_id>` orqali agent bilan suhbatlashib, muammoni hal qiladi; suhbat tarixi `chat_messages`'ga yoziladi va kontekst SDK `resume` orqali saqlanadi. |
| **FR-12** | **Web dashboard** real vaqtda: faol agentlar, ularning roli/ID/holati, joriy qadam, oqim (event stream). |
| **FR-13** | **Audit timeline:** kim (user/agent), qachon, nima qildi — filtrlanadigan ko'rinish. |
| **FR-14** | **SSH boshqaruv:** admin-paneldan registratsiya qilingan serverga to'liq terminal/komanda yuborish; har komanda `ssh_commands`'ga yoziladi. |
| **FR-15** | **Dinamik secrets:** `ANTHROPIC_API_KEY`, `TG_BOT_TOKEN`, `TG_CHAT_ID`, SSH kalitlar, model nomlari va h.k. admin-panel orqali kiritiladi/o'zgartiriladi; DB'da Fernet bilan shifrlangan. O'zgarish darhol (yoki keyingi siklda) qo'llanadi. |
| **FR-16** | **RBAC:** admin (to'liq), operator (vazifa+chat+ko'rish), viewer (faqat o'qish). Har endpoint rol bilan himoyalangan. |
| **FR-17** | **Auth:** login (parol + JWT/session), parollar `bcrypt`/`argon2` bilan hashlanadi. |

---

## 5. Nofunksional talablar

| Kategoriya | Talab |
|-----------|-------|
| Ishonchlilik | Process uzilsa ma'lumot yo'qolmaydi; idempotent resume. |
| Masshtablilik | `MAX_PARALLEL` sozlanadi; Postgres konkurent yozuvni ko'taradi. |
| Kuzatuvchanlik | Har o'zgarish `events` + `audit_log` + real-vaqt (TG/SSE). |
| Izolyatsiya | Har agent toza, alohida SDK sessiyasi. |
| Xavfsizlik | PreToolUse guard; minimal tool/agent; RBAC; secrets shifrlangan; SSH audit; barcha bypassPermissions ijro konteyner ostida. |
| Kengaytiriluvchanlik | Yangi agent roli (deploy/doc) va yangi UI sahifasi qo'shish oson. |
| Portativlik | `AsyncDB` interfeysi — Postgres ↔ SQLite. |
| Audit butunligi | `audit_log` faqat-qo'shiladigan (append-only); o'chirilmaydi. |

---

## 6. Ma'lumotlar modeli

### 6.1. Mavjud jadvallar (v1 dan)

**tasks**: `id` (uuid4 PK), `parent_id`, `kind` (root|subtask), `title`, `description`, `strategy`, `deps` (JSON), `status` (TaskStatus), `result`, `attempts` (int), `agent_id`, `session_id`, `created_at`, `updated_at`.

**agent_runs**: `id` (masalan `executor-ab12cd`), `task_id` (FK), `role`, `model`, `status`, `started_at`, `finished_at`.

**events**: `id` (PK autoincrement/serial), `task_id`, `agent_id`, `status`, `message`, `created_at`.

### 6.2. Yangi jadvallar (v2)

**users**: `id` (uuid4 PK), `username` (unique), `password_hash`, `role` (admin|operator|viewer), `is_active` (bool), `last_login`, `created_at`.

**secrets**: `key` (PK, masalan `ANTHROPIC_API_KEY`), `value_encrypted` (Fernet), `description`, `is_secret` (bool — UI'da yashirilsinmi), `updated_by` (user_id), `updated_at`.

**servers**: `id` (uuid4 PK), `name`, `host`, `port` (default 22), `username`, `auth_method` (`password`|`key`), `secret_ref` (secrets.key ga ishora — parol/kalit shu yerda shifrlangan), `created_by`, `created_at`.

**ssh_commands** (SSH audit): `id` (PK serial), `server_id` (FK), `user_id` (FK), `command`, `output` (TEXT), `exit_code` (int), `duration_ms` (int), `created_at`.

**chat_messages**: `id` (PK serial), `task_id` (FK, nullable), `chat_session_id` (SDK resume uchun), `channel` (`telegram`|`web`), `direction` (`in`|`out`), `role` (`user`|`agent`), `content` (TEXT), `user_id` (nullable), `created_at`.

**audit_log** (append-only): `id` (PK serial), `actor_type` (`user`|`agent`|`system`), `actor_id`, `action` (masalan `task.created`, `agent.executor.started`, `ssh.command`, `secret.updated`, `user.login`), `target` (task_id/server_id/...), `details` (JSON), `created_at`.

### 6.3. TaskStatus enum (tuzatilgan)

```
PENDING → ANALYZING → PLANNED → EXECUTING → REVIEWING → DONE
                                     ↑___________│ (fail → retry, attempts < MAX_RETRY)
                                                  └→ FAILED (attempts >= MAX_RETRY)
```

> **v1 tuzatishi:** v1'dagi o'lik `TESTING` holati olib tashlandi (Reviewer testni REVIEWING ichida bajaradi). Enum: `PENDING, ANALYZING, PLANNED, EXECUTING, REVIEWING, DONE, FAILED`.

---

## 7. Agent rollari (Claude Agent SDK)

`claude_agent_sdk.AgentDefinition` orqali. **Model ID'lar `.env`/secrets'dan keladi** (default aliaslar quyida; ishonchlilik uchun to'liq ID tavsiya etiladi):

| Rol | Default model | To'liq ID | Tool'lar | Mas'uliyat |
|-----|---------------|-----------|----------|------------|
| **planner** | `opus` | `claude-opus-4-8` | Read, Grep, Glob | Tahlil, strategiya, subtask JSON |
| **executor** | `sonnet` | `claude-sonnet-4-6` | Read, Write, Edit, Bash, Grep, Glob | Bitta subtask'ni to'liq bajarish |
| **reviewer** | `sonnet` | `claude-sonnet-4-6` | Read, Bash, Grep, Glob | Tekshirish + testdan o'tkazish (JSON) |
| **chat** (yangi) | `sonnet` | `claude-sonnet-4-6` | Read, Grep, Glob (+ kontekstga qarab Bash) | Foydalanuvchi bilan muammoni hal qilish suhbati |

**Muhim cheklov:** subagent o'z subagentini spawn qila olmaydi — ierarxiya bir qavatli (orchestrator → agentlar).

**Model tanlovi izohi:** Agent SDK `opus`/`sonnet`/`haiku` aliaslarini qabul qiladi, lekin production'da aniq versiya (`claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5`) barqarorroq. `secrets`/`config` orqali `PLANNER_MODEL` va h.k. beriladi.

---

## 8. Runner (Claude Agent SDK o'rami)

`async def run_agent(role, prompt, *, session_id=None, extra_tools=None) -> tuple[str, str]`:
- `claude_agent_sdk.query(prompt, options)` chaqiradi.
- `ClaudeAgentOptions`: `agents={role: AGENTS[role]}`, `allowed_tools` ga `"Agent"` qo'shiladi, `permission_mode="bypassPermissions"`, `resume=session_id` (berilgan bo'lsa), `model` (config'dan).
- **In-process hooks** (`options.hooks`):
  - `PreToolUse` (Bash matcher) → `guards.is_dangerous()` → xavfli bo'lsa **deny** + TG/audit ogohlantirish.
  - `SubagentStop` / `PostToolUse` → reporter'ga signal (event yozish).
- Stream'dan yakuniy `result` matn va `session_id` ajratiladi (resume uchun saqlanadi).
- JSON kutilganda toza JSON parse (```json fence'lar tozalanadi); xato bo'lsa qayta so'rash.

---

## 9. Orchestrator (yengil dispatcher)

`async def handle_task(task)`:
1. **Idempotent tekshiruv:** agar `task` allaqachon subtask'larga ega bo'lsa (resume holati), rejalashtirishni o'tkazib, davom etilmagan subtask'lardan davom etadi.
2. status → ANALYZING, hisobot ("planner 🟡 tahlil").
3. `run_agent("planner", ...)` → JSON parse → strategy + subtasks → bazaga yoziladi, status → PLANNED.
4. `deps==[]` subtask'lar `asyncio.gather` bilan parallel; bog'liqlari topologik tartibda.
5. Har subtask: EXECUTING → `run_agent("executor")` → result saqla → REVIEWING → `run_agent("reviewer")` → `passed` ? DONE : (attempts+1, retry yoki FAILED). Har bosqichda hisobot.
6. Barcha subtask DONE → root DONE → yakuniy hisobot.

`async def orchestrator_loop()`: cheksiz sikl — `db.next_pending_root()` → `handle_task` yoki `sleep(POLL_INTERVAL)`. Ishga tushganda tugamagan vazifalarni tiklaydi (idempotent).

`MAX_RETRY`, `POLL_INTERVAL`, `MAX_PARALLEL` — config/secrets'dan.

---

## 10. Telegram (to'liq ikki tomonlama + chat)

### 10.1. Outbound (reporter.py)
`TelegramReporter.report(agent_id, role, task_id, status_text)` — `httpx` `sendMessage` POST:
```
🤖 *{role}* `{agent_id}`
📋 task `{task_id[:8]}`
{status_text}
```
Har report `events` + `audit_log`'ga yoziladi.

### 10.2. Inbound + chat (telegram_bot.py)
Long-polling (`getUpdates`) yoki webhook. Buyruqlar:
- `/task <matn>` — yangi root task (PENDING).
- `/status <id>` — holat.
- `/tasks` — oxirgi 10 ta.
- `/chat <task_id>` — agent bilan **suhbat rejimi**: keyingi xabarlar `chat` agentga uzatiladi, kontekst `chat_session_id` (SDK `resume`) orqali saqlanadi; javob qaytariladi. Suhbat `chat_messages`'ga yoziladi.
- `/endchat` — suhbatni tugatish.

---

## 11. Web admin-panel (FastAPI + HTMX + Tailwind)

### 11.1. Sahifalar
| Sahifa | Mazmun | Min. rol |
|--------|--------|----------|
| **Login** | Username + parol → JWT/session cookie | — |
| **Dashboard** | Faol vazifalar/agentlar, real-vaqt oqim (SSE/WebSocket): rol+ID+holat+joriy qadam | viewer |
| **Tasks** | Ro'yxat, filtr, batafsil (subtasklar, strategy, natija); yangi task yaratish | operator (yaratish) / viewer (ko'rish) |
| **Task detail** | Subtask daraxti, har agent_run, event timeline, retry/qayta yuborish | operator |
| **Chat** | Web orqali agent bilan suhbat (task bog'langan), live | operator |
| **Audit** | `audit_log` timeline — actor/action/target/vaqt bo'yicha filtr | viewer |
| **SSH** | Server ro'yxati; tanlangan serverga to'liq terminal (WebSocket); komanda tarixi | admin |
| **Servers** | SSH serverlarni qo'shish/o'chirish (host/port/user/auth) | admin |
| **Secrets** | Dinamik konfiguratsiya: kalit-qiymat, shifrlangan; tahrir/qo'shish | admin |
| **Users** | Foydalanuvchilar + rollar CRUD | admin |

### 11.2. Real vaqt
- **Dashboard/Task detail:** SSE (`text/event-stream`) — orchestrator event yozganda `events`/pub-sub orqali UI yangilanadi.
- **SSH terminal va Chat:** WebSocket (interaktiv).

### 11.3. Auth & RBAC
- `auth.py`: login → parol tekshirish (bcrypt/argon2) → JWT (yoki imzolangan session cookie).
- `rbac.py`: `require_role(min_role)` dependency har endpoint'da. Rollar tartibi: viewer < operator < admin.
- Har muhim amal (`task.created`, `secret.updated`, `ssh.command`, `user.*`) `audit_log`'ga `actor=user` bilan yoziladi.

---

## 12. Server nazorati (SSH)

`ssh.py` — `asyncssh` asosida:
- `connect(server)`: `servers` jadvalidan host/port/user; auth ma'lumoti (parol/kalit) `secrets`'dan deshifrlanadi.
- `run_command(server, command) -> (stdout, stderr, exit_code)`: bir martalik komanda.
- `interactive_shell(server)`: WebSocket bilan ulangan to'liq PTY terminal.
- **Audit (majburiy):** har komanda `ssh_commands`'ga (server, user, command, output, exit_code, duration) va `audit_log`'ga yoziladi.
- **O'rnatish helper'lari:** `install_project`, `update_project`, `restart_services`, `tail_logs` — UI tugmalari uchun tayyor amallar (foydalanuvchi to'liq terminalni ham, tayyor tugmalarni ham ishlatadi).

> **Xavfsizlik ogohlantirishi (README'da majburiy):** to'liq cheklovsiz SSH terminal yuqori xavf. Faqat **admin** roliga ruxsat; barcha komandalar audit'ga yoziladi; production'da panel HTTPS + kuchli auth + IP cheklov ostida ishlatilsin.

---

## 13. Dinamik konfiguratsiya va secrets

- `config.py`: pydantic `Settings` — `.env` faqat **bootstrap** uchun (`DB_DSN`, `SECRET_ENC_KEY` (Fernet master kalit), birinchi admin ma'lumotlari).
- `secrets.py`:
  - `Fernet(SECRET_ENC_KEY)` bilan `value_encrypted` shifrlash/deshifrlash.
  - `get_secret(key, default=None)`, `set_secret(key, value, by_user)`.
  - **Layered resolver:** `get_config(key)` → avval DB `secrets`, topilmasa `.env`, topilmasa default.
- Quyidagilar dinamik (UI'dan): `ANTHROPIC_API_KEY`, `TG_BOT_TOKEN`, `TG_CHAT_ID`, `PLANNER_MODEL`, `EXECUTOR_MODEL`, `REVIEWER_MODEL`, `MAX_RETRY`, `POLL_INTERVAL`, `MAX_PARALLEL`, SSH parol/kalitlar.
- O'zgarish: orchestrator har sikl boshida resolverdan o'qiydi → secret o'zgarsa keyingi siklda qo'llanadi (yoki pub-sub bilan darhol).

> **Bootstrap kaliti:** `SECRET_ENC_KEY` (Fernet master) faqat `.env`/muhit o'zgaruvchisida bo'ladi, hech qachon DB'ga yoki kodga yozilmaydi. Uni yo'qotish = barcha shifrlangan secrets'ni yo'qotish.

---

## 14. Xavfsizlik

1. `guards.is_dangerous(cmd)` — `rm -rf`, `git push`, `:(){`, `mkfs`, `dd if=`, `curl ... | sh`, `shutdown`, `reboot` va h.k. (konfiguratsiyalanadigan blacklist). **Faqat birinchi himoya qatlami** — asosiysi konteyner izolyatsiyasi.
2. Runner `PreToolUse` hook xavfli Bash'ni deny qiladi + audit/TG ogohlantirish.
3. Har agent minimal tool; Reviewer'da Write/Edit yo'q.
4. Executor jarayonlari **alohida cheklangan Linux foydalanuvchi/konteyner** ostida (bypassPermissions sababli majburiy).
5. RBAC: har endpoint rol bilan himoyalangan; SSH/secrets/users faqat admin.
6. Secrets faqat shifrlangan; parol hash (bcrypt/argon2); JWT imzolangan.
7. Audit append-only; SSH har komanda yoziladi.
8. Web panel production'da HTTPS (reverse proxy: Caddy/Nginx) ortida.

---

## 15. Texnologik stek

| Komponent | Texnologiya |
|-----------|-------------|
| Til | Python 3.11+ |
| Agent runtime | `claude-agent-sdk` |
| Baza | PostgreSQL (`asyncpg`); SQLite (`aiosqlite`) test/local |
| Web | FastAPI, Jinja2, HTMX, Tailwind, Uvicorn |
| Real-vaqt | SSE + WebSocket (FastAPI) |
| HTTP/Telegram | `httpx` |
| SSH | `asyncssh` |
| Auth/crypto | `bcrypt`/`argon2-cffi`, `pyjwt`, `cryptography` (Fernet) |
| Konfiguratsiya | `pydantic` / `pydantic-settings` |
| Testlash | `pytest`, `pytest-asyncio` |
| Konteynerlash | Docker, docker-compose |

---

## 16. Loyiha tuzilmasi

```
orchestra/
├─ pyproject.toml
├─ .env.example
├─ README.md
├─ Dockerfile
├─ docker-compose.yml
├─ alembic/ (yoki initdb migratsiya)
├─ src/orchestra/
│  ├─ __init__.py
│  ├─ config.py            # pydantic Settings (bootstrap .env)
│  ├─ models.py            # Task, AgentRun, TaskStatus, User, Server, ...
│  ├─ db.py                # AsyncDB + PostgresDB + SQLiteDB
│  ├─ secrets.py           # Fernet, get/set_secret, layered resolver
│  ├─ agents.py            # AgentDefinition registry (planner/executor/reviewer/chat)
│  ├─ runner.py            # run_agent(): SDK query() o'rami + hooks
│  ├─ guards.py            # xavfli Bash tekshiruvi
│  ├─ reporter.py          # TelegramReporter (outbound)
│  ├─ orchestrator.py      # main loop + handle_task (idempotent)
│  ├─ chat.py              # agent bilan chat sessiyasi (resume)
│  ├─ ssh.py               # asyncssh terminal/exec + audit
│  ├─ rbac.py              # rollar/ruxsatlar
│  ├─ telegram_bot.py      # inbound + chat
│  ├─ web/
│  │  ├─ app.py            # FastAPI ilova
│  │  ├─ auth.py           # login/JWT
│  │  ├─ sse.py            # event stream
│  │  ├─ routes/           # dashboard, tasks, chat, audit, ssh, servers, secrets, users
│  │  ├─ templates/        # Jinja2 + HTMX
│  │  └─ static/           # Tailwind, JS
│  └─ cli.py               # entrypoint: run / bot / web / submit / status / createadmin
├─ .claude/settings.json   # Claude Code PreToolUse hook
├─ scripts/guard_bash.py   # PreToolUse hook skripti
└─ tests/
   ├─ test_db.py
   ├─ test_runner.py
   ├─ test_orchestrator.py
   ├─ test_secrets.py
   ├─ test_rbac.py
   ├─ test_chat.py
   └─ test_web.py
```

---

## 17. CLI

| Buyruq | Vazifa |
|--------|--------|
| `python -m orchestra.cli run` | Orchestrator loop |
| `python -m orchestra.cli bot` | Telegram inbound bot |
| `python -m orchestra.cli web` | Web admin-panel (Uvicorn) |
| `python -m orchestra.cli submit "<matn>"` | Bazaga root task |
| `python -m orchestra.cli status <id>` | Holatni ko'rsatish |
| `python -m orchestra.cli createadmin <user> <parol>` | Birinchi admin foydalanuvchi |
| `python -m orchestra.cli initdb` | Jadvallarni yaratish |

---

## 18. Docker

`docker-compose.yml` servislari:
- **postgres** — volume bilan (ma'lumot saqlanadi).
- **orchestrator** — `CMD python -m orchestra.cli run`.
- **bot** — `CMD python -m orchestra.cli bot`.
- **web** — `CMD python -m orchestra.cli web`, port 8000 (yoki reverse proxy ortida).
- Umumiy `.env` (bootstrap: `DB_DSN`, `SECRET_ENC_KEY`), umumiy tarmoq.

`Dockerfile`: `python:3.11-slim`, paketlar, `claude-agent-sdk` va Claude Code CLI bog'liqliklari.

---

## 19. Testlash strategiyasi

| Test | Maqsad |
|------|--------|
| test_db | Jadvallar, CRUD, next_pending, idempotent resume |
| test_runner | SDK mock → JSON parse; xavfli Bash bloklanadi (hook) |
| test_orchestrator | Planner mock → 2 executor parallel → reviewer pass → DONE; retry; **resume idempotentligi** |
| test_secrets | Fernet shifr/deshifr; layered resolver (DB > .env > default) |
| test_rbac | viewer/operator/admin endpoint ruxsatlari |
| test_chat | chat agent resume kontekst saqlaydi |
| test_web | login, asosiy sahifalar, SSE oqim (TestClient) |

SDK chaqiruvlari mock orqali (haqiqiy API'siz). Maqsad — `pytest` to'liq yashil.

---

## 20. Bosqichli reja

| Bosqich | Mazmun | Natija |
|---------|--------|--------|
| 1 | config, models, db (Postgres+SQLite), secrets + test | Saqlanadigan, shifrlangan holat |
| 2 | agents, runner, guards + test | Agent chaqiruv + himoya |
| 3 | reporter, orchestrator (idempotent), chat + test | Parallel ijro, retry, chat |
| 4 | telegram_bot (inbound+chat) | TG to'liq ikki tomonlama |
| 5 | web: auth, rbac, dashboard, tasks, audit (SSE) | Asosiy admin-panel |
| 6 | web: ssh, servers, secrets, users (WebSocket) | Server nazorati + dinamik config |
| 7 | Docker, hooks, README | Deploy + hujjat |

Har bosqichda `pytest` yashilga keltiriladi.

---

## 21. Qabul mezonlari

1. `submit`/`/task` → `run` → TG va Web'da ketma-ket: planner, har executor (ID), har reviewer (ID), yakuniy xulosa.
2. Subtask'lar haqiqatan parallel (log/dashboard'da vaqtlar ustma-ust).
3. Reviewer fail → `MAX_RETRY` gacha qayta ijro.
4. Orchestrator to'xtatib qayta ishga tushirilsa, tugamagan vazifa **takrorlanmasdan** davom etadi.
5. Xavfli Bash bloklanadi + TG/audit ogohlantirish.
6. **TG `/chat`** orqali agent bilan suhbatlashib muammo hal qilinadi, kontekst saqlanadi.
7. **Web dashboard** real vaqtda agentlarni ko'rsatadi; **audit** kim/qachon/nimani ko'rsatadi.
8. **SSH** orqali admin serverga komanda yuboradi; har komanda audit'da.
9. **Secrets** UI'dan o'zgartiriladi va keyingi siklda qo'llanadi (qayta deploy'siz).
10. **RBAC:** viewer yoza olmaydi; operator secret/SSH/users'ga kira olmaydi; admin to'liq.
11. `pytest` to'liq yashil; README to'liq (o'rnatish, .env, RBAC, xavfsizlik, arxitektura, server o'rnatish).

---

## 22. Risklar va yumshatish

| Risk | Ta'sir | Yumshatish |
|------|--------|-----------|
| Cheklovsiz SSH suiiste'moli | Yuqori | Faqat admin + to'liq audit + HTTPS/IP cheklov + production izolyatsiya |
| bypassPermissions xavfli ijro | Yuqori | PreToolUse guard + konteyner/cheklangan user |
| `SECRET_ENC_KEY` yo'qolishi | Yuqori | Muhit/maxfiy boshqaruvda backup; hech qachon DB/kodda emas |
| Planner noto'g'ri JSON | O'rta | Qattiq prompt + validatsiya + qayta so'rash |
| Cheksiz retry | O'rta | `MAX_RETRY` |
| Konkurent DB yozuv | O'rta | Postgres + tranzaksiyalar |
| Resume'da subtask ikkilanishi | O'rta | `handle_task` idempotent tekshiruvi (FR-9) |

---

## Ilova A. Amalga oshirish prompti
Ushbu TZ asosida loyihani noldan quradigan to'liq prompt `IMPLEMENTATION_PROMPT.md` (v2.0) faylida berilgan.
