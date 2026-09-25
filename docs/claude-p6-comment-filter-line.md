# P6 交付报告：评论过滤披露行（任务 `claude-p6-comment-filter-line`）

**一句话结论**：在冻结的 v2 评论版式上做了一处有意的最小扩展——stats 引用块的最后一行披露
`已审查 X/Y 个文件 · 置信度门槛 N · 低于门槛过滤 N 条 · 去重 N 条`。有 findings 与无 findings
两个分支都会渲染这一行；**哪一段没有数据就省略那一段，整行没有数据就整行省略**（旧 Run 的评论
与改动前逐字一致，不臆造 0）。两条评论生产者（CLI `--publish-comment` 与 `/publish`）共用同一个
归一化入口 `comment_filter_disclosure`，离线实测同一条 Run 的两份正文逐字相同。

- 任务类型：实现。写入范围：`services/report_renderer.py`、`services/publish_service.py`、
  `cli.py`、`tests/test_report_renderer.py`、`tests/test_jsonl_backend.py`、本文件。
- 验证命令：`New-Item -ItemType Directory -Force -Path .pytest_x` → `TEMP`/`TMP` 指向它 →
  `python -m pytest -q --no-cov`
- 结果：**605 passed, 1 skipped**（基线 593 passed + 1 skipped；本轮新增 12 例：
  `tests/test_report_renderer.py` 6 例、`tests/test_jsonl_backend.py` 6 例）
- 未做：未读/打印/传输凭据，未执行任何 git 操作，未修改 write_scope 之外的文件（含 `frontend/`、
  `web/`、`web_server.py`、`post_processor.py`、两个 orchestrator），未联网、未向任何 PR 写入内容。

## 1. 缺陷证据（改动前实测）

| 证据 | 命令/位置 | 结果 |
|---|---|---|
| 评论没有任何过滤披露 | 离线样本「修复前」段（`.pytest_x/p6_comment_filter_line_sample.txt`）：门槛丢掉全部 3 条候选后，评论只有 `**0 个问题**` + 证据行 + 元数据行 | 读者无法区分「模型判定没问题」与「候选全被门槛丢掉」——正是用户实测的 2 问题→0 问题困惑 |
| 计数早已在库里，却没有读取方 | `review_orchestrator.py:367`、`hybrid_orchestrator.py:332` 写 `metadata["filtered_findings"]`（`before/after/below_threshold/duplicates/severity_sorted`）；`docs/claude-p6-hybrid-postprocess.md` §未决项 2 已登记「暂无读取方」 | 数据齐备，缺的只是渲染 |
| 两条生产者各自拼装 meta | 改动前 `publish_service.py:302-318` 与 `cli.py:1642-1657` 的 `GitHubCommentMeta(...)` 都没有过滤字段 | 需要给两处补同一份数据，且不能各自漂移 |

## 2. 实现

### 2.1 渲染层（`services/report_renderer.py`）

`GitHubCommentMeta` 增加三个可选字段（`:190-192`），全部默认 `None`：

```python
threshold: float | None = None
below_threshold: int | None = None
duplicates: int | None = None
```

新增 `_github_audit_line`（`:739-780`），挂在 stats 引用块最后一行（`:480-482`）：

```python
audit_line = self._github_audit_line(context, meta, zh)
if audit_line:
    quote_lines.append(audit_line)
```

规则（一条一行，逐段可选）：

| 片段 | 数据 | 中文 | 英文 |
|---|---|---|---|
| 覆盖度 | `meta.files_reviewed` + `context.files_changed` | `已审查 {x}/{y} 个文件` | `reviewed {x}/{y} files` |
| 门槛 | `meta.threshold` | `置信度门槛 0.60` | `confidence threshold 0.60` |
| 低于门槛 | `meta.below_threshold` | `低于门槛过滤 N 条` | `filtered N below threshold` |
| 去重 | `meta.duplicates` | `去重 N 条` | `N duplicates` |

