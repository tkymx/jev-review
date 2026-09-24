import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from jev_review.cli import main
from helpers import SIMPLE_DIFF, FakeClient

ROOT = Path(__file__).resolve().parents[1]


class CliTest(unittest.TestCase):
    def run_cli(self, argv, client=None):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(argv, client=client)
        return code, buf.getvalue()

    def test_run_writes_xml_and_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            patch = Path(d) / "x.diff"
            patch.write_text(SIMPLE_DIFF, encoding="utf-8")
            out = Path(d) / "report.xml"
            client = FakeClient({"sql_injection": r"SELECT .*\+", "debug_leftover": r"DEBUG"}, locate_line=11)
            code, text = self.run_cli(["run", "--patch", str(patch), "-v", "core.en", "-o", str(out)], client)
            self.assertEqual(code, 1)                           # red found
            xml = out.read_text(encoding="utf-8")
            self.assertIn('<finding id="sql_injection" kind="viewpoint" status="red"', xml)
            self.assertIn("report:", text)
            code, _ = self.run_cli(["run", "--patch", str(patch), "-v", "core.en", "-o", str(out), "--fail-on", "never"], client)
            self.assertEqual(code, 0)

    def test_dry_run_needs_no_client(self):
        with tempfile.TemporaryDirectory() as d:
            patch = Path(d) / "x.diff"
            patch.write_text(SIMPLE_DIFF, encoding="utf-8")
            code, text = self.run_cli(["run", "--patch", str(patch), "-v", "core.ja", "--dry-run"])
            self.assertEqual(code, 0)
            self.assertIn("2 units", text)
            self.assertIn("estimate:", text)

    def test_lint_exit_codes(self):
        code, text = self.run_cli(["lint", "core.en"])
        self.assertEqual(code, 0)
        code, text = self.run_cli(["lint", str(ROOT / "examples/viewpoints/anti-patterns.ja.toml")])
        self.assertEqual(code, 1)
        self.assertIn("JR003", text)

    def test_eval_on_samples(self):
        # A fake client that recognises two sample patterns: recall on those, zero false positives elsewhere.
        client = FakeClient({"sql_injection": r"SELECT \* FROM users WHERE name = '\" \+", "html_injection": r"innerHTML ="})
        code, text = self.run_cli(["eval", "-v", "core.en", "--samples", str(ROOT / "samples"),
                                   "--only", "sql_concat", "--only", "js_xss", "--only", "clean_"], client)
        self.assertIn("sql_injection", text)
        self.assertIn("html_injection", text)
        self.assertIn("100%", text)

    def test_samples_index_refers_to_existing_files_and_ids(self):
        import tomllib
        from jev_review.viewpoints import load
        ids = {v.id for v in load(["core.en"]).viewpoints}
        data = tomllib.loads((ROOT / "samples/index.toml").read_text(encoding="utf-8"))
        for c in data["case"]:
            with self.subTest(c["id"]):
                self.assertTrue((ROOT / "samples" / c["patch"]).exists())
                self.assertTrue(set(c["expect"]) <= ids)


if __name__ == "__main__":
    unittest.main()
