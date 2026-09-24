"""Viewpoint files: what to ask Jev about each hunk.

A viewpoint is one yes/no question about the added lines. Measured rules that shaped
this format (see docs/findings.md):

* One fact per question. Joining conditions with AND lowered recall from 96% (1
  condition) to 73% (4); nested AND/OR was right only 84% of the time. Asking each
  condition separately and combining them in code ([[rule]]) raised it to 97%.
* Exceptions ("ignore X") work, up to about three, and the first one works best.
* Adding more viewpoints does not hurt the others (6 -> 387 questions, detection
  stayed at 89-92%), so a file can be long.
"""
from __future__ import annotations

import fnmatch
import posixpath
import re
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SEVERITIES = ("high", "medium", "low")
TARGETS = ("code", "any")
DEFAULT_RED = 0.7
DEFAULT_YELLOW = 0.5


class ViewpointError(ValueError):
    pass


@dataclass
class Viewpoint:
    id: str
    question: str
    exceptions: list[str] = field(default_factory=list)
    severity: str = "medium"
    target: str = "code"          # "code": skipped on prose hunks (Markdown etc.)
    files: list[str] = field(default_factory=list)
    report: bool = True           # False: building block for [[rule]] only
    source: str = ""

    def instructions(self) -> str:
        return " ".join([self.question.strip()] + [e.strip() for e in self.exceptions])

    def applies_to(self, path: str) -> bool:
        if not self.files:
            return True
        base = posixpath.basename(path)
        return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(base, g) for g in self.files)


@dataclass
class Rule:
    """A compound check computed in code from viewpoint probabilities.

    p = min( min(p[all]), max(p[any]), 1 - max(p[none]) ) over the parts that are set.
    """
    id: str
    all: list[str] = field(default_factory=list)
    any: list[str] = field(default_factory=list)
    none: list[str] = field(default_factory=list)
    severity: str = "medium"
    message: str = ""
    source: str = ""

    def refs(self) -> list[str]:
        return self.all + self.any + self.none

    def describe(self) -> str:
        return self.message or self.id


@dataclass
class ViewpointSet:
    name: str = ""
    language: str = "en"
    red: float = DEFAULT_RED
    yellow: float = DEFAULT_YELLOW
    viewpoints: list[Viewpoint] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def get(self, vid: str) -> Viewpoint | None:
        return next((v for v in self.viewpoints if v.id == vid), None)


def bundled_names() -> list[str]:
    root = resources.files("jev_review") / "data" / "viewpoints"
    return sorted(p.name[:-5] for p in root.iterdir() if p.name.endswith(".toml"))


def resolve(spec: str) -> tuple[str, str]:
    """Return (label, toml text) for a path or a bundled name such as 'core.en'."""
    path = Path(spec)
    if path.exists():
        return str(path), path.read_text(encoding="utf-8")
    name = spec[:-5] if spec.endswith(".toml") else spec
    root = resources.files("jev_review") / "data" / "viewpoints"
    candidate = root / f"{name}.toml"
    if candidate.is_file():
        return f"bundled:{name}", candidate.read_text(encoding="utf-8")
    raise ViewpointError(f"viewpoint file not found: {spec} (bundled: {', '.join(bundled_names())})")


def _str_list(value, where: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ViewpointError(f"{where}: expected a list of strings")
    return list(value)


def parse_text(text: str, label: str = "<string>") -> ViewpointSet:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ViewpointError(f"{label}: invalid TOML: {e}") from e
    review = data.get("review", {})
    vs = ViewpointSet(
        name=str(review.get("name", Path(label).stem)),
        language=str(review.get("language", "en")),
        red=float(review.get("red", DEFAULT_RED)),
        yellow=float(review.get("yellow", DEFAULT_YELLOW)),
        sources=[label],
    )
    for i, raw in enumerate(data.get("viewpoint", [])):
        where = f"{label}: viewpoint #{i + 1}"
        if not isinstance(raw, dict):
            raise ViewpointError(f"{where}: expected a table")
        vid = raw.get("id")
        if not isinstance(vid, str) or not ID_RE.match(vid):
            raise ViewpointError(f"{where}: 'id' must match {ID_RE.pattern}")
        where = f"{label}: viewpoint '{vid}'"
        q = raw.get("question")
        if not isinstance(q, str) or not q.strip():
            raise ViewpointError(f"{where}: 'question' is required")
        sev = raw.get("severity", "medium")
        if sev not in SEVERITIES:
            raise ViewpointError(f"{where}: 'severity' must be one of {SEVERITIES}")
        tgt = raw.get("target", "code")
        if tgt not in TARGETS:
            raise ViewpointError(f"{where}: 'target' must be one of {TARGETS}")
        unknown = set(raw) - {"id", "question", "exceptions", "severity", "target", "files", "report"}
        if unknown:
            raise ViewpointError(f"{where}: unknown keys {sorted(unknown)}")
        vs.viewpoints.append(Viewpoint(
            id=vid, question=q, exceptions=_str_list(raw.get("exceptions"), where + ".exceptions"),
            severity=sev, target=tgt, files=_str_list(raw.get("files"), where + ".files"),
            report=bool(raw.get("report", True)), source=label,
        ))
    for i, raw in enumerate(data.get("rule", [])):
        rid = raw.get("id") if isinstance(raw, dict) else None
        if not isinstance(rid, str) or not ID_RE.match(rid):
            raise ViewpointError(f"{label}: rule #{i + 1}: 'id' must match {ID_RE.pattern}")
        where = f"{label}: rule '{rid}'"
        sev = raw.get("severity", "medium")
        if sev not in SEVERITIES:
            raise ViewpointError(f"{where}: 'severity' must be one of {SEVERITIES}")
        unknown = set(raw) - {"id", "all", "any", "none", "severity", "message"}
        if unknown:
            raise ViewpointError(f"{where}: unknown keys {sorted(unknown)}")
        rule = Rule(id=rid, all=_str_list(raw.get("all"), where), any=_str_list(raw.get("any"), where),
                    none=_str_list(raw.get("none"), where), severity=sev,
                    message=str(raw.get("message", "")), source=label)
        if not rule.all and not rule.any:
            raise ViewpointError(f"{where}: needs 'all' or 'any'")
        vs.rules.append(rule)
    return vs


def load(specs: list[str]) -> ViewpointSet:
    """Load and merge one or more viewpoint files. Settings come from the first file."""
    if not specs:
        raise ViewpointError("no viewpoint file given (try: -v core.en)")
    merged: ViewpointSet | None = None
    for spec in specs:
        label, text = resolve(spec)
        vs = parse_text(text, label)
        if merged is None:
            merged = vs
            continue
        merged.viewpoints += vs.viewpoints
        merged.rules += vs.rules
        merged.sources += vs.sources
    validate(merged)
    return merged


def validate(vs: ViewpointSet) -> None:
    seen: set[str] = set()
    for item in [*vs.viewpoints, *vs.rules]:
        if item.id in seen:
            raise ViewpointError(f"duplicate id '{item.id}'")
        seen.add(item.id)
    ids = {v.id for v in vs.viewpoints}
    for r in vs.rules:
        missing = [x for x in r.refs() if x not in ids]
        if missing:
            raise ViewpointError(f"rule '{r.id}' refers to unknown viewpoints {missing}")
    if not (0 < vs.yellow <= vs.red <= 1):
        raise ViewpointError(f"thresholds must satisfy 0 < yellow <= red <= 1 (got yellow={vs.yellow}, red={vs.red})")
    if not vs.viewpoints:
        raise ViewpointError("no [[viewpoint]] defined")
