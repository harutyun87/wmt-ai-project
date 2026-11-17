"""Публикация подтверждённых решений (TO-BE шаг 9, SPEC 6.5, E9, E10).

MVP: только файлы outbox. GitLabPublisher — заготовка с повторами и тайм-аутом, проверена на заглушке,
с реальным GitLab не запускалась.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from .pipeline import fingerprint

PUBLISHABLE = {("new_bug", "approve"): "issue", ("duplicate", "approve"): "note", ("duplicate", "duplicate"): "note",
               ("new_bug", "duplicate"): "note"}


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", part)


def issue_description(draft: dict) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(draft["steps"], 1))
    log = "\n".join(draft["log_excerpt"]) or "(нет)"
    return (f"**Сборка / окружение:** {draft['build']}, {draft['environment']}\n\n"
            f"**Шаги:**\n{steps}\n\n**Ожидаемо:** {draft['expected']}\n\n**Фактически:** {draft['actual']}\n\n"
            f"**Лог (маскирован):**\n```\n{log}\n```\n\n**Связанные кейсы:** {', '.join(draft['links'])}\n")


def build_items(proposals: dict, decisions: dict) -> tuple[list[dict], list[str]]:
    """Формирует элементы публикации. Возвращает (элементы, пояснения по пропущенным кейсам)."""
    items, notes = [], []
    for p in proposals["proposals"]:
        d = decisions.get(p["case_id"])
        if not d:
            notes.append(f"{p['case_id']}: нет решения — не публикуется")
            continue
        if d.get("for_fingerprint") != fingerprint(p):
            notes.append(f"{p['case_id']}: предложение изменилось после решения "
                         f"(было «{d.get('for_suggestion')}», сейчас «{p['suggestion']}») — повторите decide")
            continue
        kind = PUBLISHABLE.get((p["suggestion"], d["action"]))
        if kind is None or p["draft"] is None:
            notes.append(f"{p['case_id']}: решение «{d['action']}» по предложению «{p['suggestion']}» — публикации нет")
            continue
        draft = p["draft"]
        key = f"{kind}__{_safe(p['case_id'])}__{_safe(draft['build'])}"
        if kind == "issue":
            severity = d.get("severity") or draft["severity"]
            items.append({"key": key, "kind": "issue", "case_id": p["case_id"], "build": draft["build"],
                          "title": draft["title"], "description": issue_description(draft),
                          "labels": ["bug", f"severity::{severity}", f"component::{draft['component']}"]})
        else:
            bug_id = d.get("duplicate_of") or (p["duplicate_candidates"][0]["bug_id"]
                                               if p["duplicate_candidates"] else None)
            if not bug_id:
                notes.append(f"{p['case_id']}: дубль без номера бага — публикации нет")
                continue
            body = (f"Воспроизведено снова: {p['case_id']}, сборка {draft['build']}, {draft['environment']}.\n\n"
                    f"Фактически: {draft['actual']}\n")
            items.append({"key": key, "kind": "note", "case_id": p["case_id"], "build": draft["build"],
                          "bug_id": bug_id, "body": body})
    return items, notes


def publish_outbox(items: list[dict], outbox: Path) -> tuple[list[str], list[str]]:
    """Пишет элементы в outbox. Существующие файлы не трогает (идемпотентность, SPEC S6)."""
    outbox.mkdir(parents=True, exist_ok=True)
    written, skipped = [], []
    for item in items:
        path = outbox / f"{item['key']}.json"
        if path.exists():
            skipped.append(path.name)
            continue
        body = {k: v for k, v in item.items() if k != "key"}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)  # атомарная запись: обрыв не оставит полупустой файл с «правильным» именем
        written.append(path.name)
    return written, skipped


# ---------------------------------------------------------------- GitLab (не MVP)

class PublishError(Exception):
    pass


Sender = Callable[[str, dict, dict, float], tuple[int, dict]]


def http_sender(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {}
    try:
        return status, json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        # Прокси или старый сервер вернул не-JSON при успехе: задача создана, повторять нельзя.
        return status, {"raw": raw[:200].decode("utf-8", errors="replace")}


class GitLabPublisher:
    """POST /projects/:id/issues и /projects/:id/issues/:iid/notes с повторами для 5xx и тайм-аутов."""

    RETRY_DELAYS = (1, 2)  # 3 попытки, паузы между ними (SPEC E9)

    def __init__(self, base_url: str, project_id: str, token: str, timeout: float = 10.0,
                 sender: Sender = http_sender, sleep: Callable[[float], None] = time.sleep):
        self.api = f"{base_url.rstrip('/')}/api/v4/projects/{urllib.parse.quote(project_id, safe='')}"
        self.headers = {"PRIVATE-TOKEN": token}
        self.timeout, self.sender, self.sleep = timeout, sender, sleep

    def _post(self, url: str, payload: dict) -> dict:
        attempts = len(self.RETRY_DELAYS) + 1
        for attempt in range(attempts):
            try:
                status, body = self.sender(url, self.headers, payload, self.timeout)
            except (TimeoutError, OSError) as e:
                status, body, err = 0, {}, type(e).__name__
            else:
                err = f"HTTP {status}"
                if 200 <= status < 300:
                    return body
                if 400 <= status < 500:
                    raise PublishError(f"{err}: запрос отклонён, повтор не поможет")
            if attempt < attempts - 1:
                self.sleep(self.RETRY_DELAYS[attempt])
        raise PublishError(f"{err}: не удалось после {attempts} попыток")

    def publish(self, item: dict) -> dict:
        if item["kind"] == "issue":
            return self._post(f"{self.api}/issues", {"title": item["title"], "description": item["description"],
                                                     "labels": ",".join(item["labels"])})
        iid = re.sub(r"\D", "", item["bug_id"])
        return self._post(f"{self.api}/issues/{iid}/notes", {"body": item["body"]})