- **整行省略**：三个过滤字段全为 `None` 时直接返回 `""`（`:757-758`）——覆盖率已由目标行承担，
  没有过滤数据的 Run 不会多出一行重复的覆盖度。
- **逐段省略**：某段的值为 `None` 就跳过该段（`0` 是实测值，照常显示）。
- **有/无 findings 都显示**：引用块在两条分支之前渲染，因此空 findings 的短形态同样带这一行
  （离线样本第二条即「0 个问题 + 低于门槛过滤 3 条」）。
- 该行随 `quote_lines` 一起进入 compact 降级路径的 `head`，超长评论被迫截断时披露也不会丢。

### 2.2 两条生产者的取值（同一入口，防漂移）

`publish_service.py` 新增公开函数 `comment_filter_disclosure(stats, *, fallback_threshold)`
（`:176-201`）：把 `filtered_findings` 归一化成 `{threshold, below_threshold, duplicates}`，
坏值/缺失一律 `None`。门槛不由 stats 提供时回落到配置值，**但仅限记录了计数的 Run**。

| 生产者 | 计数来源 | 门槛来源 | 位置 |
|---|---|---|---|
| `/publish`（历史 Run） | `metadata["filtered_findings"]` | 记录了计数时取 `config.post_processor.confidence_threshold`；`filtered_findings` 里若已有 `threshold` 键则优先用它 | `publish_service.py:327-330`，写入 meta `:352-354` |
| CLI `--publish-comment` | `artifacts.filtered_findings` | 同上（同一进程、同一份 `app_config`，即产出这些计数的门槛） | `cli.py:1644-1647`，写入 meta `:1668-1670` |

### 2.3 未改动的冻结元素

标题、目标行（含其覆盖率后缀）、优先级短名单、严重级折叠块、卡片、页脚、转义规则、
`_GITHUB_SOFT_LIMIT` 体积上限与 compact 降级步骤全部逐字未动；既有冻结用例（含
`test_render_github_comment_outputs_target_stats_and_footer`、footer 五片段/缺失不臆造、
compact 两条、already_published 字面冻结）全部保持绿色。

## 3. 测试

新增 12 例（全部为新增用例，未删改既有断言）：

| # | 用例 | 文件:行 | 钉住内容 |
|---|---|---|---|
| 1 | `test_render_github_comment_closes_the_stats_block_with_the_filter_audit` | `test_report_renderer.py:775` | 有 findings：四片段齐全，且是引用块最后一行（其后紧跟短名单标题） |
| 2 | `test_render_github_comment_shows_the_filter_audit_without_findings_too` | `:800` | 无 findings 分支：`**0 个问题**` 与审计行同时出现 |
| 3 | `test_render_github_comment_omits_the_audit_line_without_filter_data` | `:825` | 字段缺失：整行省略，引用块仍只有 2 行（覆盖度不重复出现） |
| 4 | `test_render_github_comment_audit_line_keeps_only_the_fragments_it_has` | `:846` | 只给部分字段：只显示已有片段；`0` 是实测值要显示，`None` 才是省略理由 |
| 5 | `test_render_github_comment_audit_line_follows_the_interface_language` | `:876` | 英文措辞逐字：`reviewed 2/2 files · confidence threshold 0.60 · filtered 1 below threshold · 0 duplicates` |
| 6 | `test_cli_comment_report_reads_the_filter_audit_from_the_run_artifacts` | `:895` | CLI 路径从 `artifacts.filtered_findings` 取值、门槛取配置值（内存配置，不读磁盘/环境） |
| 7 | `test_publish_discloses_the_post_process_filter_counts` | `test_jsonl_backend.py:2473` | `/publish` 从 run metadata 读计数并落到同一行（预览不发帖） |
| 8 | `test_publish_explains_a_zero_finding_run_that_the_threshold_filtered` | `:2500` | 用户实测场景：3 条候选全被门槛丢掉 → `0 个问题` + `低于门槛过滤 3 条` |
| 9 | `test_publish_uses_the_configured_threshold_for_a_recorded_run` | `:2526` | 门槛不是写死的 0.6，取生效配置（0.75） |
| 10 | `test_publish_of_a_run_without_filter_metadata_keeps_the_audit_line_off` | `:2543` | 旧 Run 无 `filtered_findings`：整行省略 |
| 11 | `test_publish_discloses_only_the_filter_counts_the_run_recorded` | `:2558` | 只记了 `duplicates`：只显示该片段 |
| 12 | `test_publish_tolerates_a_malformed_filter_payload` | `:2582` | 坏数据（`"not-a-dict"`）不崩、也不被读成「0 条被过滤」 |

