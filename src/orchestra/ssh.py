"""SSH server nazorati (asyncssh) + to'liq audit.

Har komanda `ssh_commands` va `audit_log`'ga yoziladi. Auth ma'lumoti (parol yoki
maxfiy kalit) `servers.secret_ref` → `secrets` orqali shifrlangan holda olinadi.

DIQQAT: to'liq cheklovsiz terminal yuqori xavf — faqat admin roliga ruxsat berilgan
(web/routes/ssh.py'da `require_role(ADMIN)`). asyncssh lazy import qilinadi.
"""

from __future__ import annotations

import time
from typing import Any

from .db import AsyncDB
from .models import Server
from .secrets import SecretStore

# Oldindan belgilangan amallar (UI tugmalari uchun).
INSTALL_CMDS = [
    "git clone https://github.com/<owner>/orchestra.git || (cd orchestra && git pull)",
    "cd orchestra && cp -n .env.example .env",
    "cd orchestra && docker compose up -d --build",
]


class SSHManager:
    def __init__(self, db: AsyncDB, store: SecretStore):
        self._db = db
        self._store = store

    async def _connect(self, server: Server):
        import asyncssh  # lazy

        secret = (
            await self._store.get_secret(server.secret_ref) if server.secret_ref else None
        )
        kwargs: dict[str, Any] = {
            "host": server.host,
            "port": server.port,
            "username": server.username,
            "known_hosts": None,  # production'da host-key tekshiruvini yoqing
        }
        if server.auth_method == "password":
            kwargs["password"] = secret
        else:
            if secret:
                kwargs["client_keys"] = [asyncssh.import_private_key(secret)]
        return await asyncssh.connect(**kwargs)

    async def run_command(
        self, server: Server, command: str, *, user_id: str | None = None
    ) -> dict:
        """Bir martalik komanda. Natija audit'ga yoziladi."""
        t0 = time.monotonic()
        output, exit_code = "", None
        try:
            async with await self._connect(server) as conn:
                res = await conn.run(command, check=False)
                output = (res.stdout or "") + (res.stderr or "")
                exit_code = res.exit_status
        except Exception as exc:  # noqa: BLE001
            output = f"[SSH xato] {exc}"
            exit_code = -1
        duration_ms = int((time.monotonic() - t0) * 1000)

        await self._db.log_ssh_command(
            server.id, user_id, command, output, exit_code, duration_ms
        )
        await self._db.log_audit(
            actor_type="user", actor_id=user_id, action="ssh.command",
            target=server.id, details={"command": command, "exit_code": exit_code},
        )
        return {"output": output, "exit_code": exit_code, "duration_ms": duration_ms}

    async def interactive_shell(self, server: Server, websocket, *, user_id: str | None = None):
        """WebSocket ↔ PTY ko'prik (to'liq terminal). Best-effort; asyncssh kerak."""
        import asyncio

        import asyncssh  # noqa: F401  (lazy import xatosini erta ko'rsatish uchun)

        await self._db.log_audit(
            actor_type="user", actor_id=user_id, action="ssh.terminal.open", target=server.id
        )
        import json

        conn = await self._connect(server)
        proc = await conn.create_process(
            term_type="xterm", term_size=(80, 24), stdin=asyncssh.PIPE
        )

        async def pump_out():
            try:
                while True:
                    data = await proc.stdout.read(1024)
                    if not data:
                        break
                    await websocket.send_text(data)
            except Exception:
                pass

        out_task = asyncio.create_task(pump_out())
        try:
            while True:
                raw = await websocket.receive_text()
                # Frontend har xabarni JSON sifatida yuboradi: {"type":"data"|"resize", ...}
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError):
                    proc.stdin.write(raw)
                    continue
                if msg.get("type") == "resize":
                    try:
                        proc.change_terminal_size(
                            int(msg.get("cols", 80)), int(msg.get("rows", 24))
                        )
                    except Exception:
                        pass
                else:
                    proc.stdin.write(msg.get("data", ""))
        except Exception:
            pass
        finally:
            out_task.cancel()
            proc.close()
            conn.close()
            await self._db.log_audit(
                actor_type="user", actor_id=user_id, action="ssh.terminal.close",
                target=server.id,
            )
