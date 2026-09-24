"""XML report and console summary."""
from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict

from . import __version__
from .jev import PRICE_PER_MTOK_USD
from .review import STATUS_ORDER, Reviewer, UnitResult


def _f(x: float | None) -> str:
    return "" if x is None else f"{x:.3f}"


def to_xml(results: list[UnitResult], reviewer: Reviewer, source: dict, include_green: bool = False) -> str:
    vset, stats = reviewer.vset, reviewer.stats
    counts = Counter(r.status for r in results)
    root = ET.Element("jev-review", {
        "version": "1", "tool": f"jev-review {__version__}",
        "model": stats.model or getattr(reviewer.client, "model", "") or "",
        "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
    })
    ET.SubElement(root, "source", {k: str(v) for k, v in source.items() if v is not None})
    ET.SubElement(root, "thresholds", {"red": str(reviewer.red), "yellow": str(reviewer.yellow)})
    ET.SubElement(root, "summary", {
        "units": str(len(results)), "files": str(len({r.unit.path for r in results})),
        "red": str(counts["red"]), "yellow": str(counts["yellow"]),
        "green": str(counts["green"]), "skipped": str(counts["skipped"]),
        "errors": str(sum(1 for r in results if r.error)),
        "calls": str(stats.calls), "input-tokens": str(stats.input_tokens),
        "cost-usd": f"{stats.input_tokens * PRICE_PER_MTOK_USD / 1e6:.6f}",
    })

    vps = ET.SubElement(root, "viewpoints", {"sources": " ".join(vset.sources)})
    for v in vset.viewpoints:
        el = ET.SubElement(vps, "viewpoint", {"id": v.id, "severity": v.severity, "target": v.target,
                                              "report": str(v.report).lower()})
        ET.SubElement(el, "question").text = v.question.strip()
        for e in v.exceptions:
            ET.SubElement(el, "exception").text = e.strip()
        for g in v.files:
            ET.SubElement(el, "files").text = g
    for r in vset.rules:
        el = ET.SubElement(vps, "rule", {"id": r.id, "severity": r.severity})
        for kind in ("all", "any", "none"):
            for ref in getattr(r, kind):
                ET.SubElement(el, kind).text = ref
        if r.message:
            ET.SubElement(el, "message").text = r.message

    by_file: "OrderedDict[str, list[UnitResult]]" = OrderedDict()
    for r in sorted(results, key=lambda r: (r.unit.path, r.unit.start)):
        by_file.setdefault(r.unit.path, []).append(r)
    files_el = ET.SubElement(root, "files")
    for path, rs in by_file.items():
        worst = min((r.status for r in rs), key=STATUS_ORDER.get)
        f_el = ET.SubElement(files_el, "file", {"path": path, "status": worst})
        for r in rs:
            attrs = {"start": str(r.unit.start), "end": str(r.unit.end), "status": r.status,
                     "added-lines": str(len(r.unit.added))}
            if r.unit.enclosing:
                attrs["enclosing"] = r.unit.enclosing
            if r.is_code is not None:
                attrs["is-code"] = _f(r.is_code)
            if r.unit.split:
                attrs["split"] = "true"
            u_el = ET.SubElement(f_el, "unit", attrs)
            if r.error:
                ET.SubElement(u_el, "error").text = r.error
            for f in sorted(r.findings, key=lambda f: (STATUS_ORDER[f.status], -f.p)):
                if not f.report:
                    continue
                if f.status in ("green", "skipped") and not include_green:
                    continue
                ET.SubElement(u_el, "finding", {"id": f.id, "kind": f.kind, "status": f.status,
                                                "p": _f(f.p), "severity": f.severity})
            if r.location:
                loc = {"line": str(r.location.line)}
                if r.location.p is not None:
                    loc["p"] = _f(r.location.p)
                ET.SubElement(u_el, "location", loc).text = r.location.text
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def summary_text(results: list[UnitResult], reviewer: Reviewer) -> str:
    stats = reviewer.stats
    c = Counter(r.status for r in results)
    lines = [
        f"jev-review: {len(results)} units in {len({r.unit.path for r in results})} files - "
        f"red {c['red']}, yellow {c['yellow']}, green {c['green']}, skipped {c['skipped']} "
        f"({stats.calls} calls, {stats.input_tokens:,} input tokens, about ${stats.input_tokens * PRICE_PER_MTOK_USD / 1e6:.4f})"
    ]
    for r in sorted(results, key=lambda r: (STATUS_ORDER[r.status], r.unit.path, r.unit.start)):
        if r.error:
            lines.append(f"  ERROR  {r.unit.path}:{r.unit.start}-{r.unit.end}  {r.error}")
        if r.status not in ("red", "yellow"):
            continue
        found = ", ".join(f"{f.id} {f.p:.2f}" for f in sorted(r.flagged(), key=lambda f: -f.p))
        where = f"  -> line {r.location.line}: {r.location.text.strip()[:80]}" if r.location else ""
        lines.append(f"  {r.status.upper():6s} {r.unit.path}:{r.unit.start}-{r.unit.end}  {found}{where}")
    return "\n".join(lines)
