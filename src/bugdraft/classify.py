"""Правила: окружение, компонент, серьёзность (предложение), краткая сводка ошибки из лога."""
from __future__ import annotations

import re

from .io_csv import Case

# Признаки проблемы окружения, а не продукта (TO-BE шаг 5).
ENV_PATTERNS = [
    r"connect(?:ion)?\s+(?:timeout|timed out|refused)",
    r"ECONNREFUSED|ETIMEDOUT|EHOSTUNREACH",
    r"name or service not known|could not resolve host|temporary failure in name resolution",
    r"\bsandbox\b.*\b(?:down|unavailable)\b|\bstand(?:-| )?by\b.*\bdown\b",
    r"стенд\S*\s+недоступ",
    r"provider unavailable",
]
_ENV_RE = re.compile("|".join(f"(?:{p})" for p in ENV_PATTERNS), re.IGNORECASE)

_HTTP_ERR_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(\S+)\s*->\s*(5\d\d)\b")
_EXCEPTION_RE = re.compile(r"\b\w*(?:Exception|Error)\b")
_TAG_RE = re.compile(r"\[([a-z][a-z0-9-]*)\]")
_GENERIC_TAGS = {"web", "web-ui", "ui", "gateway", "api"}

SEVERITIES = ["Critical", "Major", "Minor", "Trivial"]
_PRIORITY_TO_SEVERITY = {"High": "Major", "Medium": "Minor", "Low": "Trivial"}


def environment_reason(case: Case, log_text: str) -> str | None:
    """Возвращает найденный признак проблемы окружения или None."""
    m = _ENV_RE.search(log_text) or _ENV_RE.search(case.actual)
    return m.group(0) if m else None


def error_summary(log_text: str) -> str | None:
    """«500 на POST /api/cart/promo» — если в логе есть 5xx-ответ."""
    m = _HTTP_ERR_RE.search(log_text)
    return f"{m.group(3)} на {m.group(1)} {m.group(2)}" if m else None


def guess_component(log_text: str) -> str:
    for tag in _TAG_RE.findall(log_text):
        if tag not in _GENERIC_TAGS:
            return tag[:-len("-service")] if tag.endswith("-service") else tag
    return "unknown"


def suggest_severity(case: Case, log_text: str) -> str:
    """Предложение серьёзности. Утверждает человек (TO-BE шаг 8)."""
    base = _PRIORITY_TO_SEVERITY.get(case.priority, "Minor")
    server_error = bool(_HTTP_ERR_RE.search(log_text) or _EXCEPTION_RE.search(log_text))
    if server_error and SEVERITIES.index(base) > SEVERITIES.index("Major"):
        return "Major"
    return base
