# P6 收尾交付报告：hybrid 路径补上 PostProcessor（任务 `claude-p6-hybrid-postprocess`）

**一句话结论**：`PostProcessor` 抽出可复用的统计入口 `process_with_stats(result) -> (ReviewResult, stats)`，
`process()` 改为委托它；`cli.run_review` 默认走的 `HybridReviewOrchestrator` 在写库前调用**同一个入口、
同一份 `app_config.post_processor`**，置信度门槛 / 去重 / 严重程度排序因此对默认路径生效；计数写进
`metadata["filtered_findings"]` 与 `ReviewArtifacts.filtered_findings`。离线实测：同一份模型产出
（0.95 / 0.55 / 0.50）修复前会把三条全部写进报告，修复后只保留 0.95 那条。

- 任务类型：实现（可写 `services/post_processor.py`、`services/review_orchestrator.py`、
  `services/hybrid_orchestrator.py`、`tests/test_review_orchestrator.py`、本文件）
- 验证命令：`New-Item -ItemType Directory -Force -Path .pytest_x` → `TEMP`/`TMP` 指向它 →
  `python -m pytest -q --no-cov`
- 结果：**593 passed, 1 skipped**（基线 589 passed, 1 skipped；本轮新增 4 个用例，全部在
  `tests/test_review_orchestrator.py`）
- 未做：未读/打印凭据，未执行任何 git 操作，未修改 write_scope 之外的文件（含 `cli.py`、
  `web_server.py`、`frontend/tui`、`web/`、`tests/test_cli.py`、`tests/test_post_processor.py`），
  未联网、未向任何 PR 写入内容

## 1. 缺陷（改动前实测）

| 证据 | 命令/位置 | 结果 |
|---|---|---|
| hybrid 无门槛/去重逻辑，也从不调用 PostProcessor | 本轮改动前的 `hybrid_orchestrator.py` 全文（324 行）不含 `confidence` / `PostProcessor`；同仓 `docs/claude-p6-hybrid-evidence-author.md:61,148` 亦记录「hybrid … 不跑 `PostProcessor`」 | 无调用路径 |
| PostProcessor 只在标准路径被构造/调用 | 改动前 `review_orchestrator.py:139`（构造）、`:298`（`process`） | 仅标准路径 |
| 默认走的是 hybrid | `cli.py:1361,1378-1381`：`use_hybrid: bool = True`；`cli.py:2482` 调用时不传 `use_hybrid`；`preferences.hybrid_strategy` 是 `PreferencesConfig` 的固定字段（`config.py:592`） | 恒为 hybrid |
| 默认门槛就是用户配置的 0.6 | `config.py:752`：`PostProcessorConfig.confidence_threshold: float = 0.6` | 门槛被整个绕开 |

后果：`metadata.filtered_findings` 为空、`ReviewArtifacts.filtered_findings` 为空，0.50/0.55 的
低置信度 finding 直接进入报告与 GitHub 评论（见 §6 的修复前后实测）。

## 2. 实现

### 2.1 共用入口（`services/post_processor.py:25-70`）

```python
def process(self, result: ReviewResult) -> ReviewResult:
    return self.process_with_stats(result)[0]                      # 行为逐字不变

def process_with_stats(self, result) -> tuple[ReviewResult, dict[str, Any]]:
    above_threshold = self.filter_by_confidence(result.findings, threshold=self._config.confidence_threshold)
    deduplicated    = self.deduplicate(above_threshold)
    findings        = self.sort_by_severity(deduplicated)
    payload = result.model_dump(); payload["findings"] = [f.model_dump() for f in findings]
    return ReviewResult.model_validate(payload), { ...stats... }
```

- 三步流水线（门槛 → 去重 → 排序）只有这一份实现；`process()` 的返回对象与改动前逐字段相同。
- `process_with_stats` 不就地修改入参：返回新的 `ReviewResult`，`result.findings` 保持原样。

返回的 `stats` 只陈述事实，不估算：

| 键 | 含义 |
|---|---|
| `before` | 进入后处理的 finding 条数 |
| `after` | 后处理之后剩下的条数 |
| `below_threshold` | 因 `confidence_threshold` 被丢弃的条数 |
| `duplicates` | 被去重规则（默认 `file + category + line_start // 10`）合并掉的条数 |
| `severity_sorted` | 返回的 finding 确实按严重程度有序（对结果的自检，不是声明） |

### 2.2 两条路径共用

| 路径 | 调用点 | 结果 |
|---|---|---|
| 标准编排器 | `review_orchestrator.py:301` `self._post_processor.process_with_stats(raw_result)` | 由 `process()` 换成共用入口，返回值与改动前一致 |
| hybrid 编排器 | `hybrid_orchestrator.py:41` 构造 `PostProcessor(config=config.post_processor)`；`:258` 在写库前 `process_with_stats` | 本轮新增：门槛/去重/排序对默认路径生效 |

- artifacts 暴露：`ReviewArtifacts.filtered_findings`（`review_orchestrator.py:125`，两条路径共用同一
  dataclass）。`ReviewArtifacts` 里没有等价字段可复用——`validation_summary` 是 `FindingValidator`
  的**证据**三态计数（valid/needs_review/invalid），与「后处理丢了多少条」是两件事，因此新增字段而
  不是塞进旧字段。
- run metadata：两侧都写 `"filtered_findings"`（标准 `review_orchestrator.py:367`、hybrid
  `hybrid_orchestrator.py:332`），与 artifacts 同源同值；走 `metadata_json` 列，不加数据库列。
