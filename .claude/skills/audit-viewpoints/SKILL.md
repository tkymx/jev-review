---
name: audit-viewpoints
description: Audit a jev-review viewpoint file (TOML) against the anti-patterns measured for TypeSafe Jev, propose rewrites, and optionally measure the result on labeled samples. Use when the user asks to audit, review, check or improve a viewpoint file, asks whether their Jev questions are well written, or says 「観点ファイルを監査して」「観点をチェックして」「この質問で Jev はちゃんと判定できる？」.
---

# audit-viewpoints

Check that every viewpoint in a jev-review viewpoint file is written in a way Jev answers reliably, and fix the ones that are not. The rules come from measurements on labeled code (`docs/findings.md`); cite the numbers when you explain a problem.

Reply in the user's language. Viewpoint text you write must be in the file's `[review] language`.

## Steps

1. **Find the file.** Use the path the user gave. Otherwise look for `*.toml` files containing `[[viewpoint]]`. If there are several, ask which one.

2. **Run the linter.**

   ```bash
   jev-review lint <file> --format json
   ```

   If `jev-review` is not installed, run `PYTHONPATH=src python -m jev_review lint <file> --format json` from the jev-review repository, or `pip install -e <path to jev-review>`. The linter also validates the file; if it fails with a format error, fix that first (`docs/viewpoint-format.md`).

3. **Judge every viewpoint yourself**, including the ones the linter passed. The linter reads wording with regular expressions; it misses things. For each viewpoint, go through this list:

   | Check | Problem if... | Measured effect |
   |---|---|---|
   | One fact | It asks about two or more conditions (AND, "and also", 「かつ」, a list of conditions that must all hold) | Recall 96% → 73% from 1 to 4 conditions; nested AND/OR 84%, combined in code 97% |
   | Presence | It asks whether something is missing, or its answer depends on code outside the hunk | Absence questions: 77% false positives on clean code; presence questions: 3% |
   | Named forms | It names a category and relies on "such as" / 「など」 for the rest, or misses a language's form (e.g. `|| true`, `continue-on-error: true`, `try?`, `_ = err` for swallowed errors) | XSS under "dangerous call": 0.04; named: 0.94. GitHub Actions recall 33% with unnamed forms |
   | Concrete | It asks about an area ("security issue", "any problem", 「品質」) | Fired on other kinds of problems 35–76% of the time |
   | Not subjective | It asks readable / maintainable / clean / good design | Ranks a before/after pair well, but 54–75% as pass/fail |
   | Not a verdict | It asks "safe to merge?" | Never passed a defect, but stopped 47% of clean changes |
   | Visible, not intent | It needs the author's intent (logic errors, "as intended", inverted comparisons, missing None checks) | p = 0.65 on average; inverted comparisons missed in every condition |
   | Exceptions | More than three, the important one not first, or scoped by a description of a kind instead of something visible (file path, object, function or variable name) | Last of three exceptions: 0.26 → 0.68. "Keys that are public by design" also cleared a Swift Google key (0.97 → 0.24); "the apiKey inside a JavaScript firebaseConfig object" did not (0.95) |
   | Target | A code check has `target = "any"`, or a prose check (docs, changelog wording) has the default `target = "code"` | Without the prose gate, Markdown hunks were flagged as bugs |
   | Scope | The question is language-specific but has no `files` glob | Other languages get asked a question that cannot apply |
   | Thresholds | `red` below 0.7 | p 0.5–0.7 was right about 48% of the time; 0.9+ was right 97% |

   Give each viewpoint one verdict:
   - **OK**: keep as is.
   - **Fix**: keep the intent, rewrite the wording.
   - **Split**: turn it into several viewpoints with `report = false` plus a `[[rule]]` (`all` / `any` / `none`).
   - **Move out of Jev**: Jev cannot answer it reliably from a hunk (absence that needs context, intent, subjective quality, verdicts). Say who should check it instead: a person, an LLM with the surrounding code, a linter, or a type checker.

4. **Write the rewrites.** Follow the rules:
   - One visible fact per viewpoint, ending as a yes/no question (「〜か。」 / "?").
   - Ask for the presence of the bad pattern: "Does an added line call X without Y?" is fine; "Is Y missing?" is not.
   - Name each form, per language, instead of "such as" / 「など」.
   - At most three exceptions, most important first, each anchored to something visible.
   - Keep `id` values stable where the intent does not change, so reports stay comparable.

5. **Show the result** as a table: id, verdict, reason (with the measured effect), proposed text. Then show the full rewritten TOML. Ask before overwriting the user's file; if they agree, write it and run `jev-review lint` again until it reports no errors or warnings.

6. **Measure, if possible.** When `TYPESAFE_API_KEY` is set (or the user points to an env file) and labeled samples exist, run the old and new files and compare:

   ```bash
   jev-review eval -v <old file> --samples <samples dir>
   jev-review eval -v <new file> --samples <samples dir>
   ```

   The bundled `samples/` only fit the ids of `core.en` / `core.ja`. For custom viewpoints, offer to build a small samples folder from the user's own history (`git show <commit> > case.patch`, one `[[case]]` per patch with the ids that should fire, plus a few clean changes). Target per viewpoint: recall at least 80%, false positive rate at most 10%. Each call costs a fraction of a cent; tell the user the number of cases before running.

## Output format

```text
<file>: <n> viewpoints — OK <a> / Fix <b> / Split <c> / Move out <d>

| id | verdict | why | proposed |
|---|---|---|---|
| missing_timeout | Move out | Absence question: 77% false positives on clean diffs | Check with a linter rule (requests without timeout=) or ask an LLM with the call site |
| sql_and_input | Split | Three conditions with AND: recall drops to 81% | builds_sql / concatenates_value / uses_external_value + [[rule]] all |
...

<rewritten TOML>
```

Keep explanations short: one sentence of reason and the number that backs it.
