# Задачи разработки

```
Статус: на проверке
Дата: 2026-11-17
Автор: Claude (раздел 4 паспорта); статусы обновлены после раздела 8
Основание: docs/SPEC.md
```

| # | Задача | Зависимость | Компонент / файл | Проверяемый результат | Статус |
|---|---|---|---|---|---|
| T1 | Чтение и валидация CSV рана и багов | — | `src/bugdraft/io_csv.py` | AC10; `test_units.TestCsv` | Выполнено |
| T2 | Проверка полноты | T1 | `src/bugdraft/checks.py` | AC3, E4; `test_units.TestChecks` | Выполнено |
| T3 | Маскирование | — | `src/bugdraft/masking.py` | AC6; `test_units.TestMasking` | Выполнено |
| T4 | Окружение, компонент, серьёзность, сводка ошибки | T3 | `src/bugdraft/classify.py` | AC1, AC4; `test_units.TestClassify` | Выполнено |
| T5 | Поиск дублей | T1 | `src/bugdraft/duplicates.py` | AC2; TC-1042 без кандидатов; `test_units.TestDuplicates` | Выполнено |
| T6 | Шаблонный черновик | T4 | `src/bugdraft/drafting.py` | AC1; `test_flow.TestDrafting` | Выполнено |
| T7 | LLM-черновик с проверкой схемы и откатом | T6 | `src/bugdraft/drafting.py` | AC9 на заглушке; `test_flow.TestLLMFallback` | Выполнено |
| T8 | Сборка предложений | T2–T7 | `src/bugdraft/pipeline.py` | AC1–AC5, AC13; `test_flow.TestPipeline` | Выполнено |
| T9 | Решения | T8 | `src/bugdraft/cli.py` (decide) | E5, E7, AC14; `test_flow.TestCliAndPublish` | Выполнено |
| T10 | Публикация в outbox, идемпотентность | T9 | `src/bugdraft/publish.py` | AC7, AC8; `test_flow.TestCliAndPublish` | Выполнено |
| T11 | Заготовка GitLab-публикации с повторами | T10 | `src/bugdraft/publish.py` | AC11 на заглушке (`test_flow.TestGitLabRetries`); реальный вызов — не в MVP | Выполнено |
| T12 | Сводка | T8 | `src/bugdraft/pipeline.py` | AC12 | Выполнено |
| T13 | CLI и UTF-8 вывод | T8–T12 | `src/bugdraft/cli.py`, `__main__.py` | Сквозной запуск по RUN.md | Выполнено |
| T14 | Скилл ревью и проверка на двух diff | T13 | `skills/code-review/`, `review/` | review-report.md | Выполнено |
| T15 | Тест-отчёт | T13 | `docs/TEST-REPORT.md` | Все тесты пройдены или отмечены | Выполнено |
