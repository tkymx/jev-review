# Viewpoint anti-patterns

`jev-review lint` reports these. Each one lost accuracy in the measurements in [findings.md](findings.md). The checks work on wording, so they miss some cases and flag some harmless ones; the `audit-viewpoints` skill and `jev-review eval` cover the rest.

| Code | Level | Pattern | Measured effect | Fix |
|---|---|---|---|---|
| JR001 | warn | Absence: "is X missing?", 「〜が無いか」 | Fired on 77% of clean diffs (presence questions: 3%) | Ask for the bad pattern's presence. Leave absence to a reviewer with full context. |
| JR002 | warn | Conditions joined with AND, 「かつ」 | Recall 96 / 90 / 81 / 73% for 1 / 2 / 3 / 4 conditions | One viewpoint per condition (`report = false`) + `[[rule]] all = [...]` |
| JR003 | error | Nested AND/OR in one question | 84% correct; 97% when combined in code | Same as JR002, with `any` / `none` |
| JR004 | warn | Abstract: "any security issue?", 「問題があるか」 | Fired on other kinds of defects 35–76% of the time | Name the concrete pattern, one per viewpoint |
| JR005 | warn | Subjective: readable, maintainable, clean | Ranked 7–8 of 8 before/after pairs right; as pass/fail 54–75% | Use only to compare two versions |
| JR006 | warn | Verdict: "safe to merge?" | Never passed a defect; stopped 47% of clean changes | Use only to skip a deep review when it says yes |
| JR007 | warn | Logic or intent | p = 0.65 on average; inverted comparisons missed | Name a visible shape (`i <= len(xs)`) |
| JR008 | info | Category with examples ("such as", 「など」) | XSS under "dangerous call": 0.04; naming innerHTML: 0.94 | List every kind, per language |
| JR009 | warn | More than three exceptions | Last of three: 0.26 → 0.68 | Keep three, most important first |
| JR010 | info | Not a yes/no question | — | End with "?" or 「か。」 |
| JR011 | info | Question over 400 characters | — | Split |
| JR012 | warn | Duplicate question | — | Remove |
| JR013 | info | Red threshold below 0.7 | p 0.5–0.7 was right about 48% of the time | Keep 0.7; use yellow for 0.5–0.7 |
| JR014 | info | Rule with a single condition | — | Use the viewpoint directly |

## Not caught by the linter

These need judgement; the `audit-viewpoints` skill checks them.

- **Exceptions scoped by kind instead of by a visible anchor.** "Ignore keys that are public by design" also cleared a Google key in Swift (0.97 → 0.24). "Ignore the apiKey inside a JavaScript firebaseConfig object" did not (0.95). Scope exceptions by a path, object, function or variable name.
- **Examples that miss a language's form.** A secret check that names `sk-` but not `AKIA`, or an error check that names `except: pass` but not `|| true` or `continue-on-error: true`.
- **Viewpoints that overlap.** Neighbouring questions (shell injection and unsafe delete) can fire together. That is fine; do not count both as separate problems.

## Rewrites

| Before | After |
|---|---|
| Is a timeout missing on the external API call? | Does an added line call requests.get, fetch or http.Get without a timeout argument? |
| Is there SQL that uses concatenation and an external value? | Three viewpoints (`builds_sql`, `concatenates_value`, `uses_external_value`, `report = false`) + `[[rule]] all = [...]` |
| Does this change have any security issues? | `sql_injection`, `shell_injection`, `html_injection`, `hardcoded_secret` ... as separate viewpoints |
| Does an added line contain a logical error? | Does an added loop use an end condition such as `i <= len(xs)`? |
| 追加行に eval や SQL の連結など、危険な呼び出しがあるか。 | 追加行で、外部から来た値を eval、exec、new Function でプログラムとして実行しているか。（ほかの種類は別の観点に） |
