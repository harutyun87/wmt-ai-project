"""Маскирование чувствительных данных в логах (TO-BE шаг 4, SPEC AC6).

Применяется до передачи текста в LLM и до записи в любые выходные файлы.
"""
from __future__ import annotations

import re

_RULES: list[tuple[re.Pattern[str], str]] = [
    # Authorization: Bearer <token>
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 <masked>"),
    # key=value / key: value для секретов, в том числе в JSON ("password":"...")
    (re.compile(r'(?i)("?\b(?:token|access_token|refresh_token|password|passwd|pwd|secret|api[_-]?key|session(?:id)?)\b"?\s*[:=]\s*)"?[^\s",;}]+"?'),
     r"\1<masked>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    # Номер карты: 13–19 цифр, допускаются пробелы и дефисы между группами.
    (re.compile(r"(?<![\d.:-])(?:\d[ -]?){12,18}\d(?![\d.:-])"), "<card>"),
    # Российский телефон: +7 / 8 и 10 цифр.
    (re.compile(r"(?<!\d)(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)"), "<phone>"),
]


def mask(text: str) -> str:
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text
