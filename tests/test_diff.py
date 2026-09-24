import unittest

from jev_review.diff import Unit, Line, parse, split_unit
from helpers import SIMPLE_DIFF


class ParseTest(unittest.TestCase):
    def test_units_and_line_numbers(self):
        units = parse(SIMPLE_DIFF)
        self.assertEqual([u.path for u in units], ["app/db.py", "README.md"])  # lockfile excluded
        db = units[0]
        self.assertEqual(db.enclosing, "def find_user(name):")
        self.assertEqual([l.new_no for l in db.added], [11, 12, 13])
        self.assertEqual((db.start, db.end), (10, 14))
        self.assertIn('+    print("DEBUG", q)', db.text())
        self.assertIn("-    q = ", db.text())

    def test_deletion_only_hunk_is_dropped(self):
        diff = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,1 @@\n keep\n-gone\n"
        self.assertEqual(parse(diff), [])

    def test_deleted_file_and_binary_are_skipped(self):
        diff = ("diff --git a/old.py b/old.py\ndeleted file mode 100644\n--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
                "diff --git a/img.png b/img.png\nBinary files a/img.png and b/img.png differ\n")
        self.assertEqual(parse(diff), [])

    def test_line_starting_with_dashes_inside_hunk(self):
        diff = "diff --git a/a.sql b/a.sql\n--- a/a.sql\n+++ b/a.sql\n@@ -1,1 +1,2 @@\n--- comment\n+++ added\n"
        units = parse(diff)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].added[0].text, "++ added")

    def test_no_newline_marker_ignored(self):
        diff = "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1,1 +1,1 @@\n-x\n\\ No newline at end of file\n+y\n"
        self.assertEqual([l.text for l in parse(diff)[0].added], ["y"])

    def test_extra_excludes(self):
        self.assertEqual([u.path for u in parse(SIMPLE_DIFF, excludes=["*.md"])], ["app/db.py", "yarn.lock"])


class SplitTest(unittest.TestCase):
    def test_split_prefers_boundary_and_keeps_all_lines(self):
        lines = []
        n = 1
        for block in range(3):
            lines.append(Line("+", f"def f{block}():", n)); n += 1
            for i in range(29):
                lines.append(Line("+", f"    x{i} = {i}", n)); n += 1
            lines.append(Line("+", "", n)); n += 1
        unit = Unit("big.py", "", lines)
        pieces = split_unit(unit, max_added=60)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(p.split for p in pieces))
        self.assertTrue(all(len(p.added) <= 60 for p in pieces))
        self.assertEqual(sum(len(p.lines) for p in pieces), len(lines))
        self.assertTrue(pieces[1].lines[0].text in ("", "def f1():", "def f2():"))

    def test_small_unit_untouched(self):
        u = Unit("a.py", "", [Line("+", "x", 1)])
        self.assertEqual(split_unit(u), [u])


if __name__ == "__main__":
    unittest.main()
