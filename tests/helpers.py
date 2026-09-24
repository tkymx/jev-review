"""Test helpers: a fake Jev client that answers from simple keyword rules."""
from __future__ import annotations

import re


class FakeClient:
    """Answers noul questions with p=0.95 when a keyword rule matches the diff, else 0.05.

    rules: {question_id: regex applied to the added lines}
    """
    model = "fake-jev"

    def __init__(self, rules: dict[str, str] | None = None, is_code: float = 0.95, locate_line: int | None = None):
        self.rules = rules or {}
        self.is_code = is_code
        self.locate_line = locate_line
        self.calls: list[tuple[dict, dict]] = []

    def ask(self, state, questions):
        self.calls.append((state, questions))
        added = "\n".join(l[1:] for l in state["diff"].splitlines() if l.startswith("+"))
        answers = {}
        for qid, q in questions.items():
            if qid == "__is_code":
                answers[qid] = {"noul": self.is_code}
            elif q["type"] == "choice":
                keys = list(q["criteria"])
                pick = f"L{self.locate_line}" if self.locate_line and f"L{self.locate_line}" in keys else keys[0]
                answers[qid] = {"choice": pick, "probabilities": {k: (0.8 if k == pick else 0.2 / max(1, len(keys) - 1)) for k in keys},
                                "confidence": 0.6}
            else:
                rx = self.rules.get(qid)
                answers[qid] = {"noul": 0.95 if rx and re.search(rx, added) else 0.05}
        return {"answers": answers, "usage": {"input_tokens": 100}, "model": self.model}


SIMPLE_DIFF = """diff --git a/app/db.py b/app/db.py
index 111..222 100644
--- a/app/db.py
+++ b/app/db.py
@@ -10,3 +10,5 @@ def find_user(name):
     conn = get_conn()
-    q = "SELECT * FROM users WHERE name = ?"
+    q = "SELECT * FROM users WHERE name = '" + name + "'"
+    print("DEBUG", q)
+    return conn.execute(q).fetchall()
     # end
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1,1 +1,2 @@
 # title
+Do not pass input to eval().
diff --git a/yarn.lock b/yarn.lock
--- a/yarn.lock
+++ b/yarn.lock
@@ -1,1 +1,2 @@
 a
+b
"""
