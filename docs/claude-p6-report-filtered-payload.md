# P6 交付报告：报告载荷与 review.completed 事件携带过滤信息（任务 `claude-p6-report-filtered-payload`）

**一句话结论**：`build_report_payload` 的 `run` 段现在带上 `filtered`（`threshold` /
`below_threshold` / `duplicates`，来自 `ReviewArtifacts.filtered_findings` 的实测值），
`review.completed` 事件把同一份块原样透出，`/history <run_id>` 的报告也从
`metadata["filtered_findings"]` 补上同一块；三者与 GitHub 评论审计行共用
`comment_filter_disclosure` 这一份归一化。没有记录到统计的 run **省略 `filtered` 键**，
绝不写 `0` 或空占位——TUI（`frontend/tui/src/empty-findings.ts`）据此在 0 findings 时
渲染「模型给出 N 条候选，但都低于置信度门槛 X，已过滤。」。

- 任务类型：实现（可写 `src/ai_pr_review/cli.py`、`src/ai_pr_review/backend/jsonl_server.py`、
  `tests/test_cli.py`、`tests/test_jsonl_backend.py`、本文件）
- 验证命令：`New-Item -ItemType Directory -Force -Path .pytest_x` → `TEMP`/`TMP` 指向它 →
  `python -m pytest -q --no-cov`
- 结果：**613 passed, 1 skipped in 84.44s**（最终代码复跑；本轮新增 7 个用例：`tests/test_cli.py`
  4 个 + `tests/test_jsonl_backend.py` 3 个；改动前基线按同一套用例计为 606 passed / 1 skipped
  = 613 − 7，未单独复跑基线）
- 未做：未读/打印凭据，未执行任何 git 操作，未改 `frontend/tui`（只读契约），未改 write_scope
  之外的文件（含 `docs/claude-review-events.md`、`docs/review-workspace-contract.md`），
  未联网、未向任何 PR 写入内容

## 1. 缺陷（改动前实测）

| 证据 | 命令/位置 | 结果 |
|---|---|---|
| TUI 已读 `report.run.filtered.{threshold,below_threshold}` | `frontend/tui/src/app.tsx:2544,2556-2557` → `frontend/tui/src/empty-findings.ts:45-55` | 契约先于实现落地 |
| 报告载荷没有这两个字段 | `cli.py:1545-1550`（改动前）`payload["run"] = {id, duration_seconds, total_cost, validation}` | 只有 4 个键 |
| 数据其实一直在 | `review_orchestrator.py:125,367`、`hybrid_orchestrator.py:296,332`：`filtered_findings` = `PostProcessor.process_with_stats` 的计数 | 已实测、已落库，只是没进报告 |
| 事件也没有 | `jsonl_server.py:151-158`（改动前）`review.completed` 只有 files/severity/evidence/cost/duration | TUI 需重新取报告才能解释 0 findings |

后果：门槛把候选全部过滤掉时，TUI 只能说「本次审查未发现问题」，说不出「模型给过 N 条候选、
被门槛 X 过滤」——用户会以为模型什么都没看出来。

## 2. 实现

### 2.1 报告载荷（`cli.py`）

新增 `report_filtered_section(stats)`（`cli.py:1534-1552`）：复用评论路径的
`comment_filter_disclosure`（`publish_service.py:176-202`），只保留值非 `None` 的键。
`build_report_payload` 在 `run` 段条件挂载（`cli.py:1572-1577`）：

```python
filtered = report_filtered_section(artifacts.filtered_findings)
if filtered:
    payload["run"]["filtered"] = filtered
```

| 输入（`artifacts.filtered_findings`） | `payload["run"]` |
|---|---|
| `{"before":5,"after":2,"below_threshold":3,"duplicates":0,"threshold":0.7,...}` | `filtered: {"threshold":0.7,"below_threshold":3,"duplicates":0}` |
| `{"below_threshold":2,"duplicates":0}`（旧 run 没记门槛） | `filtered: {"below_threshold":2,"duplicates":0}`（不补门槛） |
| `{}` / `None` / `"not-a-dict"` / 值全是非数字 | **无 `filtered` 键** |

