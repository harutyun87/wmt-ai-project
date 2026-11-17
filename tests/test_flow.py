"""Сквозные тесты: черновик, LLM-откат, конвейер, CLI, публикация (SPEC AC1, AC5, AC7–AC9, AC11–AC13, E5–E7)."""
import support  # noqa: F401
import io
import json
import socket
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from support import BUGS_CSV, RUN_CSV, SYN, make_case

from bugdraft.cli import main
from bugdraft.drafting import LLMDrafter, split_steps, template_draft
from bugdraft.io_csv import load_bugs, load_run
from bugdraft.pipeline import analyze, summary_markdown
from bugdraft.publish import GitLabPublisher, PublishError

EXPECTED = {"TC-1042": "new_bug", "TC-1107": "duplicate", "TC-1150": "return_to_tester", "TC-1201": "environment"}


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(args))
    return code, out.getvalue(), err.getvalue()


class TestDrafting(unittest.TestCase):
    def test_split_steps(self):
        self.assertEqual(split_steps("1. Открыть /login; 2. Ввести a; b; 3. Нажать"),
                         ["Открыть /login", "Ввести a; b", "Нажать"])
        self.assertEqual(split_steps(""), [])

    def test_template_AC1(self):
        cases = {c.case_id: c for c in load_run(RUN_CSV)[0]}
        log = (SYN / "run-logs" / "TC-1042.txt").read_text(encoding="utf-8")
        d = template_draft(cases["TC-1042"], log)
        self.assertIn("500 на POST /api/cart/promo", d["title"])
        self.assertEqual((d["severity"], d["component"]), ("Major", "cart"))
        self.assertEqual(len(d["steps"]), 3)
        self.assertEqual(d["links"], ["TC-1042"])
        self.assertTrue(any("NullPointerException" in ln for ln in d["log_excerpt"]))

    def test_long_title_truncated(self):
        d = template_draft(make_case(title="x" * 200), "")
        self.assertLessEqual(len(d["title"]), 120)


class TestLLMFallback(unittest.TestCase):
    """AC9: заглушки вместо сети."""

    def drafter(self, transport):
        return LLMDrafter("http://llm.local", "test-model", transport=transport)

    @staticmethod
    def reply(content):
        return lambda url, h, p, t: {"choices": [{"message": {"content": content}}]}

    def test_valid_response_used(self):
        content = '```json\n{"title": "Промокод не применяется", "steps": ["a", "b"], "severity": "Major"}\n```'
        d, gen, note = self.drafter(self.reply(content)).draft(make_case(), "")
        self.assertEqual((d["title"], d["steps"], gen, note), ("Промокод не применяется", ["a", "b"], "llm:test-model", ""))
        self.assertEqual(d["build"], "1.0.0")  # факты — из кейса, не из модели

    def test_timeout(self):
        def boom(*_):
            raise socket.timeout("timed out")
        d, gen, note = self.drafter(boom).draft(make_case(), "")
        self.assertEqual(gen, "template-v1")
        self.assertIn("недоступна", note)

    def test_garbage_and_bad_schema(self):
        for content in ["не JSON", '{"title": "x"}', '{"title": "x", "steps": ["a"], "severity": "Blocker"}',
                        '["список"]', '{"title": "' + "x" * 200 + '", "steps": ["a"], "severity": "Major"}']:
            d, gen, note = self.drafter(self.reply(content)).draft(make_case(), "")
            self.assertEqual(gen, "template-v1", content)
            self.assertIn("отклонён", note, content)

    def test_unexpected_shape(self):
        d, gen, note = self.drafter(lambda *_: {"error": "x"}).draft(make_case(), "")
        self.assertEqual(gen, "template-v1")

    def test_prompt_gets_masked_text_only(self):
        seen = {}

        def spy(url, h, payload, t):
            seen["payload"] = json.dumps(payload, ensure_ascii=False)
            return {"choices": [{"message": {"content": "{}"}}]}

        from bugdraft.masking import mask
        raw_log = "ERROR [svc] login failed for anna@example.com token=SECRET123"
        self.drafter(spy).draft(make_case(), mask(raw_log))
        self.assertNotIn("anna@example.com", seen["payload"])
        self.assertNotIn("SECRET123", seen["payload"])


