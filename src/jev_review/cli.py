"""Command line interface: jev-review run | lint | eval | list."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .diff import DEFAULT_EXCLUDES, git_diff, parse
from .jev import DEFAULT_MODEL, PRICE_PER_MTOK_USD, JevClient, JevError, estimate_tokens, load_env_file, plan_calls
from .viewpoints import ViewpointError, bundled_names, load

EXIT_OK, EXIT_FINDINGS, EXIT_ERROR = 0, 1, 2


def _client(args, client):
    if client is not None:
        return client
    if args.env_file:
        load_env_file(args.env_file)
    return JevClient(os.environ.get(args.api_key_env, ""), model=args.model)


def _read_diff(args) -> tuple[str, dict]:
    if args.patch:
        text = sys.stdin.read() if args.patch == "-" else Path(args.patch).read_text(encoding="utf-8")
        return text, {"kind": "patch", "path": args.patch}
    if args.staged:
        return git_diff(staged=True), {"kind": "staged"}
    if args.target is None:
        return git_diff(), {"kind": "working-tree"}
    kind = "range" if ".." in args.target else "commit"
    return git_diff(args.target), {"kind": kind, "target": args.target}


def cmd_run(args, client=None, out=None) -> int:
    out = out or sys.stdout
    from .report import summary_text, to_xml
    from .review import Reviewer

    vset = load(args.viewpoints)
    diff_text, source = _read_diff(args)
    units = parse(diff_text, excludes=DEFAULT_EXCLUDES + args.exclude)
    if not units:
        print("jev-review: no added lines to review", file=out)
        return EXIT_OK

    if args.dry_run:
        reviewer = Reviewer(None, vset)
        total = 0
        print(f"{len(units)} units, {len(vset.viewpoints)} viewpoints, {len(vset.rules)} rules", file=out)
        for u in units:
            vps, qs = reviewer.questions_for(u)
            try:
                calls = plan_calls(u.state(), qs) if qs else []
            except JevError as e:
                print(f"  {u.path}:{u.start}-{u.end}  SKIP ({e})", file=out)
                continue
            tok = sum(estimate_tokens(u.state()) + estimate_tokens(b) for b in calls)
            total += tok
            print(f"  {u.path}:{u.start}-{u.end}  +{len(u.added)} lines  {len(vps)} viewpoints  "
                  f"{len(calls)} call(s)  ~{tok:,} tokens{'  (split)' if u.split else ''}", file=out)
        print(f"estimate: ~{total:,} input tokens, about ${total * PRICE_PER_MTOK_USD / 1e6:.4f} "
              "(plus one locate call per flagged unit)", file=out)
        return EXIT_OK

    reviewer = Reviewer(_client(args, client), vset, jobs=args.jobs, locate=not args.no_locate,
                        red=args.red, yellow=args.yellow)
    results = reviewer.review(units)
    xml = to_xml(results, reviewer, {**source, "viewpoints": " ".join(vset.sources)}, include_green=args.include_green)
    if args.output:
        Path(args.output).write_text(xml, encoding="utf-8")
        print(summary_text(results, reviewer), file=out)
        print(f"report: {args.output}", file=out)
    else:
        out.write(xml)
        print(summary_text(results, reviewer), file=sys.stderr)
    if any(r.error for r in results):
        return EXIT_ERROR
    levels = {"red": ("red",), "yellow": ("red", "yellow"), "never": ()}[args.fail_on]
    return EXIT_FINDINGS if any(r.status in levels for r in results) else EXIT_OK


def cmd_lint(args, out=None) -> int:
    out = out or sys.stdout
    from .lint import format_text, lint
    from .viewpoints import parse_text, resolve, validate

    worst = EXIT_OK
    reports = []
    for spec in args.files:
        label, text = resolve(spec)
        vs = parse_text(text, label)
        validate(vs)
        issues = lint(vs)
        reports.append({"file": label, "issues": [i.to_dict() for i in issues]})
        if args.format == "text":
            print(format_text(issues, label), file=out)
        if any(i.level == "error" for i in issues) or (args.strict and any(i.level == "warn" for i in issues)):
            worst = EXIT_FINDINGS
    if args.format == "json":
        print(json.dumps(reports, ensure_ascii=False, indent=2), file=out)
    return worst


def cmd_eval(args, client=None, out=None) -> int:
    out = out or sys.stdout
    from .evaluate import evaluate, failed, format_text, load_cases, to_json
    from .review import Reviewer

    vset = load(args.viewpoints)
    cases = load_cases(args.samples)
    if args.only:
        cases = [c for c in cases if any(c["id"].startswith(p) for p in args.only)]
    reviewer = Reviewer(_client(args, client), vset, jobs=args.jobs, locate=False, red=args.red, yellow=args.yellow)
    result = evaluate(reviewer, cases)
    print(to_json(result) if args.format == "json" else format_text(result, args.min_recall, args.max_fp), file=out)
    return EXIT_FINDINGS if failed(result, args.min_recall, args.max_fp) else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jev-review", description="Screen git diffs with TypeSafe Jev, one hunk at a time.")
    p.add_argument("--version", action="version", version=f"jev-review {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def jev_opts(sp):
        sp.add_argument("-v", "--viewpoints", action="append", required=True,
                        help=f"viewpoint file (repeatable). Bundled: {', '.join(bundled_names())}")
        sp.add_argument("--model", default=DEFAULT_MODEL, help=f"Jev model (default {DEFAULT_MODEL})")
        sp.add_argument("--api-key-env", default="TYPESAFE_API_KEY", help="environment variable holding the API key")
        sp.add_argument("--env-file", help="read KEY=VALUE lines from this file first (e.g. ~/.config/jev/.env)")
        sp.add_argument("--jobs", type=int, default=6, help="parallel requests (default 6)")
        sp.add_argument("--red", type=float, help="override the red threshold (file default 0.7)")
        sp.add_argument("--yellow", type=float, help="override the yellow threshold (file default 0.5)")

    r = sub.add_parser("run", help="review a diff and write an XML report")
    r.add_argument("target", nargs="?", help="commit, A..B or A...B (default: uncommitted changes)")
    r.add_argument("--staged", action="store_true", help="review staged changes")
    r.add_argument("--patch", help="read a unified diff from a file ('-' for stdin) instead of git")
    jev_opts(r)
    r.add_argument("-o", "--output", help="write the XML report here (default: stdout)")
    r.add_argument("--exclude", action="append", default=[], help="extra glob to skip (repeatable)")
    r.add_argument("--include-green", action="store_true", help="also list green findings in the XML")
    r.add_argument("--no-locate", action="store_true", help="skip the extra call that pinpoints the suspect line")
    r.add_argument("--fail-on", choices=["red", "yellow", "never"], default="red", help="exit 1 when this status appears")
    r.add_argument("--dry-run", action="store_true", help="show units and a token estimate without calling Jev")

    l = sub.add_parser("lint", help="check viewpoint files for known anti-patterns")
    l.add_argument("files", nargs="+")
    l.add_argument("--format", choices=["text", "json"], default="text")
    l.add_argument("--strict", action="store_true", help="exit 1 on warnings too")

    e = sub.add_parser("eval", help="measure viewpoints on labeled sample patches")
    jev_opts(e)
    e.add_argument("--samples", default="samples", help="directory with index.toml (default: samples)")
    e.add_argument("--only", action="append", help="only cases whose id starts with this prefix (repeatable)")
    e.add_argument("--format", choices=["text", "json"], default="text")
    e.add_argument("--min-recall", type=float, default=0.8)
    e.add_argument("--max-fp", type=float, default=0.1)

    sub.add_parser("list", help="list bundled viewpoint files")
    return p


def main(argv: list[str] | None = None, client=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return cmd_run(args, client)
        if args.command == "lint":
            return cmd_lint(args)
        if args.command == "eval":
            return cmd_eval(args, client)
        if args.command == "list":
            print("\n".join(bundled_names()), file=sys.stdout)
            return EXIT_OK
    except (ViewpointError, JevError, RuntimeError, FileNotFoundError) as e:
        print(f"jev-review: {e}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
