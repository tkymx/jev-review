# jev-review

Screen a git diff with [TypeSafe Jev](https://docs.typesafe.ai/introduction), one hunk at a time, against a file of review viewpoints, and get an XML report of what looks wrong and on which line.

[日本語の README](README.ja.md)

```text
$ jev-review run HEAD -v core.en -o report.xml
jev-review: 5 units in 5 files - red 3, yellow 0, green 1, skipped 1 (7 calls, 6,890 input tokens, about $0.0003)
  RED    api/users.py:40-43  sql_injection 0.98  -> line 41: q = "SELECT * FROM users WHERE name = '" + name + "'"
  RED    service/order.py:40-43  debug_leftover 0.99  -> line 41: print("DEBUG order payload:", order.raw)
  RED    web/view.js:40-41  html_injection 0.97  -> line 41: box.innerHTML = new URLSearchParams(location.search).get("q");
report: report.xml
```

## Why

Asking an LLM to review every change in full is slow and expensive. Jev does not write text. It returns a yes-probability for each question, in about 0.3 seconds, for well under a cent. That makes it a good first pass: it narrows a change down to the hunks and lines worth a human's or an LLM's attention.

Jev is only as good as the questions it gets, though. Before writing this tool we measured it on labeled code (2,578 calls, 72 cases in 10 languages and formats). The short version:

| What we changed | What happened |
|---|---|
| Asking about one visible fact | 99% correct |
| Adding more viewpoints (6 → 387) | Detection stayed at 89–92%; latency stayed at 0.3–0.4 s |
| Joining conditions with AND (1 → 4) | Recall fell from 96% to 73%. Asking one condition at a time and combining in code: 97% |
| Asking "is X missing?" | Fired on 77% of clean diffs, against 3% for "is there X?" |
| Not naming the kind you want (XSS under "dangerous calls") | 0.04. Naming it (innerHTML): 0.94 |
| Asking abstractly ("any security issue?") | Also fired on defects of other kinds 35–76% of the time |
| Padding the hunk with 2k–28k unrelated tokens | Detection fell from 92% to 86–89% |
| Scores between 0.5 and 0.7 | Right about half the time; 0.9 and above, 97% |

jev-review turns those results into defaults: one hunk per call, all viewpoints in that one call, red at 0.7 and yellow at 0.5, prose hunks skipped for code checks, compound checks computed in code, and a linter that flags viewpoints written in the ways that failed. The full write-up is in [docs/findings.md](docs/findings.md).

## Install

Python 3.11 or later. No dependencies.

```bash
pipx install git+https://github.com/tkymx/jev-review
# or, from a clone
pip install -e .
```

You need a TypeSafe API key (<https://console.typesafe.ai/>) in `TYPESAFE_API_KEY`, or in a file you pass with `--env-file`.

## Quick start

```bash
# See how the sample diff would be split and what it would cost. No API key needed.
jev-review run --patch examples/sample.patch -v core.en --dry-run

# Review it for real
export TYPESAFE_API_KEY=...
jev-review run --patch examples/sample.patch -v core.en -o report.xml

# Your own repository
jev-review run -v core.en                      # uncommitted changes
jev-review run --staged -v core.en             # staged changes
jev-review run HEAD -v core.en                 # the last commit
jev-review run origin/main...HEAD -v core.en   # a branch or pull request
```

Exit codes: `0` nothing at the `--fail-on` level (default `red`), `1` findings at that level, `2` an error. Use `--fail-on yellow` or `--fail-on never` to change it.

A GitHub Actions example is in [examples/github-actions/jev-review.yml](examples/github-actions/jev-review.yml).

## What it does

1. **Splits the diff into units.** One unit is one hunk of one file. Hunks with more than 60 added lines are cut at a function or blank-line boundary. Lock files, images and minified files are skipped.
2. **Asks every viewpoint about each unit in one call.** More questions in the same call did not hurt the others; splitting them only raised the cost.
3. **Skips code checks on prose.** A built-in question decides whether the added lines are code. Markdown and notes are not judged by `target = "code"` viewpoints.
4. **Scores each finding.** `p >= 0.7` is red, `p >= 0.5` is yellow.
5. **Computes compound rules in code.** `[[rule]]` combines viewpoints with `all`, `any` and `none`.
6. **Points at the line.** For red or yellow units, one extra call asks which added line is the cause.
7. **Writes an XML report.** See [examples/report.sample.xml](examples/report.sample.xml).

What Jev sees for each unit is the file path, the line range, the enclosing function from the hunk header, and the hunk itself. **The diff content is sent to TypeSafe's API.** Do not run it on code you are not allowed to send there.

## Viewpoint files

A viewpoint is one yes/no question about the added lines, written in TOML:

```toml
[review]
language = "en"      # language of the built-in questions (en or ja)
red = 0.7
yellow = 0.5

[[viewpoint]]
id = "html_injection"
severity = "high"
question = "Does an added line insert an external value into the page HTML through innerHTML, outerHTML, insertAdjacentHTML, document.write, dangerouslySetInnerHTML or v-html?"

[[viewpoint]]
id = "debug_leftover"
severity = "low"
question = "Does an added line contain debug output labeled DEBUG (print, console.log, NSLog, fmt.Println, puts)?"
exceptions = ["Ignore test code (files under tests/ or named test_*)."]
files = ["*.py", "*.js", "*.ts", "*.swift", "*.go"]
```

Compound checks go in `[[rule]]`, built from viewpoints marked `report = false`. See [examples/viewpoints/compound.ja.toml](examples/viewpoints/compound.ja.toml) and the full format in [docs/viewpoint-format.md](docs/viewpoint-format.md).

### Bundled viewpoints

`-v core.en` and `-v core.ja` hold the same 15 checks in English and Japanese:

| Area | Viewpoints |
|---|---|
| Secrets | `hardcoded_secret` |
| Injection | `sql_injection`, `shell_injection`, `code_eval`, `html_injection`, `remote_script`, `unsafe_delete` |
| Error handling | `swallowed_error` |
| Leftovers | `debug_leftover` |
| Cost | `paid_api_without_guard` |
| Named bug shapes | `loop_off_by_one`, `assignment_in_condition`, `null_equality`, `unbounded_wait_loop`, `unclosed_resource` |

On the 61 labeled samples in [samples/](samples/), both files judged all 61 correctly at the red threshold. With yellow counted as a hit, recall stayed at 100%, and false positives were 0.2% (English) and 0.5% (Japanese), all between 0.51 and 0.67. **These samples come from the same experiments the viewpoints were written against, so treat the numbers as an upper bound.** Measure on your own code with `jev-review eval`.

Bugs you can only see by knowing the intent, such as an inverted comparison or a missing None check, are not in the core set. Jev did not catch them reliably.

## Writing good viewpoints

`jev-review lint` checks a viewpoint file for the wordings that failed in the experiments and explains why:

```bash
jev-review lint my-viewpoints.toml
jev-review lint examples/viewpoints/anti-patterns.en.toml   # every anti-pattern at once
```

| Code | Anti-pattern | Measured effect |
|---|---|---|
| JR001 | "Is X missing?" | Fired on 77% of clean diffs |
| JR002 | Conditions joined with AND | Recall 96% → 73% from 1 to 4 conditions |
| JR003 | Nested AND/OR | 84% correct; 97% when split into a `[[rule]]` |
| JR004 | Abstract ("any security issue?") | Fired on other kinds of defects 35–76% of the time |
| JR005 | Subjective ("readable?") | Ranks a before/after pair well; as pass/fail, 54–75% |
| JR006 | Verdict ("safe to merge?") | Never passed a defect; stopped 47% of clean changes |
| JR007 | Logic or intent | p = 0.65 on average; inverted comparisons missed |
| JR008 | Category with examples | Only the listed kinds are found |
| JR009 | More than three exceptions | The last exception loses effect |

The full list, with rewrites, is in [docs/anti-patterns.md](docs/anti-patterns.md).

To measure a file instead of reading it, run it on labeled patches:

```bash
jev-review eval -v my-viewpoints.toml --samples samples
```

It reports recall and false positive rate per viewpoint and exits `1` if a viewpoint is below `--min-recall` (default 0.8) or above `--max-fp` (default 0.1). The sample format is described in [samples/README.md](samples/README.md).

### Claude Code skill: audit-viewpoints

The repository ships a [Claude Code](https://claude.com/claude-code) skill, [`.claude/skills/audit-viewpoints`](.claude/skills/audit-viewpoints/SKILL.md). Open this repository in Claude Code and ask it to audit a viewpoint file. It runs the linter, judges the cases a regex cannot (for example an exception scoped too broadly), proposes rewrites, and can measure the result with `eval`. To use it in another project, copy the folder into that project's `.claude/skills/` or into `~/.claude/skills/`.

## Limits

- Jev answers from the hunk alone. It cannot tell whether a check lives in another file.
- It does not understand intent. Use it to narrow down, and leave the final call to a person or an LLM that can read the surrounding code.
- Thresholds were measured on `jev-1.13.0`, which is pinned by default (`--model`). Re-run `eval` when you change the model.
- Cost: input tokens only, $0.042 per million at the time of writing. The sample review above cost $0.0003.

## Development

```bash
PYTHONPATH=src:tests python -m unittest discover -s tests
```

The tests use a fake client and need no API key.

## License

MIT
