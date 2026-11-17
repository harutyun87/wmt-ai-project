# Техническое задание: bugdraft — помощник оформления баг-репортов

```
Статус: на проверке
Дата: 2026-11-17
Автор: Claude (раздел 4 паспорта)
Основание: docs/TO-BE.md, docs/Technology-map.md, data/synthetic/
Не проверено: требования к времени и стоимости LLM — оценки; реальные форматы TMS и трекера
```

## 1. Цель и границы

**Цель.** По экспорту тест-рана предложить решение по каждому упавшему кейсу (новый баг / дубль / вернуть QA-инженеру / окружение), подготовить черновик баг-репорта и после подтверждения человеком сформировать задачи для трекера.

**Границы MVP.** Локальный CLI на Python 3.10+ без внешних зависимостей. Вход — CSV-файлы. Публикация — только в файлы outbox. LLM подключается опционально. Решения принимает человек.

**Вне MVP.** Реальная запись в трекер, интеграция с TMS, интерфейс, обработка изображений.

## 2. Пользователи и права

| Роль | Что может | Чего не может |
|---|---|---|
| QA-инженер | Запускать `analyze`, `decide`, `publish` | Публиковать без решения; менять чужие решения задним числом без записи |
| QA Lead | То же + просматривать сводки | — |
| Программа | Читать вход, писать в `out/<RUN-ID>/` | Сетевые вызовы, кроме LLM (если включена) и публикации (не в MVP) |
| LLM | Получает только маскированный текст кейса | Видеть сырые логи, вложения, секреты; влиять на решение без человека |

Секреты (`LLM_API_KEY`, `GITLAB_TOKEN`) — только из переменных окружения; в файлы и отчёты не пишутся.

## 3. Сценарии

| ID | Сценарий | Шаги | Результат |
|---|---|---|---|
| S1 | Новый баг | analyze → предложение `new_bug` с черновиком → decide approve → publish | `outbox/issue__<case>__<build>.json` |
| S2 | Дубль | analyze → `duplicate` с кандидатом → decide approve → publish | `outbox/note__<case>__<build>.json` (комментарий к существующему багу) |
| S3 | Неполные данные | analyze → `return_to_tester` со списком недостающего | Ничего не публикуется; кейс в сводке |
| S4 | Проблема окружения | analyze → `environment` с признаком | Ничего не публикуется; кейс в сводке |
| S5 | Человек не согласен | decide reject / decide с другим действием | Публикуется только то, что подтверждено |
| S6 | Повторный запуск publish | publish дважды | Второй раз файлы не создаются и не перезаписываются |
| S7 | LLM недоступна или ответила мусором | analyze --drafter llm | Шаблонный черновик, причина в `generator_note` |

## 4. Ошибки и реакция

| ID | Ситуация | Реакция | Код выхода |
|---|---|---|---|
| E1 | Нет файла рана / багов | Сообщение с путём | 2 |
| E2 | Нет обязательной колонки CSV | Сообщение со списком колонок | 2 |
| E3 | Неизвестный статус кейса | Кейс пропускается с предупреждением | 0 |
| E4 | Вложение указано, но файла нет | Кейс → `return_to_tester`, missing: `attachment_file` | 0 |
| E5 | `decide` для кейса, которого нет в proposals | Ошибка | 2 |
| E6 | `publish` без `decisions.json` | Сообщение «нет решений» | 2 |
| E7 | Решение `approve` для `return_to_tester` / `environment` | Решение записывается, публикации нет | 0 |
| E8 | LLM: тайм-аут, HTTP-ошибка, ответ не по схеме | Откат на шаблон | 0 |
| E9 | Публикация в трекер (не MVP): 5xx / тайм-аут | До 3 попыток с паузами 1 и 2 с между ними; затем ошибка по кейсу, остальные продолжаются | 1 |
| E10 | Публикация: 4xx | Без повторов, ошибка по кейсу | 1 |

## 5. Компоненты

| Модуль | Ответственность |
|---|---|
| `bugdraft/io_csv.py` | Чтение и валидация CSV (UTF-8, в т.ч. с BOM) |
| `bugdraft/checks.py` | Проверка полноты |
| `bugdraft/masking.py` | Маскирование |
| `bugdraft/classify.py` | Окружение, компонент, серьёзность (предложение), сводка ошибки из лога |
| `bugdraft/duplicates.py` | Поиск дублей |
| `bugdraft/drafting.py` | Шаблонный черновик, LLM-черновик с проверкой схемы и откатом |
| `bugdraft/pipeline.py` | Сборка предложений |
| `bugdraft/publish.py` | Outbox, заготовка GitLab с повторами |
| `bugdraft/cli.py` | Команды `analyze`, `decide`, `publish` |

## 6. Контракты данных

### 6.1 CSV рана (вход)

Кодировка UTF-8. Обязательные колонки: `case_id, title, priority, steps, expected, actual, status, build, environment, tester, attachments`. `status` ∈ Passed, Failed, Blocked, Skipped. `attachments` — пути через `;` относительно `--attachments-dir`. `steps` — «1. …; 2. …».

### 6.2 CSV открытых багов (вход)

Обязательные колонки: `bug_id, title, status, severity, component`. Для поиска дублей используются статусы Open, In Progress, Reopened.

