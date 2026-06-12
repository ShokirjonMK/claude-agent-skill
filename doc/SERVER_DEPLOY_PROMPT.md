# Server Deploy & Remediation Prompt — "Orchestra" v2.0

> Bu promptni serverdagi AI agentga (Claude Code) to'liq nusxalab bering.
> U repozitoriyni clone qiladi, ishga tushiradi, real integratsion sinovdan o'tkazadi va
> barcha kamchiliklarni (ayniqsa real SDK/SSH yo'llari va xterm.js terminali) to'liq bartaraf qiladi.
> Talablar majburiy (MUST). Xavfsizlikni ZAIFLASHTIRMA, testlarni doim YASHIL holatda saqla.

---

## ROLE & GOAL

Sen DevOps + backend muhandisisan. Orchestra v2.0 loyihasi yozilgan va 87 ta unit-test yashil,
lekin ikkita tashqi paket (`claude-agent-sdk`, `asyncssh`) ishlab chiqish muhitida o'rnatilmagani
uchun real integratsion yo'llar SINALMAGAN. Sening vazifang — loyihani **serverga o'rnatib, real
xizmatlar bilan to'liq ishlatib ko'rish va barcha kamchiliklarni tuzatish**, so'ng qabul
mezonlari ro'yxati bilan hisobot berish.

**Ma'lum kamchiliklar (MUST tuzat):**
1. `runner.py` — `claude-agent-sdk` real API'siga (query/ClaudeAgentOptions/AgentDefinition/hooks/
   resume/message-parsing) qarshi tekshirilmagan; mosligini tasdiqla va kerak bo'lsa tuzat.
2. `ssh.py` — `asyncssh` real ulanish/terminal yo'li ishlatib ko'rilmagan; tasdiqla va tuzat.
3. SSH brauzer-terminali — WebSocket backend tayyor, lekin `ssh.html` da **xterm.js terminal
   vidjeti ulanmagan**; to'liq ulab, ishlatib ko'r.

---

## ОLDINDAN: muhit

- Linux server (Ubuntu 22.04+ tavsiya), root yoki sudo.
- Quyidagilar bo'lishi kerak: `git`, `python3.11+`, `pip`, `docker` + `docker compose` (ixtiyoriy,
  Postgres uchun qulay), `node 20+` + `npm` (claude-agent-sdk uchun Claude Code CLI talab qiladi).
