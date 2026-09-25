# P6 收尾交付报告：hybrid 证据校验贯通 + 作者元数据 + 发布时间 UTC（任务 `claude-p6-hybrid-evidence-author`）

**一句话结论**：`cli.run_review` 默认走的 `HybridReviewOrchestrator` 现在与标准编排器走同一条
证据校验路径——模型产出与静态规则产出都在拿到该文件 `(file_diff, context)` 的地方经
`FindingValidator` 校验并 `annotate`，计数写进 `metadata["validation_summary"]` 与
`ReviewArtifacts.validation_summary`；两个编排器都把 `metadata["pr_author"]` 写成
`pr_data.author or ""`，`publish_service` 优先读它、缺失才回退占位符；发布评论的
`reviewed_at` 从 SQLite 的无标记 UTC 时间格式化为带 `UTC` 标记的字符串，解析失败原样保留。

- 任务类型：实现（可写 `services/hybrid_orchestrator.py`、`services/review_orchestrator.py`、
  `services/publish_service.py`、`tests/test_review_orchestrator.py`、`tests/test_jsonl_backend.py`、本文件）
- 验证命令：`New-Item -ItemType Directory -Force -Path .pytest_x` → `TEMP`/`TMP` 指向它 →
  `python -m pytest -q --no-cov`
- 结果：**589 passed, 1 skipped**（本轮新增 11 个用例：`tests/test_review_orchestrator.py` 5 个 +
  `tests/test_jsonl_backend.py` 6 个）
- 未做：未读/打印凭据，未执行任何 git 操作，未修改 write_scope 之外的文件（含 `cli.py`、
  `web_server.py`、`frontend/tui`、`web/`），未联网、未向任何 PR 写入内容

## 1. 块一：hybrid 证据校验

### 1.1 缺陷（改动前实测）

| 证据 | 命令/位置 | 结果 |
|---|---|---|
| hybrid 全文件无校验调用 | `grep -c "FindingValidator\|evidence_status\|\.validate(" src/ai_pr_review/services/hybrid_orchestrator.py` | `0`（exit 1，无匹配） |
| 真实审查默认走 hybrid | `cli.py:1361,1378-1381`：`use_hybrid: bool = True`，`preferences.hybrid_strategy` 存在即用 `HybridReviewOrchestrator` | 默认分支 |
| 标准编排器的正确做法 | `review_orchestrator.py:265-271`（逐文件）/ `:286-290`（跨文件） | 已校验并计数 |

后果：hybrid run 的每条 finding 恒为默认 `evidence_status="unverified"`，真实 PR 评论显示
「校验通过 0 / 未校验 N」。

### 1.2 实现（`hybrid_orchestrator.py:16,37,105-139,230-231,278,312`）

新增 `FindingValidator` 实例（`:37`）与一个闭包 `record(finding, file_diff, context)`（`:107-129`），
两条产出路径共用它：

```python
def record(finding, file_diff, context) -> None:
    localized = localize_deterministic_finding(finding, language)   # 与原来一致：先本地化
    if localized.file == file_diff.filename:                        # 就在这个文件的上下文旁边
        evidence = self.finding_validator.validate(localized, file_diff, context)
    else:                                                           # 跨文件 finding
        evidence = self.finding_validator.validate_against_contexts(localized, file_contexts)
    all_findings.append(self.finding_validator.annotate(localized, evidence))
    validation_counts[evidence.validation_status] += 1
```

- **确定性规则产出**（阶段 4，`:131-139`）：静态规则与 AST 结论逐条 `record`，校验用的是产出它的
  那个 `(file_diff, context)`；改动前这两个循环只是 `all_findings.append(localized)`。
- **模型产出**（阶段 5，`:230-231`）：在逐文件审查循环里、`(file_diff, context)` 仍在作用域内时
  逐条 `record`，替换原来的 `all_findings.extend(result.findings)`。模型调用抛异常的分支
  `findings=[]`，不产生待校验项。