- hybrid 的 summary 计数改为后处理之后的真实条数（`hybrid_orchestrator.py:284`）：门槛滤掉噪音之后
  标题仍写「发现 3 个问题」会与正文自相矛盾。

## 3. 测试（`tests/test_review_orchestrator.py`）

| 用例 | 断言 |
|---|---|
| `test_hybrid_orchestrator_drops_findings_below_the_configured_threshold` | 门槛 0.6：0.85 保留、0.50 丢弃；`filtered_findings == {before:2, after:1, below_threshold:1, duplicates:0, severity_sorted:True}`（artifacts 与 run metadata 同值）；summary 只报 1 条 |
| `test_hybrid_reports_nothing_when_the_only_finding_is_below_the_threshold` | 任务指定的用例：门槛 0.6 + 0.55 的 finding → `findings == []`、`below_threshold == 1`、`after == 0`，metadata 记 `below_threshold=1` |
| `test_hybrid_and_standard_paths_post_process_identically` | 同一输入（5 条：1 条低置信度、1 对同键重复、critical/high 各 1）跑两条路径 → finding 顺序 `[(critical), (high), (medium duplicate better)]` 与 stats 完全一致，两侧 metadata 也一致 |
| `test_post_processor_process_still_applies_threshold_dedup_and_severity_sort` | `process()` 与 `process_with_stats()[0]` 相等，仍做门槛/去重/排序，入参不被就地修改 |

既有用例继续覆盖 `process()` 的原有语义：`tests/test_post_processor.py` 5 个用例与
`tests/test_review_orchestrator.py` 的编排器用例一字未改即通过（`StubPostProcessor` 增加
`process_with_stats` 透传实现，保证桩不改变 finding、也不谎报计数）。

**反向验证（变异检查，防止用例假绿）**：临时把 hybrid 的 `process_with_stats(...)` 换回
`(ReviewResult(summary="", findings=all_findings), {})`（即修复前的行为），只跑上述 4 个用例 →
**3 failed, 1 passed**（唯一通过的是纯 `PostProcessor` 用例，它不经过编排器，符合预期）；
随后逐字还原。

## 4. 本地端到端实测（离线，无网络、无发布）

桩模型对同一个文件返回 0.95 / 0.55 / 0.50 三条 finding，分别跑「修复前」（后处理透传）与
「修复后」（真实 `PostProcessor`，`confidence_threshold=0.6`）；产物
`.pytest_x/p6_hybrid_postprocess_sample.txt`：

```text
== hybrid BEFORE (no PostProcessor) -- 用户配置的 0.6 被忽略 ==
summary           : 审查完成，发现 3 个问题
published findings: [('Real issue', 0.95), ('Shaky guess', 0.55), ('Coin flip', 0.5)]
filtered_findings : {}
metadata          : {}
== hybrid AFTER  (process_with_stats, threshold=0.6) ==
summary           : 审查完成，发现 1 个问题
published findings: [('Real issue', 0.95)]
filtered_findings : {'before': 3, 'after': 1, 'below_threshold': 2, 'duplicates': 0, 'severity_sorted': True}
metadata          : {'before': 3, 'after': 1, 'below_threshold': 2, 'duplicates': 0, 'severity_sorted': True}
```

对照缺陷现象：0.55/0.50 两条不再落库、不再进报告，且「丢了 2 条」这件事在 run metadata 里可查。

## 5. 未决项 / 边界

1. **hybrid 直接 `from ...post_processor import PostProcessor`**（不像 `FilterPipeline` 那样走
   `standard_review.PostProcessor`）。原因是硬约束：`tests/test_cli.py:135` 的 `StubPostProcessor`
   只实现 `process`，而该文件不在本任务写入范围；若 hybrid 复用标准模块里的那个名字，CLI 的
   `main` 路径（默认 hybrid）会拿到这个桩并因缺 `process_with_stats` 抛 `AttributeError`。副作用：
   CLI 测试里 hybrid 现在跑的是**真实** PostProcessor（1 条 0.95 的 finding，门槛与去重都是恒等
   变换），`tests/test_cli.py` 全部用例一字未改即通过。
2. **`metadata.filtered_findings` 尚未被任何读取方消费**：`cli.py`（report / JSON / `--publish-comment`）
   与 `web_server.py` 都不在本任务写入范围，所以本轮只负责「如实写入」，展示留给集成方；历史 Run
   没有该键，读取方需要按缺省处理。
3. **`validation_summary` 仍是后处理之前的计数**：证据三态统计的是「校验器看过多少条」，与
   `filtered_findings` 是两条正交的事实。标准路径此前就是这个语义，hybrid 本轮照抄，未做改动。
4. **hybrid 仍不复制标准编排器的其它能力**：不建 `ReviewPlan`、不做跨文件接口分析
   （`cross_file_impacts` / `interface_impacts` 仍为空）、不加并发——本轮只补后处理。
   （`docs/claude-p6-hybrid-evidence-author.md` §6.5 的「不跑 `PostProcessor`」一条由本文件取代。）
5. **`before` 的口径**：hybrid 的 `before` 是「证据校验之后收录的条数」，即模型产出 + 静态规则产出；
   文件级 `findings_count` 回调仍只统计模型调用返回的条数（原有契约，未动）。
6. **`duplicates` 只反映去重规则的合并数**，不代表「语义重复」：同一 `(file, category, line//10)`
   桶内保留更优的一条，行为与标准路径完全一致（同一份实现）。
