"""Черновик баг-репорта: шаблон (по умолчанию) и LLM с проверкой схемы и откатом (TO-BE шаг 7, SPEC 6.6)."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Callable

from .classify import SEVERITIES, error_summary, guess_component, suggest_severity
from .io_csv import Case

TEMPLATE_GENERATOR = "template-v1"
MAX_TITLE = 120
LOG_EXCERPT_LINES = 5
_STEP_SPLIT_RE = re.compile(r";\s*(?=\d+[.)]\s)")
_STEP_NUM_RE = re.compile(r"^\s*\d+[.)]\s*")


def split_steps(steps: str) -> list[str]:
    parts = _STEP_SPLIT_RE.split(steps) if steps else []
    return [_STEP_NUM_RE.sub("", p).strip() for p in parts if p.strip()]


def log_excerpt(masked_log: str) -> list[str]:
    lines = [ln.strip() for ln in masked_log.splitlines() if re.search(r"\b(ERROR|WARN|FATAL)\b", ln)]
    return lines[:LOG_EXCERPT_LINES]


def template_draft(case: Case, masked_log: str) -> dict:
    symptom = error_summary(masked_log) or case.actual
    title = f"{case.title} — {symptom}"
    if len(title) > MAX_TITLE:
        title = title[:MAX_TITLE - 1].rstrip() + "…"
    return {
        "title": title,
        "severity": suggest_severity(case, masked_log),
        "component": guess_component(masked_log),
        "build": case.build,
        "environment": case.environment,
        "steps": split_steps(case.steps),
        "expected": case.expected,
        "actual": case.actual,
        "log_excerpt": log_excerpt(masked_log),
        "links": [case.case_id],
    }


# ---------------------------------------------------------------- LLM

Transport = Callable[[str, dict, dict, float], dict]
"""(url, headers, payload, timeout) -> разобранный JSON ответа. Подменяется в тестах."""


def http_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — URL задаёт администратор
        return json.loads(resp.read().decode("utf-8"))


_PROMPT = (
    "Ты помогаешь QA-инженеру оформить баг-репорт. Используй только факты из данных ниже, "
    "ничего не придумывай. Ответь строго JSON-объектом без пояснений: "
    '{"title": "<краткий заголовок до 120 символов: что сломано и где>", '
    '"steps": ["<шаг 1>", "..."], "severity": "Critical|Major|Minor|Trivial"}'
)


def _validate_llm_fields(obj: object) -> dict:
    if not isinstance(obj, dict):
        raise ValueError("ответ не JSON-объект")
    title, steps, severity = obj.get("title"), obj.get("steps"), obj.get("severity")
    if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE:
        raise ValueError("поле title отсутствует или длиннее 120 символов")
    if not isinstance(steps, list) or not steps or not all(isinstance(s, str) and s.strip() for s in steps):
        raise ValueError("поле steps не непустой список строк")
    if severity not in SEVERITIES:
        raise ValueError(f"severity «{severity}» вне шкалы")
    return {"title": title.strip(), "steps": [s.strip() for s in steps], "severity": severity}


class LLMDrafter:
    """OpenAI-совместимый API: Ollama (локально) или внешний сервис. Получает только маскированный текст."""

    def __init__(self, base_url: str, model: str, api_key: str | None = None,
                 timeout: float = 20.0, transport: Transport = http_transport):
        self.url = base_url.rstrip("/") + "/v1/chat/completions"
        self.model, self.api_key, self.timeout, self.transport = model, api_key, timeout, transport

    def draft(self, case: Case, masked_log: str) -> tuple[dict, str, str]:
        """Возвращает (черновик, генератор, примечание). При любой ошибке — шаблон."""
        base = template_draft(case, masked_log)
        user = json.dumps({
            "title": case.title, "steps": case.steps, "expected": case.expected, "actual": case.actual,
            "priority": case.priority, "log_excerpt": base["log_excerpt"],
        }, ensure_ascii=False)
        payload = {"model": self.model, "temperature": 0,
                   "messages": [{"role": "system", "content": _PROMPT}, {"role": "user", "content": user}]}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            resp = self.transport(self.url, headers, payload, self.timeout)
            content = resp["choices"][0]["message"]["content"]
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
            fields = _validate_llm_fields(json.loads(content))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return base, TEMPLATE_GENERATOR, f"LLM недоступна ({type(e).__name__}), использован шаблон"
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as e:
            return base, TEMPLATE_GENERATOR, f"ответ LLM отклонён: {e}; использован шаблон"
        return {**base, **fields}, f"llm:{self.model}", ""
