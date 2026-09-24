import unittest
import xml.etree.ElementTree as ET

from jev_review.diff import parse
from jev_review.report import summary_text, to_xml
from jev_review.review import Reviewer, status_of
from jev_review.viewpoints import parse_text, validate
from helpers import SIMPLE_DIFF, FakeClient

VS = """
[review]
language = "en"

[[viewpoint]]
id = "sql_concat"
question = "Does an added line build SQL by concatenation?"
severity = "high"

[[viewpoint]]
id = "debug_print"
question = "Does an added line print DEBUG output?"
severity = "low"

[[viewpoint]]
id = "mentions_eval"
question = "Does an added line mention eval?"
target = "any"

[[viewpoint]]
id = "builds_sql"
question = "Is there SQL?"
report = false

[[viewpoint]]
id = "uses_placeholder"
question = "Is there a placeholder?"
report = false

[[rule]]
id = "sql_without_placeholder"
all = ["builds_sql"]
none = ["uses_placeholder"]
severity = "high"
message = "SQL without placeholders"
"""

RULES = {"sql_concat": r"SELECT .*\+", "debug_print": r"DEBUG", "mentions_eval": r"eval",
         "builds_sql": r"SELECT", "uses_placeholder": r"\?"}


def reviewer(client, **kw):
    vs = parse_text(VS)
    validate(vs)
    return Reviewer(client, vs, jobs=2, **kw)


class ReviewTest(unittest.TestCase):
    def test_status_of(self):
        self.assertEqual([status_of(p, 0.7, 0.5) for p in (0.9, 0.7, 0.6, 0.5, 0.2)],
                         ["red", "red", "yellow", "yellow", "green"])

    def test_findings_rules_and_location(self):
        client = FakeClient(RULES, locate_line=11)
        rv = reviewer(client)
        results = rv.review(parse(SIMPLE_DIFF))
        db = next(r for r in results if r.unit.path == "app/db.py")
        by = {f.id: f for f in db.findings}
        self.assertEqual(by["sql_concat"].status, "red")
        self.assertEqual(by["debug_print"].status, "red")
        self.assertEqual(by["sql_without_placeholder"].kind, "rule")
        self.assertEqual(by["sql_without_placeholder"].status, "red")   # min(0.95, 1 - 0.05)
        self.assertEqual(db.status, "red")
        self.assertEqual(db.location.line, 11)
        # builds_sql / uses_placeholder are building blocks only
        self.assertEqual({f.id for f in db.flagged()}, {"sql_concat", "debug_print", "sql_without_placeholder"})
        # one call for the questions + one locate call
        self.assertEqual(sum(1 for s, q in client.calls if s["file"] == "app/db.py"), 2)

    def test_prose_gate(self):
        client = FakeClient(RULES, is_code=0.1)
        results = reviewer(client).review(parse(SIMPLE_DIFF))
        md = next(r for r in results if r.unit.path == "README.md")
        by = {f.id: f for f in md.findings}
        self.assertEqual(by["sql_concat"].status, "skipped")      # target = code
        self.assertEqual(by["mentions_eval"].status, "red")       # target = any still applies
        self.assertEqual(md.status, "red")

    def test_error_is_reported_not_raised(self):
        class Broken(FakeClient):
            def ask(self, state, questions):
                from jev_review.jev import JevError
                raise JevError("HTTP 401")
        results = reviewer(Broken()).review(parse(SIMPLE_DIFF))
        self.assertTrue(all(r.error == "HTTP 401" and r.status == "skipped" for r in results))

    def test_xml_report(self):
        client = FakeClient(RULES, locate_line=12)
        rv = reviewer(client)
        results = rv.review(parse(SIMPLE_DIFF))
        root = ET.fromstring(to_xml(results, rv, {"kind": "patch", "path": "x.diff"}).split("\n", 1)[1])
        self.assertEqual(root.tag, "jev-review")
        s = root.find("summary")
        self.assertEqual((s.get("units"), s.get("red")), ("2", "2"))
        unit = root.find("./files/file[@path='app/db.py']/unit")
        self.assertEqual(unit.get("status"), "red")
        ids = [f.get("id") for f in unit.findall("finding")]
        self.assertIn("sql_concat", ids)
        self.assertNotIn("builds_sql", ids)
        self.assertEqual(unit.find("location").get("line"), "12")
        self.assertEqual(root.find("./viewpoints/rule[@id='sql_without_placeholder']/none").text, "uses_placeholder")
        text = summary_text(results, rv)
        self.assertIn("RED", text)
        self.assertIn("app/db.py:10-14", text)


if __name__ == "__main__":
    unittest.main()
