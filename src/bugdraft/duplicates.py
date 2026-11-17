"""Поиск возможных дублей среди открытых багов (TO-BE шаг 6).

Сходство Жаккара по множествам грубых основ слов (первые 5 букв слов длиной от 4).
Офлайн и без модели; на перефразировках слабее эмбеддингов — см. Technology-map.md.
"""
from __future__ import annotations

import re

from .io_csv import Bug, Case

THRESHOLD = 0.35
_WORD_RE = re.compile(r"[a-zа-яё]+", re.IGNORECASE)
_STOP = {"после", "перед", "через", "когда", "который", "которая", "также", "with", "after", "when", "that", "this", "from"}
STEM_LEN = 5


def stems(text: str) -> set[str]:
    words = (w.lower().replace("ё", "е") for w in _WORD_RE.findall(text))
    return {w[:STEM_LEN] for w in words if len(w) >= 4 and w not in _STOP}


def similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_candidates(case: Case, bugs: list[Bug], limit: int = 3) -> list[dict]:
    case_stems = stems(f"{case.title} {case.actual}")
    scored = []
    for bug in bugs:
        if not bug.is_open:
            continue
        score = similarity(case_stems, stems(bug.title))
        if score > 0:
            scored.append({"bug_id": bug.bug_id, "score": round(score, 2), "title": bug.title})
    scored.sort(key=lambda c: (-c["score"], c["bug_id"]))
    return scored[:limit]
