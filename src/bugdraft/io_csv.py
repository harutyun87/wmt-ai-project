"""Чтение и валидация входных CSV (SPEC 6.1, 6.2)."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

RUN_COLUMNS = ["case_id", "title", "priority", "steps", "expected", "actual",
               "status", "build", "environment", "tester", "attachments"]
BUG_COLUMNS = ["bug_id", "title", "status", "severity", "component"]
KNOWN_STATUSES = {"Passed", "Failed", "Blocked", "Skipped"}
OPEN_BUG_STATUSES = {"Open", "In Progress", "Reopened"}
_INCOMPLETE = "__incomplete__"


class InputError(Exception):
    """Ошибка входных данных, после которой работа невозможна (код выхода 2)."""


@dataclass
class Case:
    case_id: str
    title: str
    priority: str
    steps: str
    expected: str
    actual: str
    status: str
    build: str
    environment: str
    tester: str
    attachments: list[str] = field(default_factory=list)


@dataclass
class Bug:
    bug_id: str
    title: str
    status: str
    severity: str
    component: str

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_BUG_STATUSES


def _read_rows(path: Path, required: list[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise InputError(f"Файл не найден: {path}")
    # utf-8-sig: Excel на Windows сохраняет CSV с BOM.
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in required if c not in header]
        if missing:
            raise InputError(
                f"{path.name}: нет обязательных колонок: {', '.join(missing)}. "
                f"Ожидаются: {', '.join(required)}")
        reader.fieldnames = header
        rows = []
        for row in reader:
            # DictReader ставит None в поля, которых не хватило в строке (обрезанная строка экспорта).
            incomplete = [k for k in required if row.get(k) is None]
            clean = {k: (v or "").strip() for k, v in row.items() if k is not None}
            clean[_INCOMPLETE] = ", ".join(incomplete)
            rows.append(clean)
        return rows


def load_run(path: Path) -> tuple[list[Case], list[str]]:
    """Возвращает кейсы и предупреждения (E3: неизвестный статус)."""
    cases, warnings = [], []
    for i, row in enumerate(_read_rows(path, RUN_COLUMNS), start=2):
        if row[_INCOMPLETE]:
            warnings.append(f"строка {i}: {row['case_id'] or '?'} — обрезанная строка, нет полей: "
                            f"{row[_INCOMPLETE]}; пропущена")
            continue
        if row["status"] not in KNOWN_STATUSES:
            warnings.append(f"строка {i}: {row['case_id'] or '?'} — неизвестный статус «{row['status']}», пропущен")
            continue
        # Экспорт из Windows может содержать «\» — приводим к «/», чтобы пути работали и в CI на Linux.
        attachments = [a.strip().replace("\\", "/") for a in row["attachments"].split(";") if a.strip()]
        cases.append(Case(**{c: row[c] for c in RUN_COLUMNS if c != "attachments"}, attachments=attachments))
    return cases, warnings


def load_bugs(path: Path) -> list[Bug]:
    return [Bug(**{c: row[c] for c in BUG_COLUMNS}) for row in _read_rows(path, BUG_COLUMNS)]
