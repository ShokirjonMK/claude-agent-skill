"""Dinamik, shifrlangan konfiguratsiya.

Secrets DB'da Fernet bilan shifrlangan holda saqlanadi va admin-paneldan tahrirlanadi.
`get_config` layered resolver: DB secrets > .env (Settings) > kod default. Shu sababli
API kalit/token/model qayta deploy'siz UI'dan o'zgartiriladi.

`SECRET_ENC_KEY` (Fernet master) faqat muhitda bo'ladi — hech qachon DB/kodda emas.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from .config import Settings
from .db import AsyncDB

# Config kaliti → Settings atributi (resolver fallback uchun).
_ENV_FALLBACK: dict[str, str] = {
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "TG_BOT_TOKEN": "tg_bot_token",
    "TG_CHAT_ID": "tg_chat_id",
    "PLANNER_MODEL": "planner_model",
    "EXECUTOR_MODEL": "executor_model",
    "REVIEWER_MODEL": "reviewer_model",
    "CHAT_MODEL": "chat_model",
    "POLL_INTERVAL": "poll_interval",
    "MAX_RETRY": "max_retry",
    "MAX_PARALLEL": "max_parallel",
}

# Maska bilan ko'rsatiladigan (UI'da qiymati yashiriladigan) kalitlar.
SENSITIVE_KEYS = {"ANTHROPIC_API_KEY", "TG_BOT_TOKEN"}


def generate_key() -> str:
    """Yangi Fernet master kalit (bootstrap uchun)."""
    return Fernet.generate_key().decode()


class SecretStore:
    """DB'dagi shifrlangan secrets ustida CRUD + layered resolver."""

    def __init__(self, db: AsyncDB, settings: Settings):
        self._db = db
        self._settings = settings
        key = settings.secret_enc_key
        if not key:
            # Bootstrap kaliti berilmagan bo'lsa — faqat .env fallback ishlaydi,
            # DB'ga yozish/o'qish o'chiriladi (xavfsiz default).
            self._fernet: Fernet | None = None
        else:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    @property
    def encryption_available(self) -> bool:
        return self._fernet is not None

    # ── Past daraja: shifrlash ────────────────────────────────────────────────
    def _encrypt(self, value: str) -> str:
        if not self._fernet:
            raise RuntimeError("SECRET_ENC_KEY o'rnatilmagan — secrets'ni shifrlab bo'lmaydi.")
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, token: str) -> str | None:
        if not self._fernet or not token:
            return None
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except (InvalidToken, ValueError):
            return None

    # ── CRUD ──────────────────────────────────────────────────────────────────
    async def get_secret(self, key: str) -> str | None:
        """DB'dagi shifrlangan qiymatni deshifrlab qaytaradi (yo'q bo'lsa None)."""
        row = await self._db.get_secret_row(key)
        if not row or not row.get("value_encrypted"):
            return None
        return self._decrypt(row["value_encrypted"])

    async def set_secret(
        self,
        key: str,
        value: str,
        *,
        by_user: str | None = None,
        description: str | None = None,
        is_secret: bool | None = None,
    ) -> None:
        enc = self._encrypt(value)
        secret_flag = is_secret if is_secret is not None else (key in SENSITIVE_KEYS)
        await self._db.set_secret_row(
            key, enc, description=description, is_secret=secret_flag, updated_by=by_user
        )

    async def delete_secret(self, key: str) -> None:
        await self._db.delete_secret(key)

    # ── Layered resolver: DB > .env > default ────────────────────────────────
    async def get_config(self, key: str, default: str | None = None) -> str | None:
        db_val = await self.get_secret(key)
        if db_val not in (None, ""):
            return db_val
        attr = _ENV_FALLBACK.get(key)
        if attr:
            env_val = getattr(self._settings, attr, None)
            if env_val not in (None, ""):
                return str(env_val)
        return default

    async def get_int(self, key: str, default: int) -> int:
        v = await self.get_config(key, str(default))
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return default

    async def get_float(self, key: str, default: float) -> float:
        v = await self.get_config(key, str(default))
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    # ── UI uchun ro'yxat (maskalangan) ────────────────────────────────────────
    async def list_for_ui(self) -> list[dict]:
        rows = await self._db.list_secrets()
        out: list[dict] = []
        for r in rows:
            is_secret = bool(r.get("is_secret"))
            plain = self._decrypt(r.get("value_encrypted") or "")
            if plain is None:
                display = "(deshifrlab bo'lmadi)"
            elif is_secret:
                display = _mask(plain)
            else:
                display = plain
            out.append(
                {
                    "key": r["key"],
                    "value_display": display,
                    "is_secret": is_secret,
                    "description": r.get("description") or "",
                    "updated_by": r.get("updated_by"),
                    "updated_at": r.get("updated_at"),
                }
            )
        return out


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]}"
