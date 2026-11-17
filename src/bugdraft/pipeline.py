"""Сборка предложений по упавшим кейсам и сводка по рану."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from .checks import missing_data
from .classify import environment_reason
from .drafting import TEMPLATE_GENERATOR, LLMDrafter, template_draft
from .duplicates import THRESHOLD, find_candidates
from .io_csv import Bug, Case
from .masking import mask

FAILED_STATUSES = {"Failed", "Blocked"}
MASKED_CASE_FIELDS = ("title", "steps", "expected", "actual", "environment")
SUGGESTION_LABELS = {
    "new_bug": "Новый баг",
    "duplicate": "Дубль существующего бага",
    "return_to_tester": "Вернуть QA-инженеру",
    "environment": "Проблема окружения",
}


def fingerprint(proposal: dict) -> str:
    """Отпечаток содержания предложения: решение действительно, пока предложение не изменилось."""
    body = json.dumps(proposal, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def read_logs(case: Case, attachments_dir: Path) -> str:
    """Текст всех текстовых вложений кейса (сырой — только для внутреннего использования, наружу — после mask)."""
    parts = []
    for rel in case.attachments:
        p = attachments_dir / rel
        if p.suffix.lower() in {".txt", ".log", ".json"} and p.is_file():
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def propose(case: Case, bugs: list[Bug], attachments_dir: Path, drafter: LLMDrafter | None = None) -> dict:
    proposal = {"case_id": case.case_id, "status": case.status, "suggestion": "", "reasons": [],
                "missing": [], "duplicate_candidates": [], "draft": None,
                "generator": TEMPLATE_GENERATOR, "generator_note": ""}

    missing = missing_data(case, attachments_dir)
    if missing:
        proposal.update(suggestion="return_to_tester", missing=missing,
                        reasons=[f"не хватает данных: {', '.join(missing)}"])
        return proposal

    # Риск R-02: в тексте кейса тоже могут быть ПДн — маскируем все текстовые поля до правил, LLM и отчётов.
    case = replace(case, **{f: mask(getattr(case, f)) for f in MASKED_CASE_FIELDS})
    masked_log = mask(read_logs(case, attachments_dir))

    env = environment_reason(case, masked_log)
    if env:
        proposal.update(suggestion="environment", reasons=[f"признак проблемы окружения: «{env}»"])
        return proposal

    candidates = find_candidates(case, bugs)
    proposal["duplicate_candidates"] = candidates
    if candidates and candidates[0]["score"] >= THRESHOLD:
        top = candidates[0]
        proposal.update(suggestion="duplicate",
                        reasons=[f"похож на {top['bug_id']} (сходство {top['score']:.2f} ≥ {THRESHOLD})"])
    else:
        proposal.update(suggestion="new_bug", reasons=["похожих открытых багов не найдено"])

    # LLM нужна только для нового бага; для комментария к дублю хватает шаблона (экономия вызовов).
    if drafter is not None and proposal["suggestion"] == "new_bug":
        draft, generator, note = drafter.draft(case, masked_log)
    else:
        draft, generator, note = template_draft(case, masked_log), TEMPLATE_GENERATOR, ""
    proposal.update(draft=draft, generator=generator, generator_note=note)
    return proposal


def analyze(cases: list[Case], bugs: list[Bug], attachments_dir: Path, run_id: str,
            drafter: LLMDrafter | None = None) -> dict:
    proposals = [propose(c, bugs, attachments_dir, drafter) for c in cases if c.status in FAILED_STATUSES]
    return {"run_id": run_id,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "total_cases": len(cases),
            "proposals": proposals}


def summary_markdown(result: dict) -> str:
    props = result["proposals"]
    lines = [f"# Сводка по рану {result['run_id']}", "",
             f"Сформировано: {result['generated_at']}. Всего кейсов: {result['total_cases']}, "
             f"упало (Failed/Blocked): {len(props)}.", "",
             "| Предложение | Кол-во |", "|---|---|"]
    for key, label in SUGGESTION_LABELS.items():
        lines.append(f"| {label} | {sum(p['suggestion'] == key for p in props)} |")
    lines += ["", "| Кейс | Статус | Предложение | Основание |", "|---|---|---|---|"]
    for p in props:
        lines.append(f"| {p['case_id']} | {p['status']} | {SUGGESTION_LABELS[p['suggestion']]} | "
                     f"{'; '.join(p['reasons']).replace('|', '/')} |")
    lines += ["", "Предложения не являются решениями: решение по каждому кейсу принимает QA-инженер (`decide`)."]
    return "\n".join(lines) + "\n"
