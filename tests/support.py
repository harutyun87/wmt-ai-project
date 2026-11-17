"""Общие пути и фабрики для тестов. Импортируйте первым в каждом тестовом модуле."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SYN = ROOT / "data" / "synthetic"
RUN_CSV = SYN / "test-run-RUN-2026-11-16-01.csv"
BUGS_CSV = SYN / "existing-bugs.csv"

from bugdraft.io_csv import Case  # noqa: E402


def make_case(**kw) -> Case:
    base = dict(case_id="TC-9000", title="Тестовый кейс", priority="Medium", steps="1. Шаг один; 2. Шаг два",
                expected="Ожидание", actual="Факт", status="Failed", build="1.0.0", environment="Chrome / stage",
                tester="QA-1", attachments=[])
    base.update(kw)
    return Case(**base)
