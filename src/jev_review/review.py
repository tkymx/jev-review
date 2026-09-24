"""Ask Jev about each unit and turn probabilities into red / yellow / green."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .diff import MAX_ADDED_LINES, Unit
from .jev import JevError, plan_calls
from .viewpoints import Viewpoint, ViewpointSet

# Below this, a hunk is treated as prose (Markdown, notes) and code-only viewpoints are skipped.
# Without the gate, documentation hunks were flagged as "obvious bugs".
CODE_GATE = 0.5

BUILTIN = {
    "ja": {
        "is_code": "この差分の追加行は、実行されるコードや設定（スクリプト、ソースコード、CI・Docker・設定ファイル）か。"
                   "Markdown などの文章・記録・表なら no。",
        "locate": "追加行のうち、次の指摘の主な原因になっている行はどれか: {items}",
    },
    "en": {
        "is_code": "Are the added lines executable code or configuration (scripts, source code, CI, Docker or config files)? "
                   "Answer no for prose such as Markdown documents, notes or tables.",
        "locate": "Which added line is the main cause of the following finding(s): {items}",
    },
}
STATUS_ORDER = {"red": 0, "yellow": 1, "green": 2, "skipped": 3}


def status_of(p: float, red: float, yellow: float) -> str:
    return "red" if p >= red else ("yellow" if p >= yellow else "green")


@dataclass
class Finding:
    id: str
    kind: str            # "viewpoint" or "rule"
    p: float
    status: str
    severity: str
    report: bool = True


@dataclass
class Location:
    line: int
    text: str
    p: float | None


@dataclass
class UnitResult:
    unit: Unit
    findings: list[Finding] = field(default_factory=list)
    is_code: float | None = None
    status: str = "green"
    location: Location | None = None
    error: str | None = None

    def flagged(self) -> list[Finding]:
        return [f for f in self.findings if f.report and f.status in ("red", "yellow")]


@dataclass
class Stats:
    calls: int = 0
    input_tokens: int = 0
    model: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, resp: dict) -> None:
        with self.lock:
            self.calls += 1
            self.input_tokens += int(resp.get("usage", {}).get("input_tokens", 0))
            self.model = self.model or resp.get("model")


def _noul(text: str) -> dict:
    return {"type": "noul", "instructions": text}


class Reviewer:
    def __init__(self, client, vset: ViewpointSet, jobs: int = 6, locate: bool = True,
                 red: float | None = None, yellow: float | None = None):
        self.client, self.vset, self.jobs, self.locate = client, vset, jobs, locate
        self.red = vset.red if red is None else red
        self.yellow = vset.yellow if yellow is None else yellow
        self.text = BUILTIN.get(vset.language, BUILTIN["en"])
        self.stats = Stats()

    def questions_for(self, unit: Unit) -> tuple[list[Viewpoint], dict]:
        vps = [v for v in self.vset.viewpoints if v.applies_to(unit.path)]
        qs = {v.id: _noul(v.instructions()) for v in vps}
        if any(v.target == "code" for v in vps):
            qs["__is_code"] = _noul(self.text["is_code"])
        return vps, qs

    def review(self, units: list[Unit]) -> list[UnitResult]:
        with ThreadPoolExecutor(max(1, self.jobs)) as ex:
            return list(ex.map(self.review_unit, units))

    def review_unit(self, unit: Unit) -> UnitResult:
        res = UnitResult(unit)
        vps, qs = self.questions_for(unit)
        if not vps:
            res.status = "skipped"
            return res
        state = unit.state()
        answers: dict = {}
        try:
            for batch in plan_calls(state, qs):
                resp = self.client.ask(state, batch)
                self.stats.add(resp)
                answers.update(resp["answers"])
        except (JevError, KeyError) as e:
            res.status, res.error = "skipped", str(e)
            return res

        res.is_code = answers["__is_code"]["noul"] if "__is_code" in answers else None
        prose = res.is_code is not None and res.is_code < CODE_GATE
        for v in vps:
            p = float(answers[v.id]["noul"])
            st = "skipped" if (v.target == "code" and prose) else status_of(p, self.red, self.yellow)
            res.findings.append(Finding(v.id, "viewpoint", p, st, v.severity, v.report))

        live = {f.id: f.p for f in res.findings if f.status != "skipped"}
        for rule in self.vset.rules:
            if not all(r in live for r in rule.refs()):
                continue
            parts = []
            if rule.all:
                parts.append(min(live[x] for x in rule.all))
            if rule.any:
                parts.append(max(live[x] for x in rule.any))
            if rule.none:
                parts.append(1 - max(live[x] for x in rule.none))
            p = min(parts)
            res.findings.append(Finding(rule.id, "rule", p, status_of(p, self.red, self.yellow), rule.severity))

        reported = [f for f in res.findings if f.report]
        statuses = [f.status for f in reported if f.status != "skipped"]
        res.status = min(statuses, key=STATUS_ORDER.get) if statuses else "skipped"
        if self.locate and res.status in ("red", "yellow"):
            res.location = self._locate(unit, state, res)
        return res

    def _locate(self, unit: Unit, state: dict, res: UnitResult) -> Location | None:
        added = [l for l in unit.added if l.new_no is not None]
        if len(added) == 1:
            return Location(added[0].new_no, added[0].text, None)
        if not added or len(added) > MAX_ADDED_LINES:
            return None
        items = []
        for f in res.flagged():
            if f.kind == "rule":
                rule = next(r for r in self.vset.rules if r.id == f.id)
                items.append(rule.describe())
            else:
                items.append(self.vset.get(f.id).question.strip())
        criteria = {f"L{l.new_no}": (l.text.strip()[:120] or "(blank line)") for l in added}
        q = {"__locate": {"type": "choice", "instructions": self.text["locate"].format(items=" / ".join(items)),
                          "criteria": criteria}}
        try:
            resp = self.client.ask(state, q)
        except JevError:
            return None
        self.stats.add(resp)
        ans = resp["answers"]["__locate"]
        choice = ans.get("choice")
        if not choice or not choice.startswith("L"):
            return None
        line = int(choice[1:])
        text = next((l.text for l in added if l.new_no == line), "")
        return Location(line, text, ans.get("probabilities", {}).get(choice))