- Real `ANTHROPIC_API_KEY` (integratsion sinov uchun). Ixtiyoriy: `TG_BOT_TOKEN` + `TG_CHAT_ID`,
  sinov uchun SSH serveri (yoki localhost'ga SSH).

---

## STEP 0 — Klonlash va dastlabki ko'rik

```bash
git clone <REPO_URL> orchestra && cd orchestra
git status && git log --oneline -5
ls -R src tests doc | head -60
```

Avval `doc/TZ_Orchestra_v2.md` va `doc/IMPLEMENTATION_PROMPT.md` ni o'qib, arxitekturani tushun.
`README.md` ni ham o'qi. Hech narsani buzmasdan ishla; har tuzatishdan keyin testlarni qayta yugurt.

---

## STEP 1 — Python muhiti va bog'liqliklar

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
# Ishlab chiqishda yo'q bo'lgan real paketlar:
pip install claude-agent-sdk asyncssh
# Claude Agent SDK real agent uchun Claude Code CLI (Node) talab qiladi:
npm install -g @anthropic-ai/claude-code
python -c "import claude_agent_sdk, asyncssh; print('SDK+SSH OK')"
```

Agar `claude-agent-sdk` o'rnatilmasa yoki nomi farq qilsa — PyPI'dagi to'g'ri paket nomini aniqla
(`pip index versions claude-agent-sdk` yoki Anthropic hujjatlari) va `pyproject.toml` dagi
bog'liqlikni shunga moslab tuzat.

---

## STEP 2 — Secrets va .env

```bash
cp .env.example .env
python - <<'PY'
from cryptography.fernet import Fernet
import secrets, pathlib, re
env = pathlib.Path(".env").read_text()
env = re.sub(r"^SECRET_ENC_KEY=.*$", f"SECRET_ENC_KEY={Fernet.generate_key().decode()}", env, flags=re.M)
env = re.sub(r"^WEB_JWT_SECRET=.*$", f"WEB_JWT_SECRET={secrets.token_urlsafe(48)}", env, flags=re.M)
env = re.sub(r"^BOOTSTRAP_ADMIN_PASS=.*$", "BOOTSTRAP_ADMIN_PASS=ChangeMe_StrongPass!23", env, flags=re.M)
pathlib.Path(".env").write_text(env)
print("Fernet + JWT + admin parol yozildi")
PY
```

`ANTHROPIC_API_KEY` ni HOZIRCHA `.env` ga qo'yma — keyin admin-paneldagi Secrets sahifasidan
kiritamiz (yoki integratsion sinov uchun vaqtincha `export ANTHROPIC_API_KEY=...` qil).

`.env` da `DB_DSN` ni tanlang:
- Postgres (tavsiya): `DB_DSN=postgresql://orchestra:orchestra@localhost:5432/orchestra`
- yoki tez sinov uchun: `DB_DSN=sqlite:///orchestra.db`

---

## STEP 3 — Ma'lumotlar bazasi

**Variant A — Docker bilan to'liq stack:**
```bash
docker compose up -d --build
docker compose ps
docker compose logs initdb        # jadvallar yaratilganini tekshir
docker compose logs orchestrator bot web | tail -40
```

**Variant B — qo'lda (lokal Postgres yoki SQLite):**
```bash
# Postgres bo'lsa avval bazani yarat (yoki docker compose up -d postgres)
python -m orchestra.cli initdb
python -m orchestra.cli createadmin admin 'ChangeMe_StrongPass!23'
```

---

## STEP 4 — Unit testlar (regress himoyasi)

```bash
pytest -q
```
**MUST: 87/87 yashil.** Endi har tuzatishdan keyin ham shu yashil holatni saqlaysan.

---

## STEP 5 — KAMCHILIK #1: Claude Agent SDK real API moslik

`runner.py` SDK hujjatidagi shaklga yozilgan. Real o'rnatilgan versiyaga MOS ekanini tasdiqla:

```bash
python - <<'PY'
import inspect, claude_agent_sdk as c
print("exports:", [n for n in dir(c) if not n.startswith("_")])
from claude_agent_sdk import ClaudeAgentOptions, AgentDefinition, query
print("Options fields:", getattr(ClaudeAgentOptions, "__annotations__", {}))
print("AgentDefinition sig:", inspect.signature(AgentDefinition) if inspect.isclass(AgentDefinition) else AgentDefinition)
print("query:", inspect.signature(query) if callable(query) else type(query))
PY
```

Tekshir va kerak bo'lsa `src/orchestra/runner.py` va `src/orchestra/agents.py` ni tuzat:
- `ClaudeAgentOptions` argument nomlari (`agents`, `allowed_tools`, `permission_mode`, `model`,
  `resume`, `hooks`) real maydonlarga mos kelishini.
- `query(prompt=..., options=...)` chaqiruv shakli to'g'riligini (yoki `query(prompt, options)`).
- **Hook qaytarish shakli** — `PreToolUse` deny uchun real SDK kutadigan format (`{"decision":"block",
  "reason":...}` yoki `{"hookSpecificOutput": {...}}` — versiyaga qarab). `runner.make_pretooluse_guard`
  ni real formatga moslab tuzat; hook signaturasini ham (`async def hook(input_data, tool_use_id, context)`).
- **Message parsing** — stream'dagi yakuniy natija va `session_id` qaysi message turi/atributida
  kelishini aniqla (masalan `ResultMessage.result`, `.session_id`). `runner.collect_stream` dagi
  `_message_text`/`_message_session_id` ni real shaklga moslab kengaytir.

So'ng **real, arzon jonli sinov** (chinakam API kalit bilan, trivial vazifa):
```bash
export ANTHROPIC_API_KEY=sk-ant-...
python - <<'PY'
import asyncio
from orchestra.runner import run_agent, extract_json
async def main():
    text, sid = await run_agent("planner",
        "Bitta oddiy vazifa: 'README.md fayliga bitta qator qo'shish'. Subtask'larga bo'l.",
        model="claude-opus-4-8")
    print("session:", sid)
    print("plan:", extract_json(text))
asyncio.run(main())
PY
```
Planner real JSON qaytarishi va `session_id` kelishi kerak. Xato bo'lsa — runner'ni tuzat, qayta
sina. Mock-testlar (`tests/test_runner.py`) baribir yashil qolishi shart.

---

## STEP 6 — KAMCHILIK #2: asyncssh real ulanish

Sinov uchun localhost'ga SSH yoqing (yoki haqiqiy test serveri):
```bash
# localhost SSH sinovi uchun (faqat sinov muhitida):
sudo apt-get install -y openssh-server && sudo systemctl enable --now ssh
```

Web-panel (admin) → **Servers** → server qo'sh (host=`127.0.0.1`, user=joriy, auth=parol/kalit).
So'ng **SSH** sahifasidan `uptime` yoki `ls -la` yuborib natija + audit yozilganini tekshir:
```bash
# yoki to'g'ridan-to'g'ri:
python - <<'PY'
import asyncio
from orchestra.config import get_settings
from orchestra.db import make_db
from orchestra.secrets import SecretStore
from orchestra.ssh import SSHManager
from orchestra.models import Server
async def main():
    s = get_settings(); db = make_db(s.db_dsn); await db.connect(); await db.initdb()
    store = SecretStore(db, s)
    srv = Server(name="local", host="127.0.0.1", port=22, username="<USER>", auth_method="password", secret_ref="SSH_LOCAL")
    await store.set_secret("SSH_LOCAL", "<PAROL>", by_user=None)
    await db.save_server(srv)
    res = await SSHManager(db, store).run_command(srv, "uptime")
    print(res)
    print("audit:", await db.list_ssh_commands(srv.id))
    await db.close()
asyncio.run(main())
PY
```
`asyncssh.connect` / `conn.run` / `create_process` API'lari real versiyaga mos kelishini tekshir;
farq bo'lsa `src/orchestra/ssh.py` ni tuzat (masalan `known_hosts`, `import_private_key`, PTY
yaratish). Komanda chiqishi va `exit_code` to'g'ri, audit'ga yozilgan bo'lishi shart.

