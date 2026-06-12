# 🎼 Orchestra v2.0

Claude Agent SDK asosidagi **ko'p agentli orkestratsiya platformasi**: bitta tabiiy tildagi
vazifani avtomatik tahlil qilib, subtask'larga bo'lib, ularni mustaqil AI agentlar bilan
**parallel** bajaradi va to'liq testdan o'tkazadi. Ustiga **Telegram bot** (chat bilan),
**web admin-panel** (RBAC), **SSH server nazorati** va **dinamik shifrlangan konfiguratsiya**
qo'shilgan.

> Yagona haqiqat manbai — **ma'lumotlar bazasi**, LLM emas. Orchestrator yengil dispatcher:
> bazadan o'qiydi, agentni izolyatsiyalangan sessiyada chaqiradi, natijani bazaga qaytaradi.
> Process/server uzilsa — bazadan **idempotent** davom etadi.

---

## Arxitektura

```
                          ┌──────────────── PostgreSQL (yagona manba) ────────────────┐
                          │ tasks · agent_runs · events · chat_messages               │
                          │ users · secrets · servers · ssh_commands · audit_log      │
                          └───▲────────────────▲───────────────────────▲──────────────┘
                              │                │                       │
                  ┌───────────┘                │                       └────────────┐
         ┌────────┴────────┐      ┌────────────┴───────────┐         ┌──────────────┴───────────┐
         │  ORCHESTRATOR    │      │     TELEGRAM BOT        │         │     WEB ADMIN-PANEL       │
         │  (cli run)       │      │     (cli bot)           │         │     (cli web)            │
         │  planner         │      │  /task /status /tasks   │         │  Dashboard (SSE)          │
         │  executor (xN ‖) │      │  /chat /endchat         │         │  Tasks · Audit            │
         │  reviewer        │      │  + agent bilan chat     │         │  SSH terminal             │
         │   ↕ Claude Agent │      │  + outbound hisobot     │         │  Secrets · Users (RBAC)   │
         │      SDK         │      └─────────────────────────┘         └──────────────────────────┘
         └──────┬───────────┘
                │ run_agent()  ── PreToolUse hook (guards) → xavfli Bash deny
                ▼                  SubagentStop/PostToolUse → event/report
        ┌──────────────────┐
        │ Claude Agent SDK │  izolyatsiyalangan sessiya (bypassPermissions)
        └──────────────────┘
```

**Ish jarayoni:** vazifa → Planner (strategiya + subtask JSON) → Executor'lar (parallel) →
Reviewer (test) → DONE | fail→retry (MAX_RETRY gacha). Har bosqichda TG + Web (SSE) hisobot.

---

## Texnologiyalar

Python 3.11+ · `claude-agent-sdk` · PostgreSQL (`asyncpg`) / SQLite (`aiosqlite`) ·
FastAPI + Jinja2/HTMX + Tailwind · `httpx` · `asyncssh` · Fernet (`cryptography`) ·
bcrypt + JWT · pydantic · pytest · Docker.

---

## Tez boshlash (Docker — tavsiya)

```bash
git clone <repo> && cd orchestra
cp .env.example .env
# .env ni tahrirlang — kamida quyidagilar:
#   SECRET_ENC_KEY  (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
#   WEB_JWT_SECRET  (python -c "import secrets; print(secrets.token_urlsafe(48))")
#   BOOTSTRAP_ADMIN_PASS=<kuchli parol>

docker compose up -d --build
# → web admin-panel: http://localhost:8000  (login: admin / <BOOTSTRAP_ADMIN_PASS>)
```

So'ng admin-paneldagi **Secrets** sahifasidan `ANTHROPIC_API_KEY`, `TG_BOT_TOKEN`, `TG_CHAT_ID`
va kerakli modellarni kiriting — **qayta deploy shart emas**, keyingi siklda qo'llanadi.

## Lokal (Docker'siz)

```bash
pip install -e ".[dev]"
export DB_DSN="sqlite:///orchestra.db"      # yoki postgresql://...
export SECRET_ENC_KEY="<fernet-key>"
export WEB_JWT_SECRET="<random>"

python -m orchestra.cli initdb
python -m orchestra.cli createadmin admin 'parol123'

python -m orchestra.cli web      # 1-terminal: admin-panel
python -m orchestra.cli run      # 2-terminal: orchestrator
python -m orchestra.cli bot      # 3-terminal: Telegram bot
python -m orchestra.cli submit "PDF hisobot generatorini yoz va testla"
```

---

## CLI

