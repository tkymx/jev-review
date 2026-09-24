"""Measure a viewpoint file on labeled sample patches.

samples/index.toml:

    [[case]]
    id = "py_sql_concat"
    patch = "python/sql_concat.patch"
    expect = ["sql_injection"]     # viewpoint ids that should fire; [] for a clean patch
    note = "..."                   # optional

A viewpoint "fires" on a case when its highest p over the case's units is >= the
yellow threshold. Recall is measured on cases that expect the viewpoint; the false
positive rate on cases that do not.
"""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .diff import parse
from .review import Reviewer


@dataclass
class ViewpointScore:
    id: str
    tp: int = 0
    fn: int = 0
    fp: int = 0
    tn: int = 0
    misses: list[str] = field(default_factory=list)
    false_alarms: list[str] = field(default_factory=list)

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def fp_rate(self) -> float | None:
        return self.fp / (self.fp + self.tn) if self.fp + self.tn else None


def load_cases(samples_dir: str) -> list[dict]:
    root = Path(samples_dir)
    data = tomllib.loads((root / "index.toml").read_text(encoding="utf-8"))
    cases = []
    for c in data.get("case", []):
        c = dict(c)
        c["diff"] = (root / c["patch"]).read_text(encoding="utf-8")
        c.setdefault("expect", [])
        cases.append(c)
    return cases


def evaluate(reviewer: Reviewer, cases: list[dict]) -> dict:
    vset = reviewer.vset
    reported = [v.id for v in vset.viewpoints if v.report] + [r.id for r in vset.rules]
    scores = {vid: ViewpointScore(vid) for vid in reported}
    per_case = []
    for case in cases:
        units = parse(case["diff"])
        results = reviewer.review(units)
        best: dict[str, float] = {}
        for res in results:
            for f in res.findings:
                if f.status != "skipped":
                    best[f.id] = max(best.get(f.id, 0.0), f.p)
        fired = {vid for vid, p in best.items() if p >= reviewer.yellow and vid in scores}
        expect = [e for e in case["expect"] if e in scores]
        for vid, s in scores.items():
            if vid in expect:
                if vid in fired:
                    s.tp += 1
                else:
                    s.fn += 1
                    s.misses.append(f"{case['id']} (p={best.get(vid, 0):.2f})")
            elif vid in fired:
                s.fp += 1
                s.false_alarms.append(f"{case['id']} (p={best[vid]:.2f})")
            else:
                s.tn += 1
        per_case.append({"id": case["id"], "expect": expect, "fired": sorted(fired),
                         "ok": set(expect) == fired, "unknown_expect": [e for e in case["expect"] if e not in scores]})
    tp = sum(s.tp for s in scores.values()); fn = sum(s.fn for s in scores.values())
    fp = sum(s.fp for s in scores.values()); tn = sum(s.tn for s in scores.values())
    return {
        "cases": len(cases),
        "exact": sum(1 for c in per_case if c["ok"]),
        "recall": tp / (tp + fn) if tp + fn else None,
        "fp_rate": fp / (fp + tn) if fp + tn else None,
        "viewpoints": scores,
        "per_case": per_case,
        "calls": reviewer.stats.calls,
        "input_tokens": reviewer.stats.input_tokens,
    }


def _pct(x: float | None) -> str:
    return "  -  " if x is None else f"{x * 100:4.0f}%"


def format_text(result: dict, min_recall: float, max_fp: float) -> str:
    out = [f"{result['cases']} cases, {result['exact']} judged exactly right. "
           f"Overall recall {_pct(result['recall'])}, false positive rate {_pct(result['fp_rate'])} "
           f"({result['calls']} calls, {result['input_tokens']:,} input tokens)",
           "", f"  {'viewpoint':28s} recall  false-pos  verdict"]
    for s in result["viewpoints"].values():
        bad = (s.recall is not None and s.recall < min_recall) or (s.fp_rate is not None and s.fp_rate > max_fp)
        out.append(f"  {s.id:28s} {_pct(s.recall)}  {_pct(s.fp_rate)}     {'NG' if bad else 'ok'}"
                   f"   n={s.tp + s.fn}/{s.fp + s.tn}")
        for m in s.misses:
            out.append(f"      missed:      {m}")
        for m in s.false_alarms:
            out.append(f"      false alarm: {m}")
    return "\n".join(out)


def to_json(result: dict) -> str:
    def enc(o):
        if isinstance(o, ViewpointScore):
            return {"id": o.id, "recall": o.recall, "fp_rate": o.fp_rate, "tp": o.tp, "fn": o.fn, "fp": o.fp,
                    "tn": o.tn, "misses": o.misses, "false_alarms": o.false_alarms}
        raise TypeError(type(o))
    data = dict(result)
    data["viewpoints"] = list(result["viewpoints"].values())
    return json.dumps(data, default=enc, ensure_ascii=False, indent=2)


def failed(result: dict, min_recall: float, max_fp: float) -> bool:
    return any((s.recall is not None and s.recall < min_recall) or (s.fp_rate is not None and s.fp_rate > max_fp)
               for s in result["viewpoints"].values())