---

## STEP 7 — KAMCHILIK #3: xterm.js brauzer-terminali

`/ssh/{server_id}/terminal` WebSocket endpoint backend'da tayyor, lekin frontend ulanmagan.
Quyidagilarni qil:
- `src/orchestra/web/templates/ssh.html` ga **xterm.js** (CDN) qo'sh: server tanlanganda
  "Terminal ochish" tugmasi → `new WebSocket('ws[s]://host/ssh/<id>/terminal')` ochadi,
  `term.onData → ws.send`, `ws.onmessage → term.write`. `xterm` + `xterm-addon-fit` CDN'dan.
- WebSocket auth: endpoint cookie orqali `get_current_user` bilan admin'ni tekshiradi —
  brauzerda cookie avtomatik yuboriladi, qo'shimcha ish shart emas; lekin `wss://` (HTTPS) ostida
  ishlashini hisobga ol.
- `ssh.py` dagi `interactive_shell` PTY oqimini brauzer terminali bilan ikki tomonlama ulanishini
  jonli sinab ko'r (yozish/ko'rish, `top`, `vim` kabi interaktiv dasturlar ishlasin).
- Kerak bo'lsa terminal o'lchamini (`resize`) uzatish uchun oddiy `{"type":"resize",cols,rows}`
  xabarini qo'shib, `proc.change_terminal_size` chaqir.

Tekshir: admin sifatida `/ssh?server=<id>` → "Terminal ochish" → real interaktiv terminal.

---

## STEP 8 — TO'LIQ END-TO-END integratsion sinov

Real `ANTHROPIC_API_KEY` ni admin-panel **Secrets** sahifasidan kirit (yoki .env). So'ng:

1. **Vazifa → DONE:**
   ```bash
   python -m orchestra.cli submit "Kichik bash skript yoz: hozirgi sanani chiqaradi, va uni testla"
   python -m orchestra.cli run    # yoki docker compose orqali allaqachon ishlayapti
   ```
   - Kuzat: planner → executor(lar) PARALLEL → reviewer → DONE. Web **Dashboard** real-vaqt (SSE)
     yangilanishini ko'rsatsin; **Audit** kim/qachon/nimani ko'rsatsin.
