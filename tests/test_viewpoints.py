import unittest

from jev_review.viewpoints import ViewpointError, bundled_names, load, parse_text, validate

GOOD = """
[review]
name = "t"
language = "en"
red = 0.8
yellow = 0.4

[[viewpoint]]
id = "a"
question = "Does an added line contain A?"
exceptions = ["Ignore tests."]
files = ["*.py"]

[[viewpoint]]
id = "b"
question = "Does an added line contain B?"
report = false

[[rule]]
id = "a_and_b"
all = ["a", "b"]
"""


class ViewpointTest(unittest.TestCase):
    def test_parse(self):
        vs = parse_text(GOOD, "t.toml")
        validate(vs)
        self.assertEqual((vs.red, vs.yellow, vs.language), (0.8, 0.4, "en"))
        a = vs.get("a")
        self.assertEqual(a.instructions(), "Does an added line contain A? Ignore tests.")
        self.assertTrue(a.applies_to("src/x.py"))
        self.assertFalse(a.applies_to("src/x.js"))
        self.assertFalse(vs.get("b").report)
        self.assertEqual(vs.rules[0].all, ["a", "b"])

    def test_errors(self):
        bad = {
            "bad id": '[[viewpoint]]\nid = "Bad"\nquestion = "q?"',
            "no question": '[[viewpoint]]\nid = "a"',
            "severity": '[[viewpoint]]\nid = "a"\nquestion = "q?"\nseverity = "urgent"',
            "unknown key": '[[viewpoint]]\nid = "a"\nquestion = "q?"\nweight = 2',
            "empty rule": '[[viewpoint]]\nid = "a"\nquestion = "q?"\n[[rule]]\nid = "r"\nnone = ["a"]',
        }
        for name, text in bad.items():
            with self.subTest(name), self.assertRaises(ViewpointError):
                validate(parse_text(text))

    def test_rule_reference_and_duplicates(self):
        with self.assertRaises(ViewpointError):
            validate(parse_text('[[viewpoint]]\nid = "a"\nquestion = "q?"\n[[rule]]\nid = "r"\nall = ["zzz"]'))
        with self.assertRaises(ViewpointError):
            validate(parse_text('[[viewpoint]]\nid = "a"\nquestion = "q?"\n[[viewpoint]]\nid = "a"\nquestion = "q2?"'))
        with self.assertRaises(ViewpointError):
            validate(parse_text('[review]\nred = 0.3\nyellow = 0.5\n[[viewpoint]]\nid = "a"\nquestion = "q?"'))

    def test_bundled(self):
        self.assertIn("core.ja", bundled_names())
        self.assertIn("core.en", bundled_names())
        ja, en = load(["core.ja"]), load(["core.en"])
        self.assertEqual([v.id for v in ja.viewpoints], [v.id for v in en.viewpoints])
        self.assertTrue(all(len(v.exceptions) <= 3 for v in ja.viewpoints + en.viewpoints))

    def test_merge_multiple_files(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "extra.toml"
            p.write_text('[[viewpoint]]\nid = "extra_check"\nquestion = "Is there X?"', encoding="utf-8")
            vs = load(["core.en", str(p)])
            self.assertEqual(vs.name, "core.en")
            self.assertIsNotNone(vs.get("extra_check"))


if __name__ == "__main__":
    unittest.main()
