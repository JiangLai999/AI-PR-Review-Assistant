# P6 评论格式冻结审计（mimo-p6-comment-freeze-audit）

- 日期：2026-09-25
- 范围：`docs/review-workspace-contract.md` §13.4 格式要素逐条对齐
- 写入范围：`tests/test_report_renderer.py`（仅新增）、本文件；补测轮（mimo-p6-freeze-pin-rest）追加 `tests/test_jsonl_backend.py`（仅新增）
- 实现未改动；若实现与文档策略不一致，只记录不改代码

## 1. 折叠策略（本轮补齐的测试缺口）

文档策略（§13.4 第 5 条）：critical 块应为 `<details open>`，其余严重级块应为
`<details>`，顺序为 critical / high / medium / low / info。

实现位置：`src/ai_pr_review/services/report_renderer.py:768`

```python
opening = "<details open>" if severity == "critical" else "<details>"
```

块顺序由 `SEVERITY_ORDER`（`report_renderer.py:19`）在
`_github_severity_sections`（`report_renderer.py:559`）驱动。

新增测试（`tests/test_report_renderer.py`）：

| 测试 | 覆盖 |
|---|---|
| `test_render_github_comment_folds_only_critical_open_across_severities` | 五级多严重级输入：顺序 critical→high→medium→low→info；critical 为 `<details open>`；high/medium/low/info 均为 `<details>` 且不含 `open` |
| `test_render_github_comment_opens_the_only_critical_block` | 仅 critical 输入：唯一块为 `<details open>`；`<details open>` 恰出现 1 次；不存在其它严重级块 |

结论：实现与文档策略一致，无需改实现。

## 2. §13.4 要素三列对齐表

| 文档要素 | 实现位置 | 是否有测试钉住 |
|---|---|---|
| 1. Target line：`repo · PR # · title · N files changed` | `_github_target_line` `report_renderer.py:586-614` | 是 — `test_report_renderer.py:189-193`；覆盖率后缀 `:330-348` |
| 2. Stats line：严重级计数 + 证据健康度（valid/needs review/invalid/unverified） | `_github_stats_line` `report_renderer.py:636-669` | 是 — `:194-195`（en）、`:231-233`（zh） |
| 3. Provenance line：model / run id / duration / cost | `_github_meta_line` `report_renderer.py:671-690` | 是 — `:218-219`（model+run）、`:349-351`（reviewed_at/duration/cost）、`:353-359`（cost=0 → 成本未记录） |
| 4. 🎯 Fix first (top 3)：可点击 `file:line`、confidence、证据徽章 | `_github_top_findings` `report_renderer.py:731-750`（limit=3 于 `:738`） | 是 — 标题 `:196`/`:234`、链接与回退 `:203-217`、fork 回退 `:301-310`；上限与排序 `test_render_github_comment_shortlists_at_most_three_by_severity_then_confidence` |
| 5. 每严重级一个折叠块：critical 展开，其余折叠 | `_github_severity_block` `report_renderer.py:752-782`（开合策略 `:768`） | 是（本轮补齐）— `:481-502`、`:505-515`；此前仅有 summary 文案 `:197`/`:235` |
| 5b. 紧凑卡片 `#### n. icon title` + `location · confidence · evidence · category · source` | `_github_finding_card` `report_renderer.py:784-849` | 是 — 标题 `:198`、confidence `:236`、证据徽章 `:398-410`；category/sources `test_render_github_comment_card_detail_line_carries_category_and_sources` |
| 6. 可折叠逐文件摘要 + 保留结论摘要 | `_github_summary_block` `report_renderer.py:885-933` | 是 — `:241-258` |
| 7. Footer：证据优先比例、model、run、commit | `_github_footer` `report_renderer.py:935-957` | 是 — zh 证据比例前缀 `:238`；五片段与缺失不臆造 `test_render_github_comment_footer_carries_evidence_ratio_model_run_commit`、`test_render_github_comment_footer_omits_missing_model_run_commit` |
| 规则：`file:line` 有 sha 才成链接，否则纯代码文本 | `_github_blob_link` `:692-712`、`_github_location` `:714-729` | 是 — `:203-217` |
| 规则：fork 走 PR files 视图 | `_github_location` `:721-725` | 是 — `:301-310` |
| 规则：HTML 转义（`&`/`<`/`>`）+ 前导 `#` 中和 + 反引号路径双反引号回退 | `_github_escape_prose` `:864-875`、`_github_code_span` `:877-883` | 是 — `:272-289`（转义）、`:292-298`（路径反引号） |
| 规则：chrome 跟随 `GitHubCommentMeta.language`，模型/规则正文不改写 | `zh` 判定 `:448`，chrome 各处 | 是 — `:184-200`（en）、`:222-238`（zh）、`:94-137`（证据词表） |
| 规则：长 problem+suggestion 折叠进 `<details>` | `_github_finding_card` `:828-844`（阈值 `_GITHUB_FOLD_THRESHOLD=320` `:157`） | 是 — `:241-258` |
| 规则：`github_comment_template` 优先于内置布局 | `render_github_comment` `:432-433` | 是（集成层）— `tests/test_jsonl_backend.py:2238-2250`；`tests/test_report_renderer.py` 内无直接用例 |
| 空 findings 短形态 | `_render_github_comment_v2` `:476-488` | 是 — `:261-269`（`### ✅ No findings`、无 `<details`、无 Fix first） |
| 未知 `evidence_status` 回退到「未校验」 | `_evidence_key` `:101-104`、`_github_evidence_counts` `:617-622`、`_github_evidence_badge` `:624-634` | 是 — `:140-153`（terminal + comment 徽章/计数）、`:122-137`（四态词表） |
| 超大评论 24k soft cap 的 compact 降级 | `_render_github_comment_v2` `:501-547`（`_GITHUB_SOFT_LIMIT=24000` `:187`，每级 6 条 `:188`） | 是 — `:362-383`（长度上限、per-file 省略提示、more-in-severity 计数）；步骤效果与最后一刀 `test_render_github_comment_compact_drops_per_file_then_counts_within_soft_limit`、`test_render_github_comment_compact_cut_marker_is_the_last_resort_and_last_segment` |
| already_published 重复发布警告文案 | `publish_service.py:56`（`REPEAT_PUBLISH_WARNING`）、拼装 `:356-396` | 是 — `tests/test_jsonl_backend.py` 字面冻结 + 归属 `test_repeat_publish_warning_literal_stays_in_publish_text_not_comment_body`；常量跟随断言 `:2154-2177` 仍在 |