`threshold` 来自 stats 里 PostProcessor 实际应用的门槛（`post_processor.py:67`），
不是当前配置——历史 run 复现时披露的是当年生效的值。

### 2.2 `review.completed` 事件（`jsonl_server.py`）

`_review_completed_fields`（`jsonl_server.py:128-170`）把报告里的 `run.filtered`
**原样透传**（`:167-169`），不重新推导——事件与报告必须逐字一致；缺块时事件里也没有该键：

```python
filtered = run.get("filtered")
if isinstance(filtered, dict) and filtered:
    fields["filtered"] = dict(filtered)
```

**加法式扩展**：`run_id` / `finding_count` / `files_reviewed` / `files_skipped` /
`severity` / `evidence` / `cost` / `duration_seconds` 的键名与语义一字未动。

### 2.3 `/history` 报告（`jsonl_server.py`，同一“报告载荷”概念的补齐）

`_history_detail`（`:1101-1154`）用同一个 `report_filtered_section` 读
`metadata["filtered_findings"]`（编排器一直有落库，`review_orchestrator.py:367`），
有则挂到 `report["run"]["filtered"]`（`:1136-1144`）。TUI 的 `/history` 路径同样把
`result.report` 当当前报告（`app.tsx:500`），不补这一块，历史 run 的 0 findings 提示
就仍然解释不了过滤。

## 3. 语义选择（任务要求“文档说明选择”）

1. **缺失时省略 `filtered` 键，不用空 dict、更不用 0。** 键在场 = 「本 run 实测过」，
   键缺失 = 「未记录」，两者不混淆；`{"below_threshold": 0}` 会对一个根本没跑后处理的
   run 断言「什么都没被过滤」，这正是评论渲染器丢弃 `None` 片段而不打印 0 的同一条理由。
   归一化函数内部返回 `{}`，由调用方决定省略（`cli.py:1543-1544` 有注释）。
2. **保留 `duplicates`。** 与评论审计行同一词汇表（`report_renderer.py:778-779`）；
   TUI 只读 `threshold` / `below_threshold`，多一个实测计数不改变其行为。
3. **`threshold` 不读当前配置。** 与 `comment_filter_disclosure` 的 fallback 语义一致：
   只有 run 记录了计数时才可能有门槛，且必须是 stats 里那个当年生效的值。
4. **事件透传而非重算。** 事件契约是加法式的，事件与报告不允许出现两份口径。

## 4. 测试

| 文件 | 新增用例 |
|---|---|
| `tests/test_cli.py` | `test_report_payload_run_carries_the_filtered_threshold_and_counts`（`:374`：载荷含两个 TUI 字段、类型是数字、与 `comment_filter_disclosure` 同值）、`test_report_payload_never_fabricates_filtered_counts`（`:410`：空/部分/坏值三种输入都不出 `filtered`，部分输入不补门槛不补 0）、`test_cli_json_report_discloses_the_confidence_threshold`（`:431` 端到端：`--output report.json` 的 JSON 带门槛披露，`below_threshold=0` 是真实测量）、`test_cli_json_report_explains_a_zero_finding_run_filtered_by_threshold`（`:452` 端到端：门槛 0.99 → `total_findings=0` 且 `below_threshold=1`） |
| `tests/test_jsonl_backend.py` | `test_review_completed_carries_the_filtered_block`（`:1522`：事件 `filtered` 与既有字段并存，逐字断言 8 个旧字段不变）、`test_review_completed_omits_filtered_when_the_run_recorded_nothing`（`:1578`：无统计的事件没有该键；坏形状 run 段不抛异常也不补 0）、`test_history_report_carries_the_filtered_block_from_run_metadata`（`:1611`：history 报告带块，旧 run 不带） |

**既有形状测试无回归**：`test_review_completed_carries_severity_evidence_files_cost_and_duration`、
`test_review_stage_events_report_ids_progress_and_measured_durations`、
`test_history_run_becomes_the_current_report_for_report_and_export`、
`test_cli_infers_json_format_from_output_extension` 等全部原样通过（全量 613 passed）。

## 5. 变异检查（防止用例假绿）