| Buyruq | Vazifa |
|--------|--------|
| `orchestra run` | Orchestrator loop |
| `orchestra bot` | Telegram inbound bot |
| `orchestra web` | Web admin-panel (uvicorn) |
| `orchestra submit "<matn>"` | Root vazifa qo'shadi |
| `orchestra status <id>` | Holatni ko'rsatadi |
| `orchestra createadmin <u> <p>` | Admin yaratadi |
| `orchestra initdb` | Jadvallar + bootstrap admin |

> `python -m orchestra.cli <buyruq>` ham ishlaydi.

---

## Telegram bot

`/task <matn>` · `/status <id>` · `/tasks` · `/chat <task_id>` (agent bilan suhbat — kontekst
saqlanadi) · `/endchat`. Outbound hisobotlar har holat o'zgarishida keladi (rol + agent ID +
task + status).

---

## Web admin-panel (RBAC)

| Sahifa | Min. rol |
|--------|----------|
| Dashboard (real-vaqt SSE), Tasks (ko'rish), Audit | **viewer** |
| Task yaratish/retry, Chat | **operator** |
| Servers, SSH, Secrets, Users | **admin** |

Rollar: `viewer < operator < admin`. Parollar bcrypt bilan hash, sessiya JWT cookie'da.

---

## Server nazorati (SSH)

**Servers** sahifasida server qo'shasiz (host/port/user/auth — parol yoki private key,
shifrlangan holda secrets'da saqlanadi). **SSH** sahifasida tanlangan serverga to'liq
komanda yuborasiz; har komanda `ssh_commands` + `audit_log`'ga yoziladi.

Tipik serverga o'rnatish: server qo'shing → SSH'dan
`git clone … && cd orchestra && cp .env.example .env && docker compose up -d --build`.

> ⚠️ **Xavfsizlik:** to'liq cheklovsiz terminal yuqori xavf. Faqat **admin** roliga ruxsat
> berilgan; barcha komandalar audit'da. Production'da panelni **HTTPS** (Caddy/Nginx reverse
> proxy) va IP cheklov ostida ishlating.

---

## Dinamik secrets

Barcha kalit/token/model admin-paneldagi **Secrets** sahifasidan kiritiladi va DB'da **Fernet**
bilan shifrlanadi. Resolver tartibi: **DB secrets > .env > kod default**. Shu sababli kalitlar
qayta deploy'siz o'zgartiriladi.

`SECRET_ENC_KEY` (Fernet master) faqat `.env`/muhitda bo'ladi — hech qachon DB/kodga yozilmaydi.
**Uni yo'qotsangiz, barcha shifrlangan secrets yo'qoladi.**

---

## Xavfsizlik

- **PreToolUse guard** (`guards.py` + `scripts/guard_bash.py`) xavfli Bash'ni (`rm -rf`,
  `git push`, `dd`, `curl|sh`, `shutdown` …) bloklaydi → audit + TG ogohlantirish.
  Bu **birinchi qatlam**; asosiysi izolyatsiya.
- Har agent minimal tool; Reviewer'da `Write/Edit` yo'q.
- `bypassPermissions` sababli **executor'larni cheklangan Linux foydalanuvchi yoki konteyner
  ostida** ishga tushiring (Docker shuni ta'minlaydi).
- RBAC har endpoint'da; secrets shifrlangan; audit append-only.

---

## Testlar

```bash
pytest -q          # to'liq to'plam (SDK/asyncssh/Postgres'siz, mock orqali)
```

`test_db` · `test_secrets` · `test_guards` · `test_runner` · `test_orchestrator` (parallel,
retry, fail, **resume idempotentligi**) · `test_chat` · `test_bot` · `test_rbac` · `test_web` ·
`test_cli`.

---

## Modellar (Claude Agent SDK)

| Rol | Default model |
|-----|---------------|
| planner | `claude-opus-4-8` (opus) |
| executor / reviewer / chat | `claude-sonnet-4-6` (sonnet) |

SDK `opus`/`sonnet`/`haiku` aliaslarini ham qabul qiladi; production'da to'liq ID barqarorroq.
Modellar Secrets'dan dinamik beriladi (`PLANNER_MODEL` va h.k.).

---

## Eslatmalar / production yo'l xaritasi

- **SSE multi-process:** dashboard oqimi bazadagi `events` jadvalini poll qiladi → orchestrator/bot
  va web alohida konteynerlarda bo'lsa ham ishlaydi. Yuqori yuklamada Postgres `LISTEN/NOTIFY`
  yoki Redis pub/sub'ga o'tish mumkin.
- **Claude Agent SDK** haqiqiy agent ishga tushirish uchun Claude Code CLI (Node) talab qiladi —
  Dockerfile uni o'rnatadi.
- Hujjatlar: `doc/TZ_Orchestra_v2.md` (to'liq TZ), `doc/IMPLEMENTATION_PROMPT.md` (qurish prompti).
