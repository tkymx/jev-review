# jev-review

git の差分を hunk ごとに [TypeSafe Jev](https://docs.typesafe.ai/introduction) に渡し、観点ファイルに沿って判定して、どこが怪しいか（何行目か）を XML レポートにまとめる CLI です。

[English README](README.md)

```text
$ jev-review run HEAD -v core.ja -o report.xml
jev-review: 5 units in 5 files - red 3, yellow 0, green 1, skipped 1 (7 calls, 6,890 input tokens, about $0.0003)
  RED    api/users.py:40-43  sql_injection 0.98  -> line 41: q = "SELECT * FROM users WHERE name = '" + name + "'"
  RED    service/order.py:40-43  debug_leftover 0.99  -> line 41: print("DEBUG order payload:", order.raw)
  RED    web/view.js:40-41  html_injection 0.97  -> line 41: box.innerHTML = new URLSearchParams(location.search).get("q");
report: report.xml
```

## なぜ作ったか

変更のたびに LLM に全部レビューさせると、時間も費用もかかります。Jev は文章を書かず、質問ごとに「はい」の確率だけを返します。1 回 0.3 秒ほどで、費用は 1 円に届きません。人や LLM が読む前に、見るべき hunk と行を絞り込む一次チェックに向いています。

ただし精度は質問の書き方しだいです。このツールを作る前に、答えの分かっているコード（10 言語・形式の 72 件）で Jev を 2,578 回呼んで測りました。

| 変えたこと | 結果 |
|---|---|
| 目に見える事実を 1 つだけ聞く | 99% 正しい |
| 観点を増やす（6 → 387 個） | 検出率 89〜92%、応答 0.3〜0.4 秒のまま |
| 条件を「かつ」でつなぐ（1 → 4 個） | 96% → 73% に下がる。1 つずつ聞いてコードで組み合わせると 97% |
| 「〜が無いか」と聞く | 正常な差分でも 77% が yes（「〜があるか」は 3%） |
| 見つけたい種類を名指ししない（「危険な呼び出し」で XSS） | 0.04。innerHTML と名指しすると 0.94 |
| 抽象的に聞く（「セキュリティの問題があるか」） | 別の種類の問題にも 35〜76% 反応 |
| hunk の周りに無関係な文章を 2k〜28k トークン足す | 92% → 86〜89% |
| p が 0.5〜0.7 の答え | 当たるのは半分ほど。0.9 以上なら 97% |

jev-review はこの結果をそのまま既定値にしています。1 hunk を 1 回で、観点は全部その 1 回で聞く。赤は 0.7 以上、黄は 0.5 以上。文章の hunk にはコード用の観点を使わない。複合条件はコード側で組み合わせる。失敗した書き方の観点は lint で指摘する。詳しくは [docs/findings.ja.md](docs/findings.ja.md) にまとめています。

## インストール

Python 3.11 以上。依存ライブラリはありません。

```bash
pipx install git+https://github.com/tkymx/jev-review
# クローンした場合
pip install -e .
```

TypeSafe の API キー（<https://console.typesafe.ai/>）を環境変数 `TYPESAFE_API_KEY` に入れるか、`--env-file` でファイルを渡します。

## 使い方

```bash
# サンプル差分をどう分割し、いくらかかるかを見る（API キー不要）
jev-review run --patch examples/sample.patch -v core.ja --dry-run

# 実際に判定する
export TYPESAFE_API_KEY=...
jev-review run --patch examples/sample.patch -v core.ja -o report.xml

# 自分のリポジトリで
jev-review run -v core.ja                      # コミット前の変更
jev-review run --staged -v core.ja             # ステージ済みの変更
jev-review run HEAD -v core.ja                 # 直近のコミット
jev-review run origin/main...HEAD -v core.ja   # ブランチやプルリクエスト
```

終了コードは `0` が `--fail-on` の水準（既定は `red`）に当たる指摘なし、`1` が指摘あり、`2` がエラーです。`--fail-on yellow` や `--fail-on never` で変えられます。

GitHub Actions で動かす例は [examples/github-actions/jev-review.yml](examples/github-actions/jev-review.yml) にあります。

## 中でやっていること

1. **差分を判定単位に分ける。** 1 単位は 1 ファイルの 1 hunk です。追加行が 60 行を超える hunk は、関数の切れ目か空行で分けます。ロックファイル・画像・圧縮済みファイルは除外します。
2. **1 単位につき 1 回で、全観点をまとめて聞く。** 同じ呼び出しに質問を増やしても互いに邪魔しませんでした。分けて聞くと費用が増えるだけです。
3. **文章にはコード用の観点を使わない。** 組み込みの質問で追加行がコードかどうかを判定し、Markdown やメモは `target = "code"` の観点で判定しません。
4. **確率で色を決める。** `p >= 0.7` が赤、`p >= 0.5` が黄です。
5. **複合条件はコードで計算する。** `[[rule]]` で観点を `all`・`any`・`none` で組み合わせます。
6. **怪しい行を特定する。** 赤か黄の単位だけ、原因の追加行がどれかを追加で 1 回聞きます。
7. **XML レポートを書く。** 例は [examples/report.sample.xml](examples/report.sample.xml) です。

Jev に渡すのは、ファイルのパス、行の範囲、hunk の見出しにある関数名、hunk 本体です。**差分の中身は TypeSafe の API に送られます。** 外部に送ってはいけないコードには使わないでください。

## 観点ファイル

観点は、追加行について「はい／いいえ」で答えられる質問 1 つです。TOML で書きます。

```toml
[review]
language = "ja"      # 組み込みの質問の言語（ja か en）
red = 0.7
yellow = 0.5

[[viewpoint]]
id = "html_injection"
severity = "high"
question = "追加行で、外部から来た値を innerHTML、outerHTML、insertAdjacentHTML、document.write、dangerouslySetInnerHTML、v-html で画面の HTML に差し込んでいるか。"

[[viewpoint]]
id = "debug_leftover"
severity = "low"
question = "追加行に、DEBUG と書かれた print、console.log、NSLog、fmt.Println、puts のようなデバッグ用の出力があるか。"
exceptions = ["ただし、テストコード（tests/ の中や test_ で始まるファイル）の中は除く。"]
files = ["*.py", "*.js", "*.ts", "*.swift", "*.go"]
```

複合条件は、`report = false` にした観点を `[[rule]]` で組み合わせます。例は [examples/viewpoints/compound.ja.toml](examples/viewpoints/compound.ja.toml)、書式の全体は [docs/viewpoint-format.md](docs/viewpoint-format.md) にあります。

### 同梱の観点

`-v core.ja` と `-v core.en` は、同じ 15 項目の日本語版と英語版です。

| 分野 | 観点 |
|---|---|
| 秘密情報 | `hardcoded_secret` |
| 注入 | `sql_injection`、`shell_injection`、`code_eval`、`html_injection`、`remote_script`、`unsafe_delete` |
| エラー処理 | `swallowed_error` |
| 開発用の痕跡 | `debug_leftover` |
| 費用 | `paid_api_without_guard` |
| 名前の付いたバグの形 | `loop_off_by_one`、`assignment_in_condition`、`null_equality`、`unbounded_wait_loop`、`unclosed_resource` |

[samples/](samples/) の正解付き 61 件では、赤の線で数えると日英とも 61 件すべて正しく判定しました。黄も当たりとして数えると、拾えた割合は 100% のまま、誤検知は英語 0.2%・日本語 0.5% で、どれも p 0.51〜0.67 でした。**このサンプルは観点を書くときに参照した実験ケースと同じなので、成績は上限と考えてください。** 自分のコードでの精度は `jev-review eval` で測れます。

不等号の向きが逆、None の確認漏れのように、意図を知らないと分からないバグは同梱の観点に入れていません。Jev では安定して見つけられませんでした。

## 観点の書き方をチェックする

`jev-review lint` は、実験で精度が落ちた書き方を見つけて、理由と直し方を出します。

```bash
jev-review lint my-viewpoints.toml
jev-review lint examples/viewpoints/anti-patterns.ja.toml   # アンチパターンを全部含む例
```

| コード | アンチパターン | 実測 |
|---|---|---|
| JR001 | 「〜が無いか」 | 正常な差分でも 77% が yes |
| JR002 | 条件を「かつ」でつなぐ | 1 → 4 条件で 96% → 73% |
| JR003 | 入れ子の AND/OR | 84%。`[[rule]]` に分けると 97% |
| JR004 | 抽象的（「セキュリティの問題があるか」） | 別の種類の問題にも 35〜76% 反応 |
| JR005 | 主観的（「読みやすいか」） | 前後の比較はできるが、合否は 54〜75% |
| JR006 | 合否（「マージしてよいか」） | 欠陥は通さないが、正常の 47% も止める |
| JR007 | ロジックや意図 | 平均 p = 0.65。不等号の逆は見逃す |
| JR008 | 「など」でくくる | 例に書いた種類しか拾わない |
| JR009 | 例外が 4 個以上 | 後ろの例外ほど効かない |

全項目と書き直しの例は [docs/anti-patterns.md](docs/anti-patterns.md) にあります。

書き方を読むのではなく実測したいときは、正解付きのパッチで試します。

```bash
jev-review eval -v my-viewpoints.toml --samples samples
```

観点ごとに拾えた割合と誤検知率を出し、`--min-recall`（既定 0.8）を下回るか `--max-fp`（既定 0.1）を上回る観点があれば `1` で終わります。サンプルの形式は [samples/README.md](samples/README.md) にあります。

### Claude Code スキル: audit-viewpoints

[Claude Code](https://claude.com/claude-code) 用のスキル [`.claude/skills/audit-viewpoints`](.claude/skills/audit-viewpoints/SKILL.md) を同梱しています。このリポジトリを Claude Code で開いて「この観点ファイルを監査して」と頼むと、lint を走らせ、正規表現では判断できない点（例外の範囲が広すぎる、など）も見て、書き直し案を出し、必要なら `eval` で効果を測ります。ほかのプロジェクトで使うときは、フォルダごとそのプロジェクトの `.claude/skills/` か `~/.claude/skills/` にコピーしてください。

## 限界

- Jev は hunk だけを見て答えます。チェックが別のファイルにあるかどうかは分かりません。
- 意図は理解しません。絞り込みに使い、最終判断は周りのコードを読める人か LLM に任せてください。
- 閾値は `jev-1.13.0` で測りました。既定でこのモデルに固定しています（`--model`）。モデルを変えたら `eval` で測り直してください。
- 費用は入力トークンのみで、執筆時点で 100 万トークンあたり $0.042 です。上のサンプルは $0.0003 でした。

## 開発

```bash
PYTHONPATH=src:tests python -m unittest discover -s tests
```

テストは偽のクライアントを使うので、API キーは要りません。

## ライセンス

MIT