### 6.3 proposals.json (выход analyze)

```json
{
  "run_id": "RUN-2026-11-16-01",
  "generated_at": "ISO-8601",
  "proposals": [{
    "case_id": "TC-1042",
    "status": "Failed",
    "suggestion": "new_bug | duplicate | return_to_tester | environment",
    "reasons": ["…"],
    "missing": ["attachments"],
    "duplicate_candidates": [{"bug_id": "BUG-311", "score": 0.67, "title": "…"}],
    "draft": {
      "title": "…", "severity": "Major", "component": "cart",
      "build": "2.14.0-rc3", "environment": "Chrome 131 / stage",
      "steps": ["…"], "expected": "…", "actual": "…",
      "log_excerpt": ["…"], "links": ["TC-1042"]
    },
    "generator": "template-v1 | llm:<model>",
    "generator_note": ""
  }]
}
```

`draft` есть только у `new_bug` и `duplicate` (для дубля — как текст комментария). `log_excerpt` — только маскированный текст.

### 6.4 decisions.json

```json
{"TC-1042": {"action": "approve", "severity": "Major", "duplicate_of": null,
             "for_suggestion": "new_bug", "for_fingerprint": "<16 hex>",
             "by": "QA-инженер", "at": "ISO-8601", "replaces": {"…": "прежнее решение, если было"}}}
```

`action` ∈ approve, reject, duplicate, return, environment. `duplicate` требует `duplicate_of`.
`for_fingerprint` — отпечаток содержания предложения на момент решения. Если после повторного `analyze` предложение изменилось, решение не публикуется до повторного `decide` (добавлено по ревью R1).

### 6.5 Outbox

`issue__<case>__<build>.json`: `{"kind":"issue","title","description","labels":["bug","severity::Major","component::cart"],"case_id","build"}`.
`note__<case>__<build>.json`: `{"kind":"note","bug_id","body","case_id","build"}`.

Публикуется: `approve` для `new_bug` → issue; `approve` для `duplicate` или `duplicate` → note.

### 6.6 LLM (опционально)

`POST {LLM_BASE_URL}/v1/chat/completions`, модель `LLM_MODEL`, ключ `LLM_API_KEY` (необязателен для локальной). Ответ модели — JSON с полями `title` (≤ 120 символов), `steps` (непустой список строк), `severity` ∈ Critical, Major, Minor, Trivial. Остальные поля черновика берутся из кейса, а не из ответа модели.

## 7. Требования к качеству и ресурсам

| Требование | Значение |
|---|---|
| Время analyze без LLM | ≤ 5 с на 500 кейсов |
| Время analyze с LLM | ≤ 20 с на кейс (тайм-аут запроса 20 с) |
| Стоимость | MVP — 0 (шаблон / локальная LLM); внешняя LLM — оценка в разделе 9 |
| Нагрузка | До 3 ранов в день, до 500 кейсов в ране |
| Утечки | В proposals.json, summary.md, outbox и запросах к LLM нет e-mail, токенов, паролей, номеров карт и телефонов из логов |
| Повторяемость | Один и тот же вход и шаблонный генератор → одинаковые предложения (кроме `generated_at`) |
| Совместимость | Windows, macOS, Linux; вывод в консоль в UTF-8 |

## 8. Критерии приёмки

| ID | Критерий | Тестовый вход | Ожидаемый выход |
|---|---|---|---|
| AC1 | Новый баг распознан | RUN-2026-11-16-01, TC-1042 | `new_bug`, severity Major, component cart, заголовок содержит «500 на POST /api/cart/promo» |
| AC2 | Дубль найден | TC-1107 + existing-bugs.csv | `duplicate`, первый кандидат BUG-311 |
| AC3 | Неполные данные | TC-1150 (нет вложений) | `return_to_tester`, missing содержит `attachments`, `draft` = null |
| AC4 | Окружение | TC-1201 | `environment`, причина упоминает «connect timeout» |
| AC5 | Passed не обрабатываются | 6 Passed-кейсов | Нет в proposals |
| AC6 | Маскирование | Лог с e-mail, `token=…`, номером карты, телефоном | В выходных файлах только `<email>`, `<masked>`, `<card>`, `<phone>`; временные метки не изменены |
| AC7 | Без решения — без публикации | proposals без decisions | publish → код 2, outbox пуст |
| AC8 | Идемпотентность | publish дважды | Одинаковый набор файлов, второй запуск: «пропущено: N» |
| AC9 | Откат LLM | Заглушка: тайм-аут / мусор / неверная схема | Шаблонный черновик, `generator_note` с причиной |
| AC10 | Ошибки входа | CSV без колонки `status` | Код 2, сообщение со списком колонок |
| AC11 | Повторы публикации | Заглушка: 503, 503, 201 | 3 вызова, успех; 400 → 1 вызов, ошибка |
| AC12 | Сводка | RUN-2026-11-16-01 | summary.md: упало 4, по одному в каждой категории |
| AC13 | Совпадение с эталоном | data/synthetic/expected-outcomes.md | 4 из 4 предложений совпадают |
| AC14 | Устаревшее решение | decide approve → analyze с новым багом-кандидатом → publish | Outbox пуст, сообщение «повторите decide» |
