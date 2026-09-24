import unittest
from pathlib import Path

from jev_review.lint import lint
from jev_review.viewpoints import load, parse_text

ROOT = Path(__file__).resolve().parents[1]


def codes(question, **extra):
    body = f'[[viewpoint]]\nid = "x"\nquestion = "{question}"\n'
    for k, v in extra.items():
        body += f"{k} = {v}\n"
    return {i.code for i in lint(parse_text(body)) if i.level in ("error", "warn")}


class LintTest(unittest.TestCase):
    def test_bundled_files_are_clean(self):
        for name in ("core.ja", "core.en"):
            with self.subTest(name):
                self.assertEqual([i for i in lint(load([name]))], [])

    def test_anti_pattern_examples_hit_every_check(self):
        for f in ("anti-patterns.ja.toml", "anti-patterns.en.toml"):
            with self.subTest(f):
                found = {i.code for i in lint(load([str(ROOT / "examples" / "viewpoints" / f)]))}
                self.assertTrue({"JR001", "JR002", "JR003", "JR004", "JR005", "JR006", "JR007", "JR008", "JR009", "JR013"} <= found, found)

    def test_absence(self):
        self.assertIn("JR001", codes("外部 API の呼び出しにタイムアウトの指定が無いか。"))
        self.assertIn("JR001", codes("Is a timeout missing on the API call?"))
        self.assertNotIn("JR001", codes("追加行に、上限チェックなしで課金 API を呼び出しているコードがあるか。"))
        self.assertNotIn("JR001", codes("Does an added line call a paid API with no spending limit?"))
        # anchored absence is only a note
        self.assertNotIn("JR001", codes("追加行に課金 API を呼び出すコードがあり、上限チェックが同じ追加行に無いか。"))

    def test_logic_words(self):
        self.assertIn("JR002", codes("追加行に SQL 文があり、かつ連結しているか。"))
        self.assertIn("JR003", codes("Is there a loop and also either (a sleep or an API call)?"))
        self.assertIn("JR004", codes("Does this change have any security issues?"))
        self.assertIn("JR005", codes("このコードは読みやすいか。"))
        self.assertIn("JR006", codes("Is this change safe to merge?"))
        self.assertIn("JR007", codes("追加行にロジックの誤りがあるか。"))
        self.assertIn("JR009", codes("Is there X?", exceptions='["a.", "b.", "c.", "d."]'))

    def test_clean_question(self):
        self.assertEqual(codes("Does an added line insert an external value into innerHTML?"), set())


if __name__ == "__main__":
    unittest.main()
