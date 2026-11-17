# Отчёт о тестировании bugdraft (раздел 6)

```
Статус: на проверке
Дата: 2026-11-17
Автор: Claude
Основание: docs/SPEC.md (AC1–AC14), RUN.md, review/implementation-review.md
Окружение: Linux, Python 3.13 (облачная среда Claude). На Windows-машине участника не запускалось
```

## 1. Итог

| Проверка | Команда | Результат |
|---|---|---|
| Автотесты | `python -m unittest discover -s tests` | **54 из 54 пройдено** |
| Кодировка | `python -X warn_default_encoding -W always::EncodingWarning -m unittest discover -s tests` | 0 предупреждений |
| Ресурсы | `python -W always -m unittest discover -s tests` | 0 ResourceWarning (после исправления закрытия тестового сервера) |
| Сквозной сценарий | команды из RUN.md, раздел 3 | Пройден: 4 предложения, 2 файла outbox, повторный publish — «записано 0, пропущено 2» (повторено после финальных исправлений) |
| Нагрузка | analyze: 500 кейсов × 300 открытых багов | 0,22 с (требование ≤ 5 с) |
| Консоль не в UTF-8 | `PYTHONIOENCODING=ascii python -m bugdraft analyze …` | Кириллица выводится (cli переводит вывод в UTF-8) |

## 2. Критерии приёмки

| AC | Вход | Ожидание | Факт | Статус | Тест / лог |
|---|---|---|---|---|---|
| AC1 | TC-1042 | new_bug, Major, cart, «500 на POST /api/cart/promo» | Совпадает | Пройден | `test_template_AC1`, `test_error_summary_and_component_AC1` |
| AC2 | TC-1107 + existing-bugs.csv | duplicate, BUG-311 | BUG-311, сходство 0,56 | Пройден | `test_duplicate_found_AC2` |
| AC3 | TC-1150 | return_to_tester, missing: attachments, draft = null | Совпадает | Пройден | `test_no_attachments_AC3`, `test_no_draft_for_return_and_env` |
| AC4 | TC-1201 | environment, «connect timeout» | Совпадает | Пройден | `test_environment_AC4` |
| AC5 | 6 Passed | Нет в proposals | 4 предложения из 10 кейсов | Пройден | `test_passed_excluded_AC5` |
| AC6 | e-mail, токен, карта, телефон, Bearer, JSON-пароль | Только метки; время и ID не изменены | Совпадает | Пройден | `test_secrets_AC6`, `test_phone_variants`, `test_synthetic_logs_unchanged` |
| AC7 | publish без decisions | Код 2, outbox пуст | Совпадает | Пройден | `test_publish_without_decisions_AC7` |
| AC8 | publish дважды | Файлы не меняются | mtime совпадает | Пройден | `test_full_flow_and_idempotency_AC8` |
| AC9 | Заглушка LLM: тайм-аут, мусор, 4 варианта неверной схемы | Шаблон + причина | Совпадает | Пройден | `TestLLMFallback` (5 тестов) |
| AC10 | CSV без колонки status | Код 2, список колонок | Совпадает | Пройден | `test_missing_column_AC10` |
| AC11 | Заглушка: 503, 503, 201 / 400 / 3 тайм-аута | 3 вызова и успех / 1 вызов / ошибка после 3 | Совпадает | Пройден | `TestGitLabRetries` |
| AC12 | RUN-2026-11-16-01 | summary: упало 4, по одному в категории | Совпадает | Пройден | `test_summary_AC12` |
| AC13 | expected-outcomes.md | 4 из 4 | 4 из 4 | Пройден | `test_matches_reference_AC13` |
| AC14 | decide → analyze с новым кандидатом → publish | Outbox пуст, «повторите decide» | Совпадает | Пройден | `test_stale_decision_not_published_R1` |

## 3. Ревью, исправления, повторная проверка