2. **Telegram:** `/task ...`, `/status <id>`, `/tasks`, `/chat <id>` (agent bilan suhbat —
   kontekst saqlanishi), `/endchat` — hammasi ishlasin; outbound hisobotlar kelsin.
3. **Retry:** reviewer fail qaytaradigan vaziyat yarat (yoki bilib turib buzuq subtask) →
   `MAX_RETRY` gacha qayta ijro etilishini tasdiqla.
4. **Xavfli Bash:** executor `rm -rf /` urinsa — bloklanishi va TG/audit'ga ogohlantirish borishini
   tasdiqla (kerak bo'lsa sun'iy sinov bilan).
5. **Resume idempotentligi:** vazifa o'rtasida orchestrator'ni TO'XTAT (Ctrl+C / `docker compose
   stop orchestrator`), qayta ishga tushir — tugamagan vazifa **takrorlanmasdan** davom etsin
   (subtasklar ikkilanmasin, planner qayta chaqirilmasin).
6. **RBAC:** viewer yoza olmasligi, operator secret/SSH/users'ga kira olmasligi, admin to'liq
   ekanini tekshir.

---

## STEP 9 — Xavfsizlik mustahkamlash (MUST, zaiflashtirma)

- Executor'lar `bypassPermissions` bilan ishlaydi → ular **alohida cheklangan Linux user yoki
  konteyner** ostida bo'lsin (Docker shuni ta'minlaydi; qo'lda ishlatilsa alohida user yarat).
- Web-panelni production'da **HTTPS** ortida ishlat (Caddy/Nginx reverse proxy + Let's Encrypt).
  SSH WebSocket terminali `wss://` talab qiladi.
- `asyncssh` da `known_hosts=None` faqat sinov uchun — production'da host-key tekshiruvini yoq.
- `SECRET_ENC_KEY` va `.env` faqat serverda, git'ga TUSHMASIN (`.gitignore` da bor — tekshir).
- Secrets/parollar log'larga chiqmasligini tekshir; bootstrap admin parolini birinchi kirishdan
  keyin almashtir.
- `guards.py` qora ro'yxati yetarliligini ko'rib chiq; bu faqat birinchi qatlam ekanini unutma.

---

## STEP 10 — Hisobot va yakun

1. Quyidagi **qabul mezonlari** ro'yxatini ✅/❌ bilan to'ldir va har ❌ uchun tuzatishni bajar:
   - [ ] `pytest` 87/87 yashil (tuzatishlardan keyin ham).
   - [ ] Real vazifa planner→executor(parallel)→reviewer→DONE bo'ldi (TG + Web'da ko'rindi).
   - [ ] Subtasklar haqiqatan parallel (vaqtlar ustma-ust).
   - [ ] Reviewer fail → MAX_RETRY gacha retry.
   - [ ] Orchestrator restart → tugamagan vazifa takrorlanmasdan davom etdi.
   - [ ] Xavfli Bash bloklandi + ogohlantirish.
   - [ ] TG `/chat` kontekst saqlab ishladi.
   - [ ] Web Dashboard real-vaqt; Audit kim/qachon/nima.
   - [ ] SSH komanda yuborildi + audit; **xterm.js terminal interaktiv ishladi**.
   - [ ] Secrets UI'dan o'zgartirildi → keyingi siklda qo'llandi.
   - [ ] RBAC to'g'ri (viewer/operator/admin chegaralari).
2. Tuzatilgan har bir kamchilik uchun: fayl + nima o'zgardi + nega.
3. Yakunda: `git add -A && git commit -m "server deploy: real SDK/SSH integratsiyasi + xterm.js
   terminali + tuzatishlar"` (yangi branch'da, agar main himoyalangan bo'lsa).

**MUHIM qoidalar:**
- Hech qachon xavfsizlikni zaiflashtirma (RBAC, guard, shifrlash, izolyatsiya).
- Mock unit-testlarni o'chirma; real integratsiya uchun ALOHIDA sinov yoz (kalit talab qiladiganlarini
  `@pytest.mark.skipif(no key)` bilan belgila).
- Har bir o'zgarishdan keyin `pytest -q` yashil bo'lsin.
- Tushunarsiz yoki xavfli qaror (masalan production host-key, parol) bo'lsa — to'xtab so'ra.

Boshla.
