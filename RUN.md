# Запуск bugdraft

Учебный MVP. Нужен только Python 3.10+ (стандартная библиотека, без установки пакетов).
Все команды — из корня проекта. Данные — синтетические, из `data/synthetic/`.

## 1. Подготовка

Windows (PowerShell):

```powershell
python --version          # 3.10 или новее
$env:PYTHONPATH = "src"
```

macOS / Linux / Git Bash:

```bash
python3 --version
export PYTHONPATH=src
```

Ниже — команды для PowerShell. В bash замените `python` на `python3`, а `` ` `` в конце строки — на `\`.

## 2. Тесты

```powershell
python -m unittest discover -s tests -v
```

Ожидается: `Ran 54 tests … OK`.

## 3. Сквозной пример

```powershell
# 1) предложения по упавшим кейсам
python -m bugdraft analyze `
  --run data/synthetic/test-run-RUN-2026-11-16-01.csv `
  --bugs data/synthetic/existing-bugs.csv `
  --out out

# 2) решения QA-инженера
python -m bugdraft decide --out out/RUN-2026-11-16-01 --case TC-1042 --action approve --severity Major
python -m bugdraft decide --out out/RUN-2026-11-16-01 --case TC-1107 --action approve
python -m bugdraft decide --out out/RUN-2026-11-16-01 --case TC-1150 --action return
python -m bugdraft decide --out out/RUN-2026-11-16-01 --case TC-1201 --action environment

# 3) публикация в outbox (в трекер ничего не отправляется)
python -m bugdraft publish --out out/RUN-2026-11-16-01
```

Результат в `out/RUN-2026-11-16-01/`:

| Файл | Что внутри |
|---|---|
| `proposals.json` | Предложения по 4 упавшим кейсам (контракт — SPEC 6.3) |
| `summary.md` | Сводка по рану для QA Lead |
| `decisions.json` | Решения с ролью, временем и отпечатком предложения |
| `outbox/issue__TC-1042__2.14.0-rc3.json` | Новый баг для трекера |
| `outbox/note__TC-1107__2.14.0-rc3.json` | Комментарий к BUG-311 |

Папка `out/` не коммитится (см. `.gitignore`).

Если после решений снова запустить `analyze` и предложение по кейсу изменится, `publish` его пропустит
с сообщением «повторите decide».

## 4. Черновик через LLM (необязательно)

Локальная модель через Ollama (OpenAI-совместимый API):

```powershell
ollama pull qwen2.5:7b
$env:LLM_BASE_URL = "http://localhost:11434"
$env:LLM_MODEL = "qwen2.5:7b"
python -m bugdraft analyze --run data/synthetic/test-run-RUN-2026-11-16-01.csv `
  --bugs data/synthetic/existing-bugs.csv --out out --drafter llm
```

Если модель недоступна или ответила не по схеме, черновик будет шаблонным, причина — в `generator_note`.
С реальной моделью в MVP **не проверялось** (см. docs/MVP-CHECK.md).

## 5. Коды выхода

| Код | Значение |
|---|---|
| 0 | Успех |
| 2 | Ошибка входных данных (нет файла, колонки, решения, неверный аргумент) |