class TestPipeline(unittest.TestCase):
    def setUp(self):
        cases, _ = load_run(RUN_CSV)
        self.result = analyze(cases, load_bugs(BUGS_CSV), SYN, "RUN-T")

    def test_matches_reference_AC13(self):
        got = {p["case_id"]: p["suggestion"] for p in self.result["proposals"]}
        self.assertEqual(got, EXPECTED)

    def test_passed_excluded_AC5(self):
        self.assertEqual(self.result["total_cases"], 10)
        self.assertEqual(len(self.result["proposals"]), 4)

    def test_no_draft_for_return_and_env(self):
        by = {p["case_id"]: p for p in self.result["proposals"]}
        self.assertIsNone(by["TC-1150"]["draft"])
        self.assertIsNone(by["TC-1201"]["draft"])
        self.assertIn("attachments", by["TC-1150"]["missing"])

    def test_summary_AC12(self):
        s = summary_markdown(self.result)
        self.assertIn("упало (Failed/Blocked): 4", s)
        for label in ["| Новый баг | 1 |", "| Дубль существующего бага | 1 |", "| Вернуть QA-инженеру | 1 |",
                      "| Проблема окружения | 1 |"]:
            self.assertIn(label, s)

    def test_pipeline_sends_only_masked_log_to_llm_R2(self):
        """Ревью R2: проверка на уровне конвейера, а не только drafter (дефект diff 01 этим и прошёл)."""
        from bugdraft.pipeline import propose
        seen = []

        def spy(url, h, payload, t):
            seen.append(json.dumps(payload, ensure_ascii=False))
            return {"choices": [{"message": {"content": "{}"}}]}

        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "l.txt").write_text("ERROR [svc] login failed anna@example.com token=SECRET123",
                                           encoding="utf-8")
            propose(make_case(attachments=["l.txt"]), [], Path(d), LLMDrafter("http://x", "m", transport=spy))
        self.assertEqual(len(seen), 1)
        self.assertNotIn("SECRET123", seen[0])
        self.assertNotIn("anna@example.com", seen[0])

    def test_case_fields_masked_R02(self):
        """Риск R-02: ПДн в тексте кейса не попадают в черновик и в LLM."""
        from bugdraft.pipeline import propose
        seen = []

        def spy(url, h, payload, t):
            seen.append(json.dumps(payload, ensure_ascii=False))
            return {"choices": [{"message": {"content": "{}"}}]}

        case = make_case(attachments=["run-logs/TC-1042.txt"],
                         steps="1. Войти как ivan.sidorov@example.com; 2. Оплатить картой 4111 1111 1111 1111",
                         actual="Ошибка, звонок клиенту +7 912 345-67-89")
        p = propose(case, [], SYN, LLMDrafter("http://x", "m", transport=spy))
        dumped = json.dumps(p, ensure_ascii=False) + seen[0]
        for secret in ["ivan.sidorov", "4111", "912 345"]:
            self.assertNotIn(secret, dumped)
        self.assertIn("<email>", p["draft"]["steps"][0])

    def test_llm_not_called_for_duplicates_R4(self):
        calls = []
        drafter = LLMDrafter("http://x", "m", transport=lambda *a: calls.append(1) or {})
        cases, _ = load_run(RUN_CSV)
        analyze([c for c in cases if c.case_id == "TC-1107"], load_bugs(BUGS_CSV), SYN, "R", drafter)
        self.assertEqual(calls, [])

    def test_deterministic(self):
        cases, _ = load_run(RUN_CSV)
        again = analyze(cases, load_bugs(BUGS_CSV), SYN, "RUN-T")
        self.assertEqual(again["proposals"], self.result["proposals"])