- **跨文件 finding**：模型在审查 A 时点名 B 时，`validate_against_contexts` 用 B 自己的
  `(file_diff, context)` 校验；B 不在本次审查范围（例如被过滤掉、或根本不在 PR 里）时由
  `FindingValidator` 如实记为 `invalid`，理由写在 `evidence_issues`。
- **计数落库**：`metadata["validation_summary"]`（`:312`，与标准编排器 `:361` 同键）+
  `ReviewArtifacts.validation_summary`（`:278`，与标准编排器 `:377` 同字段）。CLI 的
  `render_markdown_report`（`cli.py:1610-1622`）与 `web_server`（`:194,345,448`）因此对
  hybrid run 也能显示/返回「证据校验」区块。

**没有复制的行为**（按要求只补校验）：hybrid 仍然不建 `ReviewPlan`、不跑 `PostProcessor`、
不做跨文件接口分析、不加并发——`review_plan=None` 与原有的 `strategy/local_calls/remote_calls`
metadata 一字未动。

**语义边界**：校验只标注、不丢弃 finding（与 `FindingValidator` 的设计一致）；`unverified`
仍是「没有任何校验结论」（例如 0 条 finding），不会因为本轮改动而从计数里消失。

## 2. 块二：作者元数据

| 环节 | 位置 | 行为 |
|---|---|---|
| 写（标准） | `review_orchestrator.py:328` | `"pr_author": pr_data.author or ""` |
| 写（hybrid） | `hybrid_orchestrator.py:304` | 同上 |
| 读 | `publish_service.py:207` | `str(metadata.get("pr_author") or UNKNOWN_PR_AUTHOR)` |
| 渲染 | `report_renderer.py:656-657` | `author` 非空且不是 `"unknown"` 时才输出 `· @作者` |

- 无作者时写**空串**而不是占位符：编排器只陈述事实，占位符由发布路径决定。
- 缺失 `pr_author` 的旧 Run 仍然得到 `UNKNOWN_PR_AUTHOR`，且渲染器早已跳过 `"unknown"`，
  所以评论里**不会**出现 `@unknown`（一个不存在的 GitHub 用户名）。
- `pr_author` 与 `pr_title`、`fork` 一样走 `metadata_json` 列，**不加数据库列**，历史库照旧可读。

## 3. 块三：发布时间标 UTC

`publish_service.py:152-170` 新增 `_format_reviewed_at`，`load_target` 用它填
`GitHubCommentMeta.reviewed_at`（`:308`，替换原来的 `str(run.get("created_at") or "")`）。

| 输入（SQLite `created_at`） | 输出 |
|---|---|
| `2026-09-25 06:39:28`（`CURRENT_TIMESTAMP`，UTC 无标记） | `2026-09-25 06:39:28 UTC` |
| `2026-09-25T06:39:28Z` | `2026-09-25 06:39:28 UTC` |
| `2026-09-25T06:39:28+08:00`（已带时区） | `2026-09-24 22:39:28 UTC`（换算，不重复贴标记） |
| `not a timestamp` / `""` / `None` | 原样返回（`None`→`""`），不抛异常 |

`runs.created_at` 由 `result_store.py:324` 的 `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` 写入，
SQLite 的 `CURRENT_TIMESTAMP` 就是 UTC，因此补标 `UTC` 是陈述事实而非猜测；UTC+8 的读者不会再
把 06:39 读成本地时间。

## 4. 测试

| 文件 | 新增用例 |
|---|---|
| `tests/test_review_orchestrator.py` | `test_hybrid_run_validates_model_and_static_findings`（真实校验器 + 带 `full_content` 的上下文桩：模型与静态规则产出得到 `valid`/`needs_review`/`invalid` 三态，7 条 finding 全部保留并带 `finding_id`/`evidence`，计数同时写进 artifacts 与 metadata）、`test_hybrid_validates_a_finding_against_the_file_it_points_at`（跨文件 finding 用目标文件的上下文校验；目标不在范围内记 `invalid`）、`test_standard_orchestrator_records_the_pr_author`、`test_hybrid_orchestrator_records_the_pr_author`、`test_orchestrators_record_a_missing_author_as_an_empty_string` |
| `tests/test_jsonl_backend.py` | `test_pr_author_metadata_survives_the_database_round_trip`、`test_publish_mentions_the_stored_pr_author`（评论出现 `@alice`）、`test_publish_of_a_run_without_pr_author_never_mentions_an_unknown_user`（字面冻结 `UNKNOWN_PR_AUTHOR == "unknown"`，且断言 `@unknown` 不出现）、`test_publish_marks_the_stored_review_time_as_utc`（端到端：`审查于 <时间> UTC`）、`test_reviewed_at_formatter_marks_utc_and_never_raises`、`test_publish_keeps_an_unparseable_stored_time_verbatim`（直接改库里的 `created_at` 为坏值，发布仍成功且原样展示） |