## 4. 变异验证（改坏实现，确认新用例会红）

| 变异 | 期望变红 | 实测 |
|---|---|---|
| 删掉「三个过滤字段全空 → 整行省略」的守卫 | 用例 3 | `test_render_github_comment_omits_the_audit_line_without_filter_data` FAILED（引用块 3 行 ≠ 2 行，多出 `> 已审查 1/1 个文件`） |
| 把缺失的 `below_threshold` 写成 `or 0` 并强制输出该段 | 用例 4 | `test_render_github_comment_audit_line_keeps_only_the_fragments_it_has` FAILED |
| `publish_service` 不再把 `below_threshold` 传给 meta | 用例 7、8 | 两例 FAILED |

三处均已逐字还原（`git` 不可用，按编辑前原文恢复），还原后全量重跑 605 passed, 1 skipped。

## 5. 离线端到端样本（复现用户实测场景）

脚本：`.pytest_x/p6_comment_filter_sample.py`；输出：`.pytest_x/p6_comment_filter_line_sample.txt`。
模拟「模型给 3 条候选（0.55/0.50/0.45）全部低于门槛 0.6」，全程离线：

```
== PostProcessor stats（run metadata 的 filtered_findings 同值）==
{'before': 3, 'after': 0, 'below_threshold': 3, 'duplicates': 0, 'severity_sorted': True}

== 修复前的形态 ==
> **0 个问题**
> **证据校验（位置与片段自洽）** ✅ 校验通过 0 · … · ❔ 未校验 0
> 审查于 2026-09-25 07:30:00 UTC · 模型 `deepseek-flash` · run `run-1234`

== 修复后的形态 ==
> **0 个问题**
> **证据校验（位置与片段自洽）** ✅ 校验通过 0 · … · ❔ 未校验 0
> 审查于 2026-09-25 07:30:00 UTC · 模型 `deepseek-flash` · run `run-1234`
> 已审查 2/2 个文件 · 置信度门槛 0.60 · 低于门槛过滤 3 条 · 去重 0 条

== 同一条 Run 走 /publish（从 metadata 读同样的计数）==
（同一行）published body == rendered body: True
```

## 6. 未决项

1. **`/publish` 历史 Run 的门槛是「当前配置值」**：review 时的门槛没有落进 run metadata
   （`post_processor.py` / 两个 orchestrator 都不在本任务写入范围），所以只有记录了
   `filtered_findings` 的 Run 才会显示门槛，且显示的是本机配置值。若用户在 review 之后、
   publish 之前改过 `confidence_threshold`，评论里的门槛数字会与当时的实际门槛不一致
   （计数仍然正确）。彻底的修法是在 `process_with_stats` 的 stats 里加 `threshold` 键——
   `comment_filter_disclosure` 已优先读它，届时无需再改本文件所在的三个模块。
2. **覆盖率出现两次**（目标行的作用域后缀 + 审计行的首段）是有意为之：审计行要能独立成立。
   若要合并需改目标行，属本轮冻结元素，未动。
3. `mypy src` 当前有 8 个既存错误，全部位于 `backend/jsonl_server.py`（本次未改动）；
   本次改动的三个文件 `mypy` 干净，`black`/`isort`（`.venv313`）对新增代码无差异。
