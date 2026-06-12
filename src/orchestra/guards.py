"""Xavfli Bash komandalarni aniqlovchi qora ro'yxat.

DIQQAT: bu FAQAT birinchi himoya qatlami. Blacklist yengib o'tilishi mumkin
(masalan `rm -r -f`, base64, env-var). Asosiy himoya — executor'larni cheklangan
Linux foydalanuvchi yoki konteyner ostida ishga tushirish (README'ga qarang).
"""

from __future__ import annotations

import re

# Standart qora ro'yxat (regex, case-insensitive).
DEFAULT_DANGEROUS: list[str] = [
    # rm bilan ham recursive, ham force flagi (birlashgan -rf/-fr yoki alohida -r -f).
    r"\brm\b(?=(?:[^\n]*\s)?-[a-z]*r)(?=(?:[^\n]*\s)?-[a-z]*f)",
    r"\bgit\s+push\b",
    r":\s*\(\s*\)\s*\{",              # fork bomb :(){ ...
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba)?sh",  # curl ... | sh
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r">\s*/dev/sd[a-z]",
    r"\bchmod\s+-R\s+0*777\s+/",
    r"\bchown\s+-R\b[^\n]*\s+/\s*$",
    r"\b(userdel|deluser)\b",
    r"\biptables\s+-F\b",
]


def is_dangerous(cmd: str, patterns: list[str] | None = None) -> bool:
    """`cmd` qora ro'yxatga to'g'ri kelsa True qaytaradi."""
    if not cmd:
        return False
    pats = patterns if patterns is not None else DEFAULT_DANGEROUS
    text = cmd.strip()
    return any(re.search(p, text, re.IGNORECASE) for p in pats)


def reason(cmd: str, patterns: list[str] | None = None) -> str | None:
    """Mos kelgan birinchi pattern (ogohlantirish matni uchun)."""
    pats = patterns if patterns is not None else DEFAULT_DANGEROUS
    for p in pats:
        if re.search(p, cmd or "", re.IGNORECASE):
            return p
    return None