**反向验证（变异检查，防止用例假绿）**：临时把 hybrid 的 validate/annotate 回退成
`all_findings.append(localized)`、并把发布路径的作者与时间改回旧写法，重跑上述 5 个核心用例 →
**4 failed, 1 passed**（唯一通过的是直接测 `_format_reviewed_at` 的纯函数用例，它不经过
`load_target`，符合预期）；随后逐字还原改动。

## 5. 本地端到端实测（离线，无网络、无发布）

用真实 `FindingValidator` + 桩模型/桩规则跑一次 hybrid 审查，落库后再走发布路径重新渲染
（产物：`.pytest_x/p6_hybrid_evidence_sample.txt`，脚本用桩 AIClient，未联网、未向 GitHub 发任何请求）：

```text
== hybrid run (real FindingValidator, stub model+rules) ==
run_id             : ac8a5ca0
validation_summary : {'valid': 5, 'needs_review': 1, 'invalid': 1}
pr_author          : 'alice'
  valid        Static rule issue in src/file_0.py      # 静态规则产出同样被校验
  valid        Static rule issue in src/file_1.py
  valid        Static rule issue in src/file_2.py
  valid        Static rule issue in src/file_3.py
  valid        Model issue in src/file_0.py
  needs_review Model issue in src/file_1.py            # 行号不在变更行上
  invalid      Model issue in src/file_2.py            # 行号超出该文件内容

== published comment body (selected lines) ==
**`owner/repo`** · [PR #42](…/pull/42) · Concurrent review · @alice · 4 个变更文件 · 已审查 4/4 个文件
> **证据校验（位置与片段自洽）** ✅ 校验通过 5 · 🔍 待人工确认 1 · ⛔ 校验不成立 1 · ❔ 未校验 0
> 审查于 2026-09-25 06:48:42 UTC · 模型 `…` · run `ac8a5ca0` · 耗时 0.1s
```

对照缺陷现象：同一渲染路径上的「校验通过 0 / 未校验 N」变成真实的 5/1/1/0，作者与 UTC 标记也都出现。

## 6. 未决项 / 边界

1. **两条评论路径的 UTC 写法不完全一致**：会话内 `--publish-comment`（`cli.py:1642`）是
   `datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")`（到分钟），历史发布路径本轮改为
   `2026-09-25 06:39:28 UTC`（到秒，与任务要求的示例格式一致）。两者都标 UTC，但秒的精度不同；
   统一格式需要改 `cli.py`（不在本任务写入范围），留给集成方决定。
2. **`web_server.py:448` 的 `metadata["validation_summary"]`** 无需改代码：本轮之后 hybrid run
   开始写入该键，Web API 会自动从 `{}` 变成真实计数；未做端到端 Web 验证（不在写入范围）。
3. **校验强度不变**：`FindingValidator` 只证明「位置 + 片段自洽」，不代表问题真实成立；评论正文里
   的徽章文案（校验通过 / 待人工确认 / 校验不成立 / 未校验）沿用 P6 词汇表，未新增措辞。
4. **未对线上 PR 做真实发布验证**：本轮只跑离线测试与本地渲染，证据均为本地可复现命令。
5. **hybrid 仍不复制标准编排器的其它能力**：不做跨文件接口分析（`cross_file_impacts` /
   `interface_impacts` 仍为空）、不跑 `PostProcessor`、不建 `ReviewPlan`——本轮只补证据校验。
