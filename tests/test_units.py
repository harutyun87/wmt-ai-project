"""Модульные тесты: CSV, полнота, маскирование, правила, дубли (SPEC AC2–AC6, AC10, E3, E4)."""
import support  # noqa: F401  (путь к src)
import tempfile
import unittest
from pathlib import Path

from support import BUGS_CSV, RUN_CSV, SYN, make_case

from bugdraft.checks import missing_data
from bugdraft.classify import environment_reason, error_summary, guess_component, suggest_severity
from bugdraft.duplicates import THRESHOLD, find_candidates, stems
from bugdraft.io_csv import InputError, load_bugs, load_run
from bugdraft.masking import mask


class TestCsv(unittest.TestCase):
    def test_load_synthetic_run(self):
        cases, warnings = load_run(RUN_CSV)
        self.assertEqual(len(cases), 10)
        self.assertEqual(warnings, [])
        tc = next(c for c in cases if c.case_id == "TC-1042")
        self.assertEqual(tc.attachments, ["run-logs/TC-1042.txt"])

    def test_missing_column_AC10(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "run.csv"
            p.write_text("case_id,title\nTC-1,x\n", encoding="utf-8")
            with self.assertRaises(InputError) as ctx:
                load_run(p)
            self.assertIn("status", str(ctx.exception))

    def test_missing_file_E1(self):
        with self.assertRaises(InputError):
            load_run(Path("нет-такого-файла.csv"))

    def test_bom_and_unknown_status_E3(self):
        header = "case_id,title,priority,steps,expected,actual,status,build,environment,tester,attachments\n"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "run.csv"
            p.write_text(header + "TC-1,a,High,s,e,f,Failed,1,env,QA,\nTC-2,b,High,s,e,f,Unknown,1,env,QA,\n",
                         encoding="utf-8-sig")
            cases, warnings = load_run(p)
        self.assertEqual([c.case_id for c in cases], ["TC-1"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("TC-2", warnings[0])

    def test_truncated_row_reported(self):
        header = "case_id,title,priority,steps,expected,actual,status,build,environment,tester,attachments\n"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "run.csv"
            p.write_text(header + "TC-2,t,High\n", encoding="utf-8")
            cases, warnings = load_run(p)
            bp = Path(d) / "bugs.csv"
            bp.write_text("bug_id,title,status,severity,component\nBUG-1,t\n", encoding="utf-8")
            bugs = load_bugs(bp)
        self.assertEqual(cases, [])
        self.assertIn("обрезанная строка", warnings[0])
        self.assertIn("status", warnings[0])
        self.assertEqual(bugs[0].status, "")  # баг с обрезанной строкой не считается открытым
        self.assertFalse(bugs[0].is_open)

    def test_windows_backslash_paths(self):
        header = "case_id,title,priority,steps,expected,actual,status,build,environment,tester,attachments\n"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "run.csv"
            p.write_text(header + "TC-1,a,High,s,e,f,Failed,1,env,QA,run-logs\\TC-1042.txt; shots\\a.png\n",
                         encoding="utf-8")
            cases, _ = load_run(p)
        self.assertEqual(cases[0].attachments, ["run-logs/TC-1042.txt", "shots/a.png"])
        self.assertEqual(missing_data(make_case(attachments=cases[0].attachments[:1]), SYN), [])

    def test_open_bugs(self):
        bugs = load_bugs(BUGS_CSV)
        self.assertEqual(len(bugs), 4)
        self.assertTrue(all(b.is_open for b in bugs))


class TestChecks(unittest.TestCase):
    def test_no_attachments_AC3(self):
        self.assertEqual(missing_data(make_case(), SYN), ["attachments"])

    def test_attachment_file_missing_E4(self):
        m = missing_data(make_case(attachments=["run-logs/нет.txt"]), SYN)
        self.assertEqual(m, ["attachment_file:run-logs/нет.txt"])

    def test_attachment_outside_dir_rejected(self):
        m = missing_data(make_case(attachments=["../synthetic/README.md", "../../AGENTS.md"]), SYN)
        self.assertIn("attachment_file:../../AGENTS.md", m)

    def test_empty_required_field(self):
        m = missing_data(make_case(environment=" ", attachments=["run-logs/TC-1042.txt"]), SYN)
        self.assertEqual(m, ["environment"])

    def test_complete(self):
        self.assertEqual(missing_data(make_case(attachments=["run-logs/TC-1042.txt"]), SYN), [])


class TestMasking(unittest.TestCase):
    def test_secrets_AC6(self):
        raw = ("2026-11-16T10:14:02.311Z INFO user=anna.petrova@example.com token=abc123SECRET "
               "card 4111 1111 1111 1111 phone +7 (912) 345-67-89 Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.x.y "
               '{"password":"Qwerty!23","cartId":"cart-demo-7781"}')
        out = mask(raw)
        for secret in ["anna.petrova", "abc123SECRET", "4111", "912", "eyJhbGci", "Qwerty"]:
            self.assertNotIn(secret, out)
        for tag in ["<email>", "<masked>", "<card>", "<phone>"]:
            self.assertIn(tag, out)
        self.assertIn("2026-11-16T10:14:02.311Z", out)
        self.assertIn("cart-demo-7781", out)

    def test_synthetic_logs_unchanged(self):
        """Синтетические логи не содержат секретов — маскирование не должно их портить."""
        for p in (SYN / "run-logs").glob("*.txt"):
            text = p.read_text(encoding="utf-8")
            self.assertEqual(mask(text), text, p.name)

    def test_phone_variants(self):
        for phone in ["+79123456789", "8 912 345 67 89", "8-912-345-67-89"]:
            self.assertEqual(mask(f"тел {phone}."), "тел <phone>.", phone)


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.log_1042 = (SYN / "run-logs" / "TC-1042.txt").read_text(encoding="utf-8")
        self.log_1201 = (SYN / "run-logs" / "TC-1201.txt").read_text(encoding="utf-8")

    def test_environment_AC4(self):
        self.assertEqual(environment_reason(make_case(), self.log_1201), "connect timeout")
        self.assertIsNone(environment_reason(make_case(), self.log_1042))

    def test_environment_from_actual(self):
        self.assertIsNotNone(environment_reason(make_case(actual="Платёжный стенд недоступен"), ""))

    def test_product_500_is_not_environment(self):
        self.assertIsNone(environment_reason(make_case(), "POST /api/x -> 503 (10 ms)"))

    def test_error_summary_and_component_AC1(self):
        self.assertEqual(error_summary(self.log_1042), "500 на POST /api/cart/promo")
        self.assertEqual(guess_component(self.log_1042), "cart")
        self.assertEqual(guess_component("[web] ok"), "unknown")

    def test_severity(self):
        self.assertEqual(suggest_severity(make_case(priority="High"), self.log_1042), "Major")
        self.assertEqual(suggest_severity(make_case(priority="Low"), self.log_1042), "Major")
        self.assertEqual(suggest_severity(make_case(priority="Low"), "WARN slow"), "Trivial")
        self.assertEqual(suggest_severity(make_case(priority="???"), ""), "Minor")


class TestDuplicates(unittest.TestCase):
    def setUp(self):
        self.bugs = load_bugs(BUGS_CSV)
        self.cases = {c.case_id: c for c in load_run(RUN_CSV)[0]}

    def test_duplicate_found_AC2(self):
        c = find_candidates(self.cases["TC-1107"], self.bugs)
        self.assertEqual(c[0]["bug_id"], "BUG-311")
        self.assertGreaterEqual(c[0]["score"], THRESHOLD)

    def test_new_bug_below_threshold(self):
        c = find_candidates(self.cases["TC-1042"], self.bugs)
        self.assertTrue(not c or c[0]["score"] < THRESHOLD)

    def test_closed_bugs_ignored(self):
        from bugdraft.io_csv import Bug
        closed = [Bug("BUG-1", "Итог корзины не обновляется после удаления товара", "Closed", "Major", "cart")]
        self.assertEqual(find_candidates(self.cases["TC-1107"], closed), [])

    def test_stems_normalize_yo(self):
        self.assertEqual(stems("Ёлка"), stems("елка"))


if __name__ == "__main__":
    unittest.main()