## 3. 仍然没有测试钉住的要素（逐项行号）

> 2026-09-25 补测（mimo-p6-freeze-pin-rest）：下列 5 项已全部钉住，详见 §6。

### 3.1 Fix first 的 top-3 上限 — 已钉住

- 实现：`report_renderer.py:738`（`limit = 3`）
- 现状：已由 `test_render_github_comment_shortlists_at_most_three_by_severity_then_confidence` 钉住——输入 2 critical + 3 high 时短名单恰好 3 条，顺序为严重级优先、同级置信度降序（crit-high 0.90 → crit-low 0.70 → high-top 0.95）。

### 3.2 卡片 `category` / `sources` 位 — 已钉住

- 实现：`report_renderer.py:801-809`
- 现状：已由 `test_render_github_comment_card_detail_line_carries_category_and_sources` 钉住——明细行同时含 category 与 sources；中文界面 category 走 `GITHUB_CATEGORY_LABELS_ZH`（`security` → `` `安全` ``），sources 原样保留（`` `static_rule`, `ai_analysis` ``）；英文界面 category 为原始枚举码。

### 3.3 Footer 组成（model / run / commit / 证据比例）— 已钉住

- 实现：`report_renderer.py:935-957`
- 现状：
  - `test_render_github_comment_footer_carries_evidence_ratio_model_run_commit` 钉住五片段齐全：中文 `证据优先 · 位置与片段校验通过 X/Y · 模型 \`…\` · run \`…\` · 提交 \`…\``；英文 `evidence-first · X/Y locations and snippets validated · model \`…\` · run \`…\` · commit \`…\``。
  - `test_render_github_comment_footer_omits_missing_model_run_commit` 钉住缺失不臆造：只给 model 时无 run/commit，只给 run 时无 model/commit（中英文均覆盖）。

### 3.4 超大评论 compact 步骤顺序 — 已钉住

- 实现：`report_renderer.py:501-547`
  1. 超限先丢逐文件摘要（compact 路径不含 `_github_summary_block`，`:508-536`）
  2. 严重级块截到每级 6 条（`:512-520`）
  3. 仍超限则显式 ⛔ 截断标记（`:540-547`）
- 现状：
  - `test_render_github_comment_compact_drops_per_file_then_counts_within_soft_limit` 钉住步骤 1/2 与 soft limit：`Model summary by file` 整段消失并出现 `per-file prose omitted` 提示，出现 `more in this severity` 计数，且 `len(output) <= _GITHUB_SOFT_LIMIT`；compact 已回到限内时不得出现 `Comment truncated`。
  - `test_render_github_comment_compact_cut_marker_is_the_last_resort_and_last_segment` 钉住步骤 3：仍超限时出现 `⛔ Comment truncated`，标记是正文最后一段（`endswith("for the full report.\n")`），且长度仍不超过 soft limit。
  - 说明：最后一刀按前缀截断 `compact_body[:soft-len(marker)] + marker`，极端长度下末尾的 `per-file prose omitted` 提示行可能被切掉，故第二条用例只钉「逐文件摘要已省略」这一效果，不钉提示行仍在。

### 3.5 already_published 警告文案 — 已钉住

- 实现：`publish_service.py:56`
  `REPEAT_PUBLISH_WARNING = "注意：该 Run 在本会话中已发布过一次，再次确认会再创建一条评论。"`
  拼装于 `:361-362`（preview）与 `:383-384`（published）
- 现状：已由 `test_repeat_publish_warning_literal_stays_in_publish_text_not_comment_body` 钉住。
- **真实归属位置**：该警告属于**发布预览/发布结果的 UI 提示文本**（`_preview_payload` / `_published_payload` 返回的 `text` 字段），**不是** GitHub 评论正文（`comment_body`）。用例同时钉住：
  1. 常量字面量逐字冻结（改写常量会红，不再是跟随性断言）；
  2. `already_published` 标志首次为 `False`、同会话重复发布为 `True`；
  3. 警告出现在 `text` 中、且**不**出现在 `comment_body` 中（评论正文两次一致）。
- 文档 §13.5 F 项「warn that a second comment will be created」的语义由 `text` 承载，预览与确认两侧文案一致。

## 4. 验证

```powershell
New-Item -ItemType Directory -Force -Path .pytest_x
$env:TEMP = (Resolve-Path .pytest_x).Path
$env:TMP  = $env:TEMP
python -m pytest tests/test_report_renderer.py tests/test_jsonl_backend.py -q --no-cov
python -m pytest -q --no-cov
```

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/test_report_renderer.py -q --no-cov` | **25 passed** in 0.26s（原 23 + 新增 2） |
| `python -m pytest -q --no-cov` | **570 passed, 1 skipped** in 84.55s |
| `python -m pytest tests/test_report_renderer.py tests/test_jsonl_backend.py -q --no-cov`（mimo-p6-freeze-pin-rest） | **111 passed** in 5.09s |
| `python -m pytest -q --no-cov`（mimo-p6-freeze-pin-rest） | **577 passed, 1 skipped** in 83.60s |

未改动任何实现/前端/凭据；未做 git 操作。

## 5. 未决项

1. ~~§3.1 top-3 上限、§3.2 卡片 category/sources 位、§3.3 footer 四段组成、§3.4 compact 步骤顺序、§3.5 already_published 字面文案——均未钉~~ 已由 mimo-p6-freeze-pin-rest 全部钉住（见 §6）。
2. ~~§3.5 的「跟随性断言」是否升级为字面冻结~~ 已升级：`test_repeat_publish_warning_literal_stays_in_publish_text_not_comment_body` 以字符串字面量冻结常量，改写常量会红。
3. 保留观察：compact 最后一刀按前缀截断，极端长度下末尾的 `per-file prose omitted` 提示行可能被切掉。当前用例只钉「逐文件摘要已省略」的效果；若产品侧要求提示行永不丢失，需要改实现（不在 write_scope）。

## 6. 本轮补测清单（mimo-p6-freeze-pin-rest，2026-09-25）

写入范围仅：`tests/test_report_renderer.py`、`tests/test_jsonl_backend.py`、本文件。只新增测试函数/断言，未删改既有用例，未改实现与前端。

| # | 要素 | 测试函数 | 文件 | 钉住内容 |
|---|---|---|---|---|
| 1 | Top 短名单上限与排序 | `test_render_github_comment_shortlists_at_most_three_by_severity_then_confidence` | `tests/test_report_renderer.py` | >3 条 critical/high 时短名单恰好 3 条；顺序严重级优先、同级置信度降序 |
| 2 | 卡片 category + sources | `test_render_github_comment_card_detail_line_carries_category_and_sources` | `tests/test_report_renderer.py` | 明细行同时含二者；zh 下 category 中文映射、sources 原样；en 下 category 为枚举码 |
| 3 | Footer 五片段齐全 | `test_render_github_comment_footer_carries_evidence_ratio_model_run_commit` | `tests/test_report_renderer.py` | zh：证据优先/位置与片段校验通过 X/Y/模型/run/提交；en：evidence-first/locations and snippets validated/model/run/commit |
| 4 | Footer 缺失不臆造 | `test_render_github_comment_footer_omits_missing_model_run_commit` | `tests/test_report_renderer.py` | 只给 model 或只给 run 时缺失项不出现（中英文） |
| 5a | compact 降级步骤 1+2 | `test_render_github_comment_compact_drops_per_file_then_counts_within_soft_limit` | `tests/test_report_renderer.py` | 省略逐文件摘要并提示 `per-file prose omitted`；`more in this severity` 计数；`len <= _GITHUB_SOFT_LIMIT`；限内不出现 `Comment truncated` |
| 5b | compact 最后一刀 | `test_render_github_comment_compact_cut_marker_is_the_last_resort_and_last_segment` | `tests/test_report_renderer.py` | 仍超限时 `⛔ Comment truncated` 且为正文最后一段；长度仍 ≤ soft limit |
| 6 | already_published 字面与归属 | `test_repeat_publish_warning_literal_stays_in_publish_text_not_comment_body` | `tests/test_jsonl_backend.py` | `REPEAT_PUBLISH_WARNING` 字面冻结；`already_published` 标志；警告属发布 `text` 而非 `comment_body` |

辅助只读助手（同文件内私有函数，非用例）：`_shortlist_rows`、`_comment_footer`、`_titled_finding`（`tests/test_report_renderer.py`）。

既有用例全部保留未改：`tests/test_report_renderer.py` 原 25 项（现 31）、`tests/test_jsonl_backend.py` 原 79 项（现 80）；本轮新增 7 项，合计 111 项（两文件）。
