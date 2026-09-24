"""Static checks for viewpoint files, based on measured failure modes of Jev.

Every check cites the measurement behind it (docs/findings.md). The checks are
heuristics on wording; the audit-viewpoints Claude skill reviews the cases a regex
cannot judge, and `jev-review eval` measures a file on labeled samples.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .viewpoints import ViewpointSet


@dataclass
class Issue:
    level: str        # "error" | "warn" | "info"
    code: str
    target: str       # viewpoint / rule id, or "(file)"
    message: str
    hint: str
    evidence: str

    def to_dict(self) -> dict:
        return asdict(self)


def _rx(*parts: str) -> re.Pattern:
    return re.compile("|".join(parts), re.IGNORECASE)


# --- wording patterns (Japanese and English) -------------------------------------------
ABSENCE_END_JA = re.compile(r"(無い|ない|なし|無し|いない|欠けている|抜けている|漏れている|されていない|していない)か[。？?]?\s*$")
# "X があり、…が無いか" / "X を呼び出しているコードで…" : the absence is tied to something visible in the hunk.
PRESENCE_ANCHOR_JA = re.compile(r"(があり|があって|している(行|箇所|コード)(があり|で)|を呼び出(す|して|している)(行|コード|箇所)|呼んでいる(行|コード))")
ABSENCE_EN = _rx(r"\bmissing\b", r"\blacks?\b", r"\bdoes not (?:have|include|contain|set|specify)\b",
                 r"\bdoesn't (?:have|include|contain|set|specify)\b", r"\bhas no\b", r"\bhave no\b", r"\bis there no\b",
                 r"\bare there no\b", r"\bnot (?:set|specified|provided|handled)\b")
PRESENCE_ANCHOR_EN = re.compile(
    r"^\s*does (?:an |the )?added (?:line|loop|code|call|sql|if|while|step)\b[^?]*?\b"
    r"(?:call|calls|use|uses|run|runs|open|opens|contain|contains|put|puts|insert|inserts|start|starts|execute|executes)\b",
    re.IGNORECASE)

AND_JA = re.compile(r"かつ|および|と同時に|両方|さらに")
AND_EN = _rx(r"\band also\b", r"\bas well as\b", r"\bboth\b.+\band\b", r"\band at the same time\b", r"\band additionally\b")
OR_JA = re.compile(r"または|もしくは|いずれか|少なくとも")
OR_EN = _rx(r"\beither\b", r"\bor\b.*\(|\(.*\bor\b")
CIRCLED = re.compile(r"[①②③④⑤⑥⑦⑧⑨]")

ABSTRACT = _rx(r"(何らかの|なにか|何か)?問題(が|は)(ある|ない)か", r"セキュリティ(上の|的な)(問題|リスク)", r"品質(が|は|に)", r"適切(か|な)", r"妥当(か|な)",
               r"ベストプラクティス", r"リスクがあるか", r"改善(点|の余地)", r"正しく動(く|作)",
               r"\bany (?:issues?|problems?|bugs?|concerns?)\b", r"\bsecurity (?:issues?|problems?|risks?|concerns?)\b",
               r"\bbest practices?\b", r"\bappropriate\b", r"\b(?:good|code) quality\b", r"\bwell[- ]designed\b",
               r"\bany risk\b", r"\bcould be improved\b")
SUBJECTIVE = _rx(r"読みやす", r"読みにく", r"保守しやす", r"わかりやす", r"分かりやす", r"きれい", r"綺麗", r"美し", r"直感的", r"(良|よ)い設計",
                 r"\breadab(?:le|ility)\b", r"\bmaintainab(?:le|ility)\b", r"\bclean code\b", r"\belegant\b", r"\bintuitive\b",
                 r"\bwell[- ]written\b", r"\bgood design\b")
VERDICT = _rx(r"マージしてよい", r"マージして良い", r"本番に出してよい", r"リリースしてよい", r"承認してよい", r"問題ないか",
              r"\bsafe to merge\b", r"\bready to (?:merge|ship|release)\b", r"\bapprove\b", r"\blgtm\b", r"\bproduction[- ]ready\b")
SEMANTIC = _rx(r"ロジック", r"論理的", r"仕様(どおり|通り)", r"意図(どおり|通り|した)", r"正しい(か|動作)",
               r"\blogic(?:al)? (?:bug|error|flaw)s?\b", r"\bas intended\b", r"\bmatch(?:es)? the spec\b", r"\bcorrect behaviou?r\b")
CATEGORY = _rx(r"など", r"等(?!し)", r"\betc\.?", r"\bsuch as\b", r"\be\.g\.")


def _question_ok(q: str) -> bool:
    q = q.strip()
    return q.endswith(("か。", "か", "か？", "か?", "?"))


def lint(vs: ViewpointSet) -> list[Issue]:
    issues: list[Issue] = []
    seen: dict[str, str] = {}
    for v in vs.viewpoints:
        q = v.question.strip()
        add = lambda level, code, msg, hint, ev: issues.append(Issue(level, code, v.id, msg, hint, ev))

        absent_ja = ABSENCE_END_JA.search(q)
        absent_en = ABSENCE_EN.search(q)
        if absent_ja or absent_en:
            if absent_ja:
                anchored = bool(PRESENCE_ANCHOR_JA.search(q[: absent_ja.start()]))
            else:
                anchored = bool(PRESENCE_ANCHOR_EN.search(q))
            if anchored:
                add("info", "JR001", "Ends with an absence clause, but is anchored to something present in the same lines.",
                    "Prefer ending on the presence: 'is there a call to X without Y?'.",
                    "Absence questions fired on 77% of clean diffs; anchored ones (a paid API call without a budget check) held up.")
            else:
                add("warn", "JR001", "Absence question ('is X missing?'). A diff fragment rarely shows X, so this answers yes almost always.",
                    "Ask for the presence of the bad pattern instead, or leave absence checks to a reviewer with full context.",
                    "Absence questions fired on 77% of clean diffs; presence questions on 3%.")

        if (AND_JA.search(q) or AND_EN.search(q) or len(CIRCLED.findall(q)) >= 2) and (OR_JA.search(q) or OR_EN.search(q)):
            add("error", "JR003", "Nested AND/OR logic in one question.",
                "Split into one viewpoint per condition (report = false) and combine them with [[rule]] all/any/none.",
                "Nested questions were right 84% of the time; the same logic computed from single-condition answers was right 97%.")
        elif AND_JA.search(q) or AND_EN.search(q) or len(CIRCLED.findall(q)) >= 2:
            add("warn", "JR002", "Several conditions joined with AND in one question.",
                "Split into one viewpoint per condition (report = false) and combine them with [[rule]] all = [...].",
                "Recall fell from 96% (1 condition) to 90/81/73% (2/3/4 conditions).")

        if VERDICT.search(q):
            add("warn", "JR006", "Verdict question (is it OK to merge?).",
                "Use it only to skip a deep review when it says yes; do not use it to fail a change.",
                "It never passed a defective change, but it also stopped 47% of clean ones.")
        elif SUBJECTIVE.search(q):
            add("warn", "JR005", "Subjective quality question (readable, maintainable, clean).",
                "Use it only to compare a before/after pair, not as a pass/fail check.",
                "It ranked good vs bad versions correctly in 7-8 of 8 pairs, but a 0.5 cut-off was right only 54-75% of the time.")
        elif ABSTRACT.search(q):
            add("warn", "JR004", "Abstract question (any problem / security issue / appropriate).",
                "Name the concrete pattern you want to find, one per viewpoint.",
                "Area-level questions also fired on defects of other kinds 35-76% of the time.")

        if SEMANTIC.search(q):
            add("warn", "JR007", "Asks about logic or intent, which Jev cannot see from a hunk.",
                "Name a concrete, visible pattern (e.g. a loop bound written as `<= len(xs)`).",
                "Logic-bug questions averaged p=0.65; an inverted comparison was missed under every condition tested.")

        if CATEGORY.search(q):
            add("info", "JR008", "Category with examples ('such as', 'etc.').",
                "Only the kinds you name are detected. List every kind you care about, including per-language forms.",
                "An XSS hunk scored 0.04 under a generic 'dangerous call' question and 0.94 when innerHTML was named.")

        if len(v.exceptions) > 3:
            add("warn", "JR009", f"{len(v.exceptions)} exceptions.",
                "Keep at most three and put the most important one first.",
                "Three stacked exceptions still worked, but the one listed last lost effect (0.26 -> 0.68).")

        if not _question_ok(q):
            add("info", "JR010", "Does not read as a yes/no question.",
                "End with 'か。' or '?' so the answer is a clean yes/no.", "Jev returns a yes probability per question.")

        if len(q) > 400:
            add("info", "JR011", f"Long question ({len(q)} characters).",
                "Keep one fact per viewpoint; move alternatives into separate viewpoints.", "Long questions tend to hide several conditions.")

        key = re.sub(r"\s+", "", q)
        if key in seen:
            add("warn", "JR012", f"Same question as '{seen[key]}'.", "Remove the duplicate.", "")
        seen[key] = v.id

    if vs.red < 0.7:
        issues.append(Issue("info", "JR013", "(file)", f"red threshold is {vs.red}.",
                            "0.7 is the measured default; answers between 0.5 and 0.7 were right about half the time.",
                            "p>=0.9 was right 97%, 0.7-0.9 about 75%, 0.5-0.7 about 48%."))
    for r in vs.rules:
        if len(r.refs()) == 1 and not r.none:
            issues.append(Issue("info", "JR014", r.id, "Rule with a single condition.",
                                "Use the viewpoint directly instead of a rule.", ""))
    order = {"error": 0, "warn": 1, "info": 2}
    return sorted(issues, key=lambda i: (order[i.level], i.code, i.target))


def format_text(issues: list[Issue], label: str) -> str:
    out = [label]
    for i in issues:
        out.append(f"  {i.level.upper():5s} {i.code} {i.target}: {i.message}")
        out.append(f"        hint: {i.hint}")
        if i.evidence:
            out.append(f"        why:  {i.evidence}")
    n = {k: sum(1 for i in issues if i.level == k) for k in ("error", "warn", "info")}
    out.append(f"  {n['error']} errors, {n['warn']} warnings, {n['info']} notes")
    return "\n".join(out)
