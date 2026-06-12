"""Telegram bot boshqaruvi (admin): token/chat kiritish, on/off, holat, test xabar."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from ...models import Role
from ...rbac import require_role
from ...secrets import _mask

router = APIRouter()


async def _get_me(token: str | None) -> dict | None:
    """Telegram getMe — token to'g'riligini tekshiradi va bot ma'lumotini qaytaradi."""
    if not token:
        return None
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://api.telegram.org/bot{token}/getMe")
            d = r.json()
            return d.get("result") if d.get("ok") else {"error": d.get("description")}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def _enabled(val: str | None) -> bool:
    return (val or "1") not in ("0", "false", "False", "off", "no")


async def _context(request: Request, user, *, test_result: str | None = None) -> dict:
    store = request.app.state.store
    token = await store.get_config("TG_BOT_TOKEN")
    chat_id = await store.get_config("TG_CHAT_ID")
    allowed_ids = await store.get_config("TG_ALLOWED_IDS")
    enabled = _enabled(await store.get_config("TG_BOT_ENABLED", "1"))
    me = await _get_me(token)
    return {
        "request": request, "user": user,
        "has_token": bool(token),
        "token_masked": _mask(token) if token else "",
        "chat_id": chat_id or "",
        "allowed_ids": allowed_ids or "",
        "enabled": enabled,
        "me": me,
        "test_result": test_result,
    }


@router.get("/telegram")
async def telegram_page(request: Request, user=Depends(require_role(Role.ADMIN))):
    ctx = await _context(request, user)
    return request.app.state.templates.TemplateResponse(request, "telegram.html", ctx)


@router.post("/telegram")
async def telegram_save(
    request: Request,
    token: str = Form(""),
    chat_id: str = Form(""),
    allowed_ids: str = Form(""),
    enabled: str = Form("off"),
    user=Depends(require_role(Role.ADMIN)),
):
    store = request.app.state.store
    # Token faqat yangi qiymat kiritilganda yangilanadi (bo'sh/maskalangan bo'lsa — saqlanadi).
    if token.strip() and "•" not in token and "…" not in token:
        await store.set_secret("TG_BOT_TOKEN", token.strip(), by_user=user.id, is_secret=True)
    await store.set_secret("TG_CHAT_ID", chat_id.strip(), by_user=user.id, is_secret=False)
    await store.set_secret("TG_ALLOWED_IDS", allowed_ids.strip(), by_user=user.id, is_secret=False)
    await store.set_secret(
        "TG_BOT_ENABLED", "1" if enabled == "on" else "0", by_user=user.id, is_secret=False
    )
    await request.app.state.db.log_audit(
        actor_type="user", actor_id=user.id, action="telegram.config",
        details={"enabled": enabled == "on"},
    )
    return RedirectResponse("/telegram", status_code=303)


@router.post("/telegram/test")
async def telegram_test(request: Request, user=Depends(require_role(Role.ADMIN))):
    store = request.app.state.store
    token = await store.get_config("TG_BOT_TOKEN")
    chat_id = await store.get_config("TG_CHAT_ID")
    me = await _get_me(token)
    if not token:
        result = "🔴 Token kiritilmagan."
    elif not me or me.get("error"):
        err = me.get("error") if me else "javob yoq"
        result = f"🔴 Token noto'g'ri: {err}"
    elif not chat_id:
        result = f"🟠 Token OK (@{me.get('username')}), lekin Chat ID kiritilmagan."
    else:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": "✅ Orchestra: test xabari muvaffaqiyatli."},
                )
                d = r.json()
            if d.get("ok"):
                result = f"🟢 Ulanish OK (@{me.get('username')}). Test xabari yuborildi → chat {chat_id}."
            else:
                result = f"🟠 Token OK, lekin xabar yuborilmadi: {d.get('description')}"
        except Exception as e:  # noqa: BLE001
            result = f"🔴 Xato: {e}"

    ctx = await _context(request, user, test_result=result)
    return request.app.state.templates.TemplateResponse(request, "telegram.html", ctx)