| 变异 | 重跑用例 | 结果 |
|---|---|---|
| `cli.py` 强制 `filtered = {}`；`jsonl_server.py` 事件与 history 都不挂块（= 回退到改动前） | 上述 7 个新用例 | **6 failed, 1 passed**——通过的正是 `test_review_completed_omits_filtered_when_the_run_recorded_nothing`（它断言“缺失”，该变异只会让数据消失，符合预期）；随后逐字还原 |
| 反向变异：两个位置在无数据时伪造 `{"below_threshold": 0}` | `test_report_payload_never_fabricates_filtered_counts` + `test_review_completed_omits_filtered_when_the_run_recorded_nothing` | **2 failed**（`assert "filtered" not in ...` 直接命中）；随后逐字还原，`grep MUTATION-CHECK src` 无残留，7 用例复跑全绿 |

## 6. 本地端到端实测（离线，无网络、无凭据）

`.pytest_x/p6_report_filtered_sample.py`（产物 `:p6_report_filtered_sample.txt`）：唯一
桩是 `cli.run_review` 返回真实 `ReviewArtifacts`，stats 来自**真实 `PostProcessor`**
（门槛 0.70 / 0.99），其余路径（`JsonlBackend` → `build_report_payload` →
`review.completed` → 落库 → `/history`）全是真的：

```text
== threshold 0.70 · real PostProcessor stats ==
{"before": 3, "after": 1, "below_threshold": 2, "duplicates": 0, "threshold": 0.7, "severity_sorted": true}
review.completed.finding_count = 1
review.completed.filtered      = {"threshold": 0.7, "below_threshold": 2, "duplicates": 0}
report.run.filtered            = {"threshold": 0.7, "below_threshold": 2, "duplicates": 0}
history report.run.filtered    = {"threshold": 0.7, "below_threshold": 2, "duplicates": 0}

== threshold 0.99 · real PostProcessor stats ==
{"before": 3, "after": 0, "below_threshold": 3, "duplicates": 0, "threshold": 0.99, "severity_sorted": true}
review.completed.finding_count = 0
review.completed.filtered      = {"threshold": 0.99, "below_threshold": 3, "duplicates": 0}
report.run.filtered            = {"threshold": 0.99, "below_threshold": 3, "duplicates": 0}
history report.run.filtered    = {"threshold": 0.99, "below_threshold": 3, "duplicates": 0}
```

第二个场景正是 TUI 的目标场景：`belowThreshold=3`、`threshold=0.99` →
`empty-findings.ts:54` 渲染「模型给出 3 条候选，但都低于置信度门槛 0.99，已过滤。」
（`filteredHint` 只要求 `below_threshold > 0` 且 `threshold` 是数字）。

## 7. 未决项 / 边界

1. **事件契约文档未改**（不在写入范围）：`docs/claude-review-events.md` §2.7 的
   `review.completed` 示例仍是旧字段集，`docs/review-workspace-contract.md` §3.7 同理。
   本轮是加法式扩展，建议集成方在这两份文档补 `"filtered": {…}` 与“缺失即未记录”的说明。
2. **`filtered` 只在后处理真正跑过的 run 上出现**：`--only-fetch` / `--only-filter` /
   `dry-run` 等路径不经过 `PostProcessor`，因此报告里没有该键——这是刻意的（见 §3.1），
   不是遗漏。
3. **前端未验证**：未运行 `frontend/tui` 的测试或构建（不属于本任务写入范围，且禁止改动），
   TUI 侧行为只以 `empty-findings.ts` / `app.tsx` 的既有实现为契约依据。
4. **`web_server.py` 的 JSON 报告路径没有跟着变**：它自己拼 `run` 段
   （`web_server.py:199-203`，只有 id/duration_seconds/total_cost），不经过
   `build_report_payload`，因此 Web API 的载荷仍无 `filtered`；本轮未改（不在写入范围）。
   需要 Web 端同样披露时，应让它复用 `report_filtered_section`（`cli.py:1534`）。
5. **门槛精度**：`threshold` 是 stats 记录的 float（如 `0.7`），TUI 以 `toFixed(2)` 展示；
   本轮的单元测试用的是 0.7 / 0.85 / 0.99 等可精确表示的用例，未覆盖浮点表示异常值。