| Замечание | Исправление | Тест падал до исправления | После |
|---|---|---|---|
| R1 (High) устаревшее решение публикуется | Отпечаток предложения в решении | Да (FAIL на f4ffb74) | Пройден |
| R2 (Medium) пробел в тестах маскирования | Тест на уровне конвейера | Да (FAIL на diff 01) | Пройден |
| R3 (Medium) не-JSON при 2xx | Обработка в `http_sender` | Да (ERROR на f4ffb74) | Пройден |
| R4 (Low) LLM для дублей | Шаблон для дублей | Да (FAIL на f4ffb74) | Пройден |
| Мера R-02 (раздел 8): ПДн в полях кейса | Маскирование `title, steps, expected, actual, environment` | — (новая мера) | `test_case_fields_masked_R02` пройден |
| Совместимость (раздел 8): пути `\` из Windows | Нормализация в `io_csv` | — | `test_windows_backslash_paths` пройден |
| F1 (финальная проверка, Low): обрезанная строка CSV сообщалась как «неизвестный статус» | Отдельное предупреждение «обрезанная строка, нет полей» | Да (сообщение неверное) | `test_truncated_row_reported` пройден |

Подробности — `review/implementation-review.md`.

## 4. Не проверено, заглушки, незавершённое

| Что | Почему | Как проверить |
|---|---|---|
| Запуск на Windows у участника | Нет доступа к терминалу на этой машине | Команды из RUN.md в PowerShell; ожидается 51 OK |
| Реальная LLM (Ollama / внешняя) | Нет модели в среде; только заглушки | RUN.md, раздел 4; план — MVP-CHECK.md |
| Реальная публикация в GitLab | Нет доступа; в MVP только outbox | Тестовый проект GitLab + токен с минимальными правами |
| Реальные данные TMS и трекера | Формат не подтверждён (вопросы № 1, 5) | Обезличенный экспорт одного рана |
| Качество поиска дублей на перефразировках | Синтетика: 1 дубль | Разметка 50 реальных пар «дубль / не дубль» |

## 5. Все автотесты

| Набор | Тест | Статус |
|---|---|---|
| TestChecks | `test_attachment_file_missing_E4` | пройден |
| TestChecks | `test_attachment_outside_dir_rejected` | пройден |
| TestChecks | `test_complete` | пройден |
| TestChecks | `test_empty_required_field` | пройден |
| TestChecks | `test_no_attachments_AC3` | пройден |
| TestClassify | `test_environment_AC4` | пройден |
| TestClassify | `test_environment_from_actual` | пройден |
| TestClassify | `test_error_summary_and_component_AC1` | пройден |
| TestClassify | `test_product_500_is_not_environment` | пройден |
| TestClassify | `test_severity` | пройден |
| TestCliAndPublish | `test_decide_unknown_case_E5` | пройден |
| TestCliAndPublish | `test_duplicate_requires_bug_id` | пройден |
| TestCliAndPublish | `test_full_flow_and_idempotency_AC8` | пройден |
| TestCliAndPublish | `test_llm_without_env` | пройден |
| TestCliAndPublish | `test_publish_without_decisions_AC7` | пройден |
| TestCliAndPublish | `test_redecision_keeps_history` | пройден |
| TestCliAndPublish | `test_reject_not_published` | пройден |
| TestCliAndPublish | `test_same_input_reanalysis_keeps_decision` | пройден |
| TestCliAndPublish | `test_stale_decision_not_published_R1` | пройден |
| TestCsv | `test_bom_and_unknown_status_E3` | пройден |
| TestCsv | `test_load_synthetic_run` | пройден |
| TestCsv | `test_missing_column_AC10` | пройден |
| TestCsv | `test_missing_file_E1` | пройден |
| TestCsv | `test_open_bugs` | пройден |
| TestCsv | `test_truncated_row_reported` | пройден |
| TestCsv | `test_windows_backslash_paths` | пройден |
| TestDrafting | `test_long_title_truncated` | пройден |
| TestDrafting | `test_split_steps` | пройден |
| TestDrafting | `test_template_AC1` | пройден |
| TestDuplicates | `test_closed_bugs_ignored` | пройден |
| TestDuplicates | `test_duplicate_found_AC2` | пройден |
| TestDuplicates | `test_new_bug_below_threshold` | пройден |
| TestDuplicates | `test_stems_normalize_yo` | пройден |
| TestGitLabRetries | `test_client_error_no_retry` | пройден |
| TestGitLabRetries | `test_http_sender_non_json_success_R3` | пройден |
| TestGitLabRetries | `test_note_url` | пройден |
| TestGitLabRetries | `test_retry_then_success` | пройден |
| TestGitLabRetries | `test_timeouts_exhausted` | пройден |
| TestLLMFallback | `test_garbage_and_bad_schema` | пройден |
| TestLLMFallback | `test_prompt_gets_masked_text_only` | пройден |
| TestLLMFallback | `test_timeout` | пройден |
| TestLLMFallback | `test_unexpected_shape` | пройден |
| TestLLMFallback | `test_valid_response_used` | пройден |
| TestMasking | `test_phone_variants` | пройден |
| TestMasking | `test_secrets_AC6` | пройден |
| TestMasking | `test_synthetic_logs_unchanged` | пройден |
| TestPipeline | `test_case_fields_masked_R02` | пройден |
| TestPipeline | `test_deterministic` | пройден |
| TestPipeline | `test_llm_not_called_for_duplicates_R4` | пройден |
| TestPipeline | `test_matches_reference_AC13` | пройден |
| TestPipeline | `test_no_draft_for_return_and_env` | пройден |
| TestPipeline | `test_passed_excluded_AC5` | пройден |
| TestPipeline | `test_pipeline_sends_only_masked_log_to_llm_R2` | пройден |
| TestPipeline | `test_summary_AC12` | пройден |