class TestCliAndPublish(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        code, out, err = run_cli("analyze", "--run", str(RUN_CSV), "--bugs", str(BUGS_CSV), "--out", self.tmp.name)
        self.assertEqual(code, 0, err)
        self.run_dir = Path(self.tmp.name) / "RUN-2026-11-16-01"

    def test_publish_without_decisions_AC7(self):
        code, out, err = run_cli("publish", "--out", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn("decide", err)
        self.assertFalse((self.run_dir / "outbox").exists())

    def test_decide_unknown_case_E5(self):
        code, _, err = run_cli("decide", "--out", str(self.run_dir), "--case", "TC-0000", "--action", "approve")
        self.assertEqual(code, 2)
        self.assertIn("TC-1042", err)

    def test_duplicate_requires_bug_id(self):
        code, _, err = run_cli("decide", "--out", str(self.run_dir), "--case", "TC-1042", "--action", "duplicate")
        self.assertEqual(code, 2)

    def test_full_flow_and_idempotency_AC8(self):
        d = str(self.run_dir)
        run_cli("decide", "--out", d, "--case", "TC-1042", "--action", "approve", "--severity", "Critical")
        run_cli("decide", "--out", d, "--case", "TC-1107", "--action", "approve")
        run_cli("decide", "--out", d, "--case", "TC-1150", "--action", "return")
        run_cli("decide", "--out", d, "--case", "TC-1201", "--action", "approve")  # E7: публикации нет
        code, out, _ = run_cli("publish", "--out", d)
        self.assertEqual(code, 0)
        files = sorted(p.name for p in (self.run_dir / "outbox").iterdir())
        self.assertEqual(files, ["issue__TC-1042__2.14.0-rc3.json", "note__TC-1107__2.14.0-rc3.json"])
        issue = json.loads((self.run_dir / "outbox" / files[0]).read_text(encoding="utf-8"))
        self.assertIn("severity::Critical", issue["labels"])  # решение человека важнее предложения
        note = json.loads((self.run_dir / "outbox" / files[1]).read_text(encoding="utf-8"))
        self.assertEqual(note["bug_id"], "BUG-311")
        self.assertIn("TC-1201", out)
        before = {p.name: p.stat().st_mtime_ns for p in (self.run_dir / "outbox").iterdir()}
        code, out2, _ = run_cli("publish", "--out", d)
        self.assertIn("записано 0, пропущено (уже было) 2", out2)
        after = {p.name: p.stat().st_mtime_ns for p in (self.run_dir / "outbox").iterdir()}
        self.assertEqual(before, after)

    def test_reject_not_published(self):
        d = str(self.run_dir)
        run_cli("decide", "--out", d, "--case", "TC-1042", "--action", "reject")
        run_cli("publish", "--out", d)
        self.assertEqual(list((self.run_dir / "outbox").iterdir()), [])

    def test_redecision_keeps_history(self):
        d = str(self.run_dir)
        run_cli("decide", "--out", d, "--case", "TC-1042", "--action", "reject")
        run_cli("decide", "--out", d, "--case", "TC-1042", "--action", "approve")
        dec = json.loads((self.run_dir / "decisions.json").read_text(encoding="utf-8"))
        self.assertEqual(dec["TC-1042"]["action"], "approve")
        self.assertEqual(dec["TC-1042"]["replaces"]["action"], "reject")

    def test_stale_decision_not_published_R1(self):
        """Ревью R1: решение «новый баг» не должно превратиться в комментарий к другому багу после повторного analyze."""
        d = str(self.run_dir)
        run_cli("decide", "--out", d, "--case", "TC-1042", "--action", "approve")
        bugs2 = Path(self.tmp.name) / "bugs2.csv"
        bugs2.write_text("bug_id,title,status,severity,component\n"
                         "BUG-400,Оплата картой: применение промокода не работает,Open,Major,cart\n", encoding="utf-8")
        run_cli("analyze", "--run", str(RUN_CSV), "--bugs", str(bugs2), "--out", self.tmp.name)
        code, out, _ = run_cli("publish", "--out", d)
        self.assertEqual(code, 0)
        self.assertEqual(list((self.run_dir / "outbox").iterdir()), [])
        self.assertIn("повторите decide", out)

    def test_same_input_reanalysis_keeps_decision(self):
        d = str(self.run_dir)
        run_cli("decide", "--out", d, "--case", "TC-1042", "--action", "approve")
        run_cli("analyze", "--run", str(RUN_CSV), "--bugs", str(BUGS_CSV), "--out", self.tmp.name)
        run_cli("publish", "--out", d)
        self.assertEqual([p.name for p in (self.run_dir / "outbox").iterdir()], ["issue__TC-1042__2.14.0-rc3.json"])

    def test_llm_without_env(self):
        import os
        env = {k: os.environ.pop(k) for k in ["LLM_BASE_URL", "LLM_MODEL"] if k in os.environ}
        self.addCleanup(os.environ.update, env)
        code, _, err = run_cli("analyze", "--run", str(RUN_CSV), "--bugs", str(BUGS_CSV), "--out", self.tmp.name,
                               "--drafter", "llm")
        self.assertEqual(code, 2)
        self.assertIn("LLM_BASE_URL", err)


class TestGitLabRetries(unittest.TestCase):
    """AC11: повторы и тайм-ауты на заглушке, без сети."""

    def publisher(self, responses):
        self.calls, self.sleeps = [], []
        it = iter(responses)

        def sender(url, headers, payload, timeout):
            self.calls.append(url)
            r = next(it)
            if isinstance(r, Exception):
                raise r
            return r, {"iid": 7}

        return GitLabPublisher("https://gitlab.example.test", "qa/shop", "TOKEN", sender=sender,
                               sleep=self.sleeps.append)

    ISSUE = {"kind": "issue", "title": "t", "description": "d", "labels": ["bug"]}

    def test_retry_then_success(self):
        self.assertEqual(self.publisher([503, 503, 201]).publish(self.ISSUE), {"iid": 7})
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.sleeps, [1, 2])
        self.assertIn("/projects/qa%2Fshop/issues", self.calls[0])

    def test_client_error_no_retry(self):
        with self.assertRaises(PublishError):
            self.publisher([400]).publish(self.ISSUE)
        self.assertEqual(len(self.calls), 1)

    def test_timeouts_exhausted(self):
        with self.assertRaises(PublishError) as ctx:
            self.publisher([socket.timeout(), socket.timeout(), socket.timeout()]).publish(self.ISSUE)
        self.assertEqual(len(self.calls), 3)
        self.assertIn("3 попыток", str(ctx.exception))

    def test_http_sender_non_json_success_R3(self):
        """Ревью R3: 201 с не-JSON телом (прокси) — успех, а не исключение."""
        import http.server
        import threading
        from bugdraft.publish import http_sender

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(201)
                self.end_headers()
                self.wfile.write(b"Created")

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        status, body = http_sender(f"http://127.0.0.1:{srv.server_port}/x", {}, {"a": 1}, 5)
        self.assertEqual((status, body), (201, {"raw": "Created"}))

    def test_note_url(self):
        self.publisher([201]).publish({"kind": "note", "bug_id": "BUG-311", "body": "b"})
        self.assertTrue(self.calls[0].endswith("/issues/311/notes"))


if __name__ == "__main__":
    unittest.main()
