#!/usr/bin/env python3
"""Claude Code PreToolUse hook — xavfli Bash komandalarni bloklaydi.

Claude Code bu skriptga JSON'ni stdin orqali uzatadi. Bash bo'lsa va komanda
qora ro'yxatga tushsa, sababni stderr'ga yozib `exit 2` (bloklash) qaytaradi.
O'z ichida mustaqil (paket o'rnatilmagan bo'lsa ham ishlaydi)."""

from __future__ import annotations

import json
import re
import sys

DANGEROUS = [
    r"\brm\b(?=(?:[^\n]*\s)?-[a-z]*r)(?=(?:[^\n]*\s)?-[a-z]*f)",
    r"\bgit\s+push\b",
    r":\s*\(\s*\)\s*\{",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba)?sh",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r">\s*/dev/sd[a-z]",
    r"\bchmod\s+-R\s+0*777\s+/",
]


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # parse imkonsiz — bloklamaymiz
    tool = data.get("tool_name") or data.get("toolName")
    if tool != "Bash":
        return 0
    tool_input = data.get("tool_input") or data.get("toolInput") or {}
    cmd = (tool_input.get("command") if isinstance(tool_input, dict) else "") or ""
    for pat in DANGEROUS:
        if re.search(pat, cmd, re.IGNORECASE):
            sys.stderr.write(f"Xavfli Bash komandasi bloklandi (guard): {pat}\n")
            return 2  # 2 = bloklash
    return 0


if __name__ == "__main__":
    sys.exit(main())
