"""Проверка полноты кейса до заведения бага (TO-BE шаг 3, SPEC E4)."""
from __future__ import annotations

from pathlib import Path

from .io_csv import Case

REQUIRED_FIELDS = ["title", "steps", "expected", "actual", "build", "environment"]


def missing_data(case: Case, attachments_dir: Path) -> list[str]:
    """Список того, чего не хватает для качественного баг-репорта. Пустой список — кейс полный."""
    missing = [f for f in REQUIRED_FIELDS if not getattr(case, f).strip()]
    if not case.attachments:
        missing.append("attachments")
    else:
        root = attachments_dir.resolve()
        for rel in case.attachments:
            p = (attachments_dir / rel).resolve()
            # Вложение должно лежать внутри папки вложений и существовать.
            if root not in p.parents or not p.is_file():
                missing.append(f"attachment_file:{rel}")
    return missing
