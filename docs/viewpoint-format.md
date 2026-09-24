# Viewpoint file format

Viewpoint files are TOML. Pass one or more with `-v`; later files add viewpoints and rules, and settings come from the first file. Bundled files are referenced by name (`-v core.en`, `-v core.ja`; `jev-review list` shows them).

## `[review]`

| Key | Default | Meaning |
|---|---|---|
| `name` | file name | Shown in the report |
| `language` | `en` | Language of the built-in questions (`en` or `ja`). Write your viewpoints in the same language. |
| `red` | `0.7` | p at or above this is red |
| `yellow` | `0.5` | p at or above this is yellow |

`0 < yellow <= red <= 1`. `--red` and `--yellow` on the command line override the file.

## `[[viewpoint]]`

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | `[a-z][a-z0-9_]*`, unique across all files |
| `question` | yes | One yes/no question about the added lines |
| `exceptions` | no | List of sentences appended to the question ("Ignore ..."). At most three; the first works best. |
| `severity` | no | `high`, `medium` (default) or `low`. Reported as-is; it does not change the colour. |
| `target` | no | `code` (default): skipped when the hunk is prose such as Markdown. `any`: always asked. |
| `files` | no | Glob patterns; the viewpoint is only asked for matching paths (`*.py`, `.github/workflows/*.yml`) |
| `report` | no | `false` to use the viewpoint only inside rules |

What Jev receives for each question is `question` followed by the exceptions, and a state object:

```json
{"file": "api/users.py", "lines": "40-43", "enclosing": "def find_user(name):", "diff": "     conn = get_conn()\n+    q = ..."}
```

## `[[rule]]`

A compound check computed in code, so Jev never has to combine conditions itself.

| Key | Meaning |
|---|---|
| `id` | Unique id |
| `all` | Viewpoints that must all hold. Contributes `min(p)`. |
| `any` | Viewpoints of which at least one must hold. Contributes `max(p)`. |
| `none` | Viewpoints that must not hold. Contributes `1 - max(p)`. |
| `severity` | As for viewpoints |
| `message` | Text shown in the report and used when pointing at the line |

The rule's p is the minimum of the parts that are set, coloured with the same thresholds. A rule is evaluated only on units where every referenced viewpoint applied (matching `files`, not skipped as prose).

```toml
[[viewpoint]]
id = "builds_sql"
report = false
question = "Is there an SQL statement (SELECT, INSERT, UPDATE, DELETE) in the added lines?"

[[viewpoint]]
id = "concatenates_value"
report = false
question = "Does an added line put a value into a string with +, ||, an f-string or format?"

[[viewpoint]]
id = "uses_placeholder"
report = false
question = "Does the added SQL use placeholders such as ?, $1 or :name?"

[[rule]]
id = "sql_built_by_concat"
severity = "high"
all = ["builds_sql", "concatenates_value"]
none = ["uses_placeholder"]
message = "SQL is built by string concatenation"
```

## Report

The XML report lists, per file and per unit (hunk): the status, the red and yellow findings (`--include-green` adds the rest), the probability that the unit is code (`is-code`), and the suspect line (`location`). Units cut from a longer hunk carry `split="true"`. See [../examples/report.sample.xml](../examples/report.sample.xml).
