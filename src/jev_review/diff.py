"""Turn a unified diff into review units.

A unit is one hunk of one file. Measurements showed that Jev answers best when it
sees one hunk at a time: padding the hunk with unrelated text lowered detection
from 92% to 86-89%, and burying it in the middle of a long input lowered it to 83%.
Hunks with more than MAX_ADDED_LINES added lines are split, preferring a function
or blank-line boundary so each piece keeps some context.
"""
from __future__ import annotations

import fnmatch
import posixpath
import re
import subprocess
from dataclasses import dataclass, field

MAX_ADDED_LINES = 60

DEFAULT_EXCLUDES = [
    "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Gemfile.lock", "Podfile.lock",
    "Cargo.lock", "poetry.lock", "go.sum", "*.min.js", "*.min.css", "*.map", "*.svg",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.ico", "*.pdf", "*.zip", "*.gz",
    "*.mp3", "*.mp4", "*.mov", "*.wav", "*.woff", "*.woff2", "*.ttf", "*.otf",
]

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
# Lines where it is reasonable to cut a long hunk (a new block starts here).
_BOUNDARY_RE = re.compile(
    r"^\s*($|def |async def |class |func |function |fn |export |public |private |protected |"
    r"static |@|#{1,6} |- name:|resource |module )"
)
# Lines that name the enclosing block, used as the "enclosing" hint for split pieces.
_DEFINITION_RE = re.compile(r"^\s*(async def |def |class |func |function |fn |export (default )?(async )?function )")


@dataclass
class Line:
    kind: str            # "+", "-" or " "
    text: str
    new_no: int | None   # line number in the new file; None for deleted lines


@dataclass
class Unit:
    path: str
    enclosing: str
    lines: list[Line] = field(default_factory=list)
    split: bool = False

    @property
    def added(self) -> list[Line]:
        return [l for l in self.lines if l.kind == "+"]

    @property
    def start(self) -> int:
        nums = [l.new_no for l in self.lines if l.new_no is not None]
        return nums[0] if nums else 0

    @property
    def end(self) -> int:
        nums = [l.new_no for l in self.lines if l.new_no is not None]
        return nums[-1] if nums else 0

    def text(self) -> str:
        return "\n".join(l.kind + l.text for l in self.lines)

    def state(self) -> dict:
        """What Jev sees for this unit."""
        return {
            "file": self.path,
            "lines": f"{self.start}-{self.end}",
            "enclosing": self.enclosing,
            "diff": self.text(),
        }


def is_excluded(path: str, patterns: list[str]) -> bool:
    base = posixpath.basename(path)
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(base, p) for p in patterns)


def parse(diff_text: str, excludes: list[str] | None = None, max_added: int = MAX_ADDED_LINES) -> list[Unit]:
    """Parse a unified diff (git diff / git show / .patch) into review units."""
    excludes = DEFAULT_EXCLUDES if excludes is None else excludes
    units: list[Unit] = []
    path: str | None = None
    skip = False
    cur: Unit | None = None
    old_left = new_left = 0
    new_no = 0

    for raw in diff_text.splitlines():
        if old_left > 0 or new_left > 0:
            if raw.startswith("\\"):          # "\ No newline at end of file"
                continue
            tag, body = (raw[:1] or " "), raw[1:]
            if tag == "+":
                cur.lines.append(Line("+", body, new_no))
                new_no += 1
                new_left -= 1
            elif tag == "-":
                cur.lines.append(Line("-", body, None))
                old_left -= 1
            else:
                cur.lines.append(Line(" ", body, new_no))
                new_no += 1
                new_left -= 1
                old_left -= 1
            continue
        if raw.startswith("diff --git "):
            path, skip, cur = None, False, None
        elif raw.startswith("+++ "):
            target = raw[4:].split("\t")[0].strip()
            if target == "/dev/null":
                path, skip = None, True
            else:
                path = target[2:] if target.startswith("b/") else target
                skip = is_excluded(path, excludes)
        elif raw.startswith("Binary files "):
            skip = True
        else:
            m = _HUNK_RE.match(raw)
            if not m:
                continue
            old_left = int(m.group(2)) if m.group(2) is not None else 1
            new_left = int(m.group(4)) if m.group(4) is not None else 1
            new_no = int(m.group(3))
            cur = Unit(path or "", m.group(5).strip())
            if path and not skip:
                units.append(cur)

    out: list[Unit] = []
    for u in units:
        if u.added:
            out.extend(split_unit(u, max_added))
    return out


def split_unit(unit: Unit, max_added: int = MAX_ADDED_LINES) -> list[Unit]:
    """Split a unit whose added lines exceed max_added, cutting at a block boundary when possible."""
    if len(unit.added) <= max_added:
        return [unit]
    pieces: list[Unit] = []
    buf: list[Line] = []
    added = 0
    enclosing = unit.enclosing
    for line in unit.lines:
        buf.append(line)
        added += line.kind == "+"
        if added < max_added:
            continue
        cut = len(buf)
        for j in range(len(buf) - 1, len(buf) // 2, -1):
            if buf[j].kind != "-" and _BOUNDARY_RE.match(buf[j].text):
                cut = j
                break
        chunk, buf = buf[:cut], buf[cut:]
        pieces.append(Unit(unit.path, enclosing, chunk, split=True))
        for l in chunk:
            if l.kind != "-" and _DEFINITION_RE.match(l.text):
                enclosing = l.text.strip()
        added = sum(1 for l in buf if l.kind == "+")
    if buf:
        if any(l.kind == "+" for l in buf) or not pieces:
            pieces.append(Unit(unit.path, enclosing, buf, split=True))
        else:
            pieces[-1].lines.extend(buf)
    return pieces


def git_diff(target: str | None = None, staged: bool = False, cwd: str | None = None) -> str:
    """Read a diff from git.

    target None      -> uncommitted changes (git diff HEAD)
    staged           -> git diff --cached
    "A..B" / "A...B" -> git diff A..B
    anything else    -> the changes of that single commit (git show)
    """
    git = ["git", "-c", "core.quotepath=off"]
    if staged:
        cmd = git + ["diff", "--no-color", "--no-ext-diff", "-U3", "--cached"]
    elif target is None:
        cmd = git + ["diff", "--no-color", "--no-ext-diff", "-U3", "HEAD"]
    elif ".." in target:
        cmd = git + ["diff", "--no-color", "--no-ext-diff", "-U3", target]
    else:
        cmd = git + ["show", "--no-color", "--no-ext-diff", "-U3", "--format=", "-m", "--first-parent", target]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"git failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout
