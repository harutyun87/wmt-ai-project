"""CLI: analyze → decide → publish (SPEC 3, 4)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from . import __version__
from .drafting import LLMDrafter
from .io_csv import InputError, load_bugs, load_run
from .pipeline import SUGGESTION_LABELS, analyze, fingerprint, summary_markdown
from .publish import build_items, publish_outbox

ACTIONS = ["approve", "reject", "duplicate", "return", "environment"]
SEVERITIES = ["Critical", "Major", "Minor", "Trivial"]


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, what: str) -> dict:
    if not path.is_file():
        raise InputError(f"нет {what}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_analyze(a: argparse.Namespace) -> int:
    run_path = Path(a.run)
    cases, warnings = load_run(run_path)
    bugs = load_bugs(Path(a.bugs))
    for w in warnings:
        print(f"предупреждение: {w}", file=sys.stderr)
    drafter = None
    if a.drafter == "llm":
        base, model = os.environ.get("LLM_BASE_URL"), os.environ.get("LLM_MODEL")
        if not base or not model:
            raise InputError("для --drafter llm задайте LLM_BASE_URL и LLM_MODEL (см. .env.example)")
        drafter = LLMDrafter(base, model, os.environ.get("LLM_API_KEY"))
    run_id = a.run_id or run_path.stem.removeprefix("test-run-")
    attachments_dir = Path(a.attachments_dir) if a.attachments_dir else run_path.parent
    result = analyze(cases, bugs, attachments_dir, run_id, drafter)
    out = Path(a.out) / run_id
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "proposals.json", result)
    (out / "summary.md").write_text(summary_markdown(result), encoding="utf-8")
    print(f"Ран {run_id}: кейсов {result['total_cases']}, упало {len(result['proposals'])}")
    for p in result["proposals"]:
        print(f"  {p['case_id']:<10} {SUGGESTION_LABELS[p['suggestion']]:<26} {'; '.join(p['reasons'])}")
    print(f"Результат: {out / 'proposals.json'}, {out / 'summary.md'}")
    return 0


def cmd_decide(a: argparse.Namespace) -> int:
    out = Path(a.out)
    proposals = _read_json(out / "proposals.json", "proposals.json — сначала запустите analyze")
    by_id = {p["case_id"]: p for p in proposals["proposals"]}
    if a.case not in by_id:
        raise InputError(f"кейса {a.case} нет среди предложений: {', '.join(sorted(by_id))}")
    if a.action == "duplicate" and not a.duplicate_of:
        raise InputError("для action duplicate укажите --duplicate-of BUG-N")
    path = out / "decisions.json"
    decisions = _read_json(path, "") if path.is_file() else {}
    previous = decisions.get(a.case)
    # Решение привязано к версии предложения: после повторного analyze его нужно подтвердить заново.
    decisions[a.case] = {"action": a.action, "severity": a.severity, "duplicate_of": a.duplicate_of,
                         "for_suggestion": by_id[a.case]["suggestion"],
                         "for_fingerprint": fingerprint(by_id[a.case]),
                         "by": a.by, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    if previous:
        decisions[a.case]["replaces"] = previous
    _write_json(path, decisions)
    print(f"{a.case}: {a.action}" + (" (решение заменено, прежнее сохранено в replaces)" if previous else ""))
    return 0


def cmd_publish(a: argparse.Namespace) -> int:
    out = Path(a.out)
    proposals = _read_json(out / "proposals.json", "proposals.json — сначала запустите analyze")
    decisions = _read_json(out / "decisions.json", "решений (decisions.json) — сначала выполните decide")
    items, notes = build_items(proposals, decisions)
    written, skipped = publish_outbox(items, out / "outbox")
    for n in notes:
        print(f"  {n}")
    print(f"Outbox: записано {len(written)}, пропущено (уже было) {len(skipped)}")
    for name in written:
        print(f"  + {name}")
    print("Реальная публикация в трекер в MVP не выполняется: перенесите файлы outbox вручную.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bugdraft", description="Помощник оформления баг-репортов (учебный MVP)")
    p.add_argument("--version", action="version", version=f"bugdraft {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    an = sub.add_parser("analyze", help="предложения по упавшим кейсам рана")
    an.add_argument("--run", required=True, help="CSV тест-рана")
    an.add_argument("--bugs", required=True, help="CSV открытых багов")
    an.add_argument("--attachments-dir", help="папка вложений (по умолчанию — папка CSV рана)")
    an.add_argument("--out", default="out", help="папка результатов (по умолчанию out/)")
    an.add_argument("--run-id", help="идентификатор рана (по умолчанию из имени файла)")
    an.add_argument("--drafter", choices=["template", "llm"], default="template")
    an.set_defaults(func=cmd_analyze)

    de = sub.add_parser("decide", help="решение QA-инженера по кейсу")
    de.add_argument("--out", required=True, help="папка рана, например out/RUN-2026-11-16-01")
    de.add_argument("--case", required=True)
    de.add_argument("--action", required=True, choices=ACTIONS)
    de.add_argument("--severity", choices=SEVERITIES)
    de.add_argument("--duplicate-of")
    de.add_argument("--by", default="QA-инженер", help="роль, не ФИО")
    de.set_defaults(func=cmd_decide)

    pu = sub.add_parser("publish", help="записать подтверждённые решения в outbox")
    pu.add_argument("--out", required=True, help="папка рана")
    pu.set_defaults(func=cmd_publish)
    return p


def main(argv: list[str] | None = None) -> int:
    # Консоль Windows по умолчанию не UTF-8: без этого кириллица в выводе ломается или падает.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except InputError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 2
