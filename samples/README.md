# Samples

Labeled patches for `jev-review eval`. They come from the cases used to measure Jev (see [../docs/findings.md](../docs/findings.md)), with fake secrets changed so they do not match real key formats.

| Folder | Contents |
|---|---|
| `python/` | 16 cases: 10 with one planted problem, 6 clean |
| `javascript/`, `typescript/`, `shell/`, `sql/`, `github-actions/`, `docker/`, `go/`, `swift/` | 3–6 cases each |
| `markdown/` | 3 prose hunks that mention eval, a key and a price; nothing should fire |
| `exceptions/` | 10 cases that fall under an exception of the core viewpoints; nothing should fire |

## Format

`index.toml` lists the cases:

```toml
[[case]]
id = "sql_concat"
patch = "python/sql_concat.patch"
expect = ["sql_injection"]   # viewpoint ids that should fire; [] when nothing should
note = "optional"
```

A viewpoint fires on a case when its highest p over the case's units reaches the yellow threshold (`--yellow` changes it). `expect` uses the ids of the bundled `core.en` / `core.ja`. For your own viewpoint file, make your own samples folder with your own ids; real diffs from your repository (`git show <commit> > case.patch`) work best.
