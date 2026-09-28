# L3 修复建议 patch 交付报告（任务 `claude-l3-patch`）

**一句话结论**：`docs/repo-aware-review-plan.md` §6 的 L3（修复建议 patch）已落地——
`Finding` 新增可选字段 `suggested_patch`（unified diff 片段，**只展示、绝不自动提交**），
新模块 `services/patch_generator.py` 负责「生成 + 语法校验 + 一律降级」，
`preferences.suggested_patch` 开关**默认关闭**（开启 = 每条达标 finding 多一次模型调用），
集成在**标准编排器 `ReviewOrchestrator`**（理由见 §4.2）。写库前的每条 finding 都带上了
`evidence_status` 与（达标时的）补丁，run metadata 记录 `suggested_patches` 统计与 token 用量。
`tests/test_patch_generator.py`：**90 passed**；全量 **1026 passed, 1 skipped in 87.36s**（见 §6）。

- 任务类型：实现（写入范围：`src/ai_pr_review/services/prompt_assembler.py`、
  `src/ai_pr_review/services/patch_generator.py`、`src/ai_pr_review/services/review_orchestrator.py`、
  `src/ai_pr_review/services/hybrid_orchestrator.py`、`src/ai_pr_review/config.py`、
  `tests/test_patch_generator.py`、本文件）
- 验证命令：`New-Item -ItemType Directory -Force -Path .pytest_claude` → `TEMP`/`TMP` 指向它 →
  `python -m pytest -q --no-cov`
- 未做：未改 `hybrid_orchestrator.py`（选改动更小的标准编排器，见 §5，该文件按写集允许但未改动）；
  未改 `frontend/tui`（展示层后续任务）；未改 `report_renderer.py` / `ai_client.py`（不在写集，见 §5、§7）；
  未读/打印凭据；未执行任何 git 操作；未联网（全部测试与联调用 stub）

## 1. 交付物一览

| # | 任务要求 | 落地位置 |
|---|---|---|
| 1 | `Finding.suggested_patch: str = ""`（可选、不进必填） | `prompt_assembler.py:176`；schema 剔除清单 `:143`；空值不落 payload `:178-190` |
| 2 | `PatchGenerator`（client/provider 注入 + `max_attempts=1`） | `patch_generator.py:262` |
| 2 | `generate(finding, file_context) -> str`（异常一律 `""`） | `patch_generator.py:299`（用量统计 `:336`） |
| 2 | `is_valid_unified_diff(text) -> bool`（独立函数，便于单测） | `patch_generator.py:164`（`validate_unified_diff` `:99` + `extract_unified_diff` `:169`） |
| 3 | `preferences.suggested_patch: bool = False` + `normalize_suggested_patch` | `config.py:640` / `:772` / `:826` / `:843`（共享 `_normalize_bool_preference` `:784`） |
| 4 | 写库前对达标 finding 生成并写回 + metadata 统计 + 关闭时零构造零调用 | `review_orchestrator.py:412-414`（接线）、`:503-605`（实现）、`:485`（metadata） |
| 5 | 报告 JSON 自动带字段（`model_dump` 确认） | `result_store.py:110` `result.model_dump_json()`，用例 `test_the_patch_reaches_the_persisted_review_result` |
| 6 | 测试（校验通过/拒绝/降级/达标过滤/开关零调用/统计） | `tests/test_patch_generator.py`（90 个用例，见 §6） |

## 2. `Finding.suggested_patch`：可选字段，但**不交给模型**

```python
# prompt_assembler.py:170-176
    rule_id: str = ""
    # L3 修复建议（docs/repo-aware-review-plan.md §6）：unified diff 片段，默认空。
    # 可选字段——旧 run / 未生成的 finding 不带它也能校验通过；只由
    # PatchGenerator 在写库前对 critical/high 且 evidence_status=="valid" 的
    # finding 填写，只展示、绝不自动提交。
    suggested_patch: str = ""
```

- **可选**：有默认值 → 不在 pydantic 的 `required` 里；模型返回的 JSON 不带这个键、
  旧 run 里没有这个键，`ReviewResult.model_validate` 都照常通过（用例
  `test_defaults_to_empty_and_stays_optional`）。
- **同时把它加进了 `SERVER_SIDE_FINDING_FIELDS`**（`prompt_assembler.py:134-144`）：
  该模块的既有惯例是「服务端字段保留在 `Finding` 上供服务端写入，但不暴露给模型」
  （`finding_id` / `sources` / `evidence*` / `rule_id` 同款）。两条理由：
  1. 任务原文的要求是「让该字段**可选**（不加进必填）」——剔除出 schema 天然满足
     （既不在 `properties` 也不在 `required`）；
  2. 若把 `suggested_patch` 摆进交给模型的 schema，模型就会**自述补丁**：真正的
     「只对 critical/high 且 valid 生成」这条不变量会被绕过（`ai_client.py` 的
     `_normalize_model_findings` 不在本任务写集，无法在那里清除模型自述值）。
     编排器侧另有一道防线：`_clear_suggested_patches`（`review_orchestrator.py:589`）
     把非本次生成的 `suggested_patch` 一律清空——**不管开关是开是关**。
- 冻结式断言：`"suggested_patch" not in finding_schema["properties"]`、
  `not in finding_schema["required"]`、`not in json.dumps(schema)`、
  `not in build_system_prompt("python")`（用例
  `test_the_model_facing_schema_neither_exposes_nor_requires_it`）。
- **空值不落进 payload**（`@model_serializer(mode="wrap")`，`prompt_assembler.py:178`）：
  `suggested_patch` 为空时序列化结果里**没有这个键**，有值时照常带上。理由：
  `pr-review demo --json-output`、历史 Run、报告 payload 都有**字节级冻结快照**
  （`tests/test_cli.py:2457` 的 `DEMO_JSON_SHA256`，其注释记录了 P6 加 `rule_id`
  时也让这些哈希变过），而 `Finding` 是被直接 `model_dump()` 进 payload 的
  （`services/demo_runner.py:108`）。省略 = 「本次没有补丁建议」，语义完整，
  且对新旧 payload 双向兼容（用例 `test_an_empty_patch_is_left_out_of_the_payload`）。

## 3. `PatchGenerator`：生成 → 校验 → 降级

### 3.1 构造与调用面

```python
PatchGenerator(client=None, *, complete=None, max_attempts=1,
               max_context_chars=8000, max_diff_chars=2000,
               max_tokens=1200, timeout_seconds=60.0)
```

- `client` 可以是 **provider 形态**（自带 `await chat(...)`）或 **AIClient 形态**
  （取 `client._provider.chat`，真编排器就是这么传的）；两者都没有 `chat` 时
  `generate` 一律返回 `""`（"拿不到模型"是降级，不是异常）。
- `complete` 是给测试的直通注入点（`async (system, user) -> str`），**不影响生产路径**。
- `max_attempts=1`（默认）= 不重试：模型两次都写不出合法 diff 的场景极少靠重试挽回，
  而重试是实打实的第二次计费。要重试可在构造时显式提高。
- 可观测状态：`calls` / `invalid_outputs` / `input_tokens` / `output_tokens` +
  `usage_stats()`；编排器把它们写进 metadata（§4）。

### 3.2 语法校验（`is_valid_unified_diff` / `validate_unified_diff`）

只做**语法**层检查（≈ `git apply --check` 会先过的那层解析），不保证一定能应用成功：

| 规则 | 拒绝的例子 |
|---|---|
| 至少一个可解析的 `@@ -a,b +c,d @@` hunk 头 | `-old\n+new`（缺 `@@`）、`@@ -1 +1`（缺结尾 `@@`）、`@@ garbage @@` |
| 至少一条 `+`/`-` 变更行 | 只有上下文行的 hunk |
| 每段 hunk 的**行数与头部声明一致**（上下文/删除计旧行，上下文/新增计新行，`\ No newline` 不计） | `@@ -1,5 +1,5 @@\n-a\n+b`（半截/被截断的输出） |
| hunk 内只允许 ` ` / `+` / `-` / 空行 / `\ No newline at end of file` | `?weird`、夹在 hunk 中间的散文、`\ 随便写的反斜杠行` |
| hunk 之外只允许**形状合法**的 diff 头部（`diff --git a/x b/x` / `index <hex>..<hex>` / 六位 mode / `similarity index N%` / `rename|copy from|to …` / `Binary files … differ` / `--- <path>` / `+++ <path>`） | 前缀 `Here is the patch:`、后缀 `This change fixes the bug.`、JSON 包装、`index of the bug is 3`（只判前缀会漏） |
| 整段输出被一对 ```` ``` ```` 围栏包住时先剥围栏（围栏不是解释文字）再判；收尾围栏必须**顶格** | 围栏**之外**还有散文的照样拒绝 |
| 行分隔只认 CRLF/CR/LF（不用 `str.splitlines()`，它会在 `\x0b`、U+2028 等处断行） | `@@ -1,2 +1,2 @@\n def f():\x0b-a\n+b` |
| 返回值**规范化**：剥围栏 + 换行统一成 LF | —（落库的一定是规范形式） |

- `is_valid_unified_diff(text) -> bool` 是薄封装；`extract_unified_diff(text) -> str`
  返回**剥离围栏后**的文本（合法）或 `""`（非法）——编排器写入的就是这个返回值，
  所以落库的补丁一定通过过校验。
- 非字符串输入（`None` / 数字 / list / dict）一律 `False`，不抛异常。

### 3.3 降级（绝不中断审查）

| 场景 | 行为 |
|---|---|
| 模型调用抛异常 | 记 warning，按 `max_attempts` 决定是否再试，最终返回 `""` |
| 模型输出不是合法 diff | 计入 `invalid_outputs`，重试或返回 `""` |
| prompt 组装抛异常（自定义 finding 替身等） | 外层兜底 `except Exception` → `""` |
| 没有可用的模型调用面 | 直接 `""`（`calls` 不增加） |
| 用户取消（`asyncio.CancelledError`，`BaseException`） | **不吞**，照常向上传播（编排器转成 `ReviewCancelled`，不写库） |

## 4. 开关与编排器集成

### 4.1 `preferences.suggested_patch`（默认关闭）

- `DEFAULT_SUGGESTED_PATCH = False`（`config.py:640`）；`normalize_suggested_patch`
  沿用既有惯例（`config.py:772`）：接受 `bool` / `0|1` / `"true|false|yes|no|on|off|1|0"`，
  **非法值只回退 `False` + 一次 `RuntimeWarning`，绝不抛异常**。
  与 `normalize_symbol_locate` 共用新抽出的 `_normalize_bool_preference`
  （`config.py:784`；后者行为逐字不变，已回归）。
- **默认关闭的理由**（写进字段注释与 `DEFAULT_SUGGESTED_PATCH` 注释）：开启后每条达标
  finding 都会额外发起一次模型调用（真实成本），只有用户明确开启才跑。
- 旧配置（没有这个键）静默加载为 `False`；`save()` → `load()` 往返保真（§6 用例）。

### 4.2 为什么集成在 `ReviewOrchestrator`（标准编排器），而不是 hybrid

任务要求「选改动更小的编排器，在文档说明理由」。选**标准** `ReviewOrchestrator`：

| 维度 | `ReviewOrchestrator`（**选它**） | `HybridReviewOrchestrator` |
|---|---|---|
| 模型客户端 | run 级**单一** `ai_client`（`review_orchestrator.py:321`），补丁调用直接复用它 | 逐文件临时构造 `selected_client`（`hybrid_orchestrator.py:374`），补丁调用要先再选一次 provider/model |
| 上下文可得性 | `file_contexts` 与「finding.file → 上下文」映射就在写库点上方（`:322-401`） | 同样有 `file_contexts`，但客户端选路要额外写一套 `_client_config_for` 逻辑 |
| 成本记账 | `total_cost` 取自同一个 `ai_client.total_run_cost`（`:418`） | 逐文件累加 + `model_selector.record_cost`，补丁调用要单独接一条链路 |
| 使用面 | `review_entry.py` / `web_server.py` / `web_jobs.py` 都走它 | `cli.run_review` 的默认路径 |

结论：标准编排器只需「在写库前插一个步骤 + 读一个开关」，hybrid 还要额外解决
「这条补丁用哪个 provider 生成、成本记到哪」——**改动明显更大**。任务写集里同时给了
两个编排器，允许选其中改动更小的一个；`hybrid_orchestrator.py` 因此**一个字未改**。
未覆盖 hybrid 路径这一点已列进 §7 未决项。

### 4.3 接线（`review_orchestrator.py:409-414`）

```python
review_result, suggested_patch_stats = await self._attach_suggested_patches(
    review_result, file_contexts, ai_client, cancel_check
)
stage("persisting", "正在写入本地 SQLite 历史与反馈数据")
```

- **写库前**、**后处理之后**：先过置信度门槛/去重，再对**留下的** finding 生成补丁——
  被门槛滤掉的 finding 不会白花一次调用。
- 达标判定 `is_patch_eligible`（`patch_generator.py:175`）：`severity ∈ {critical, high}`
  且 `evidence_status == "valid"`（大小写/空格不敏感）。
- 每条达标 finding 的调用都经 `call_with_cancellation`（与逐文件审查同一套取消语义）：
  用户取消 → 抛 `ReviewCancelled` → 不写库。找不到该文件的上下文（模型点名了本次没审的文件）
  → 如实计入 `patches_skipped`，不猜。
- **刻意不新增 stage id**：CLI（`cli.py:1429`）与后端（`jsonl_server.py:58`）的 stage 标签表
  都不在本任务写集内，未知 id 会显示成裸 id 且进度条回退（`stage_ranges.get(stage, (0, 0))`）。
  补丁生成发生在 `persisting` 之前，事实由 run metadata 记录。

### 4.4 metadata 统计（`review_orchestrator.py:485`）

```json
"suggested_patches": {
  "enabled": true, "candidates": 2, "patches_generated": 1,
  "patches_skipped": 1, "calls": 2, "patches_invalid": 1,
  "input_tokens": 1000, "output_tokens": 120
}
```

- `candidates` = 达标 finding 数；`patches_generated` / `patches_skipped` = 实际写入/放弃的条数；
  `calls` = 真实模型调用次数；`patches_invalid` = 模型返回了但不合法的次数；
  `input_tokens` / `output_tokens` = provider 自报用量（不报就记 0，不编造）。
- **开关关闭时这些数字必须全为 0**（`enabled: false`），便于审计"确实一分钱没花"。

## 5. 展示层：只在 JSON 层提供，markdown / GitHub 评论不变（决定与理由）

- **报告 JSON payload 自动带上该字段**（确认）：`ResultStore.save_result` 用
  `result.model_dump_json()`（`result_store.py:110`）整包落库，`suggested_patch` 无需任何渲染层改动
  （用例 `test_the_patch_reaches_the_persisted_review_result` 解 JSON 后逐字断言）。
  没有补丁的 finding 不带这个键（见 §2 最后一条），所以既有 payload 形状除"多了一个可选键"外零变化。
- **markdown / GitHub 评论不展示补丁**，`report_renderer.py` **一个字未改**。三条理由：
  1. `report_renderer.py` 不在本任务写集内，加渲染属于越界；
  2. 评论会显著变长：每条 critical/high 多一个 diff 代码块，GitHub 评论有长度上限
     （既有实现已为此做了折叠阈值 `_GITHUB_FOLD_THRESHOLD`）；
  3. 补丁是"给人看、让人自己判断要不要用"的东西，JSON 层（报告/工作台/history）已经能取到。
- 后续若要在卡片里展示，建议**折叠**呈现（`<details>`），与既有长文本折叠同一套做法——
  这是展示层任务（TUI/评论格式）的事，见 §7。

## 6. 测试与证据

命令：`New-Item -ItemType Directory -Force -Path .pytest_claude` → `TEMP`/`TMP` 指向它 →
`python -m pytest -q --no-cov`。

| # | 命令 | 结果 |
|---|---|---|
| 1 | `python -m pytest -q --no-cov tests/test_patch_generator.py` | **90 passed in 0.73s** |
| 2 | `python -m pytest -q --no-cov`（全量） | **1026 passed, 1 skipped in 87.36s**（基线改动前实测 **936 passed, 1 skipped**；新增 90 = 本文件 90） |
| 3 | 定向回归（改动点所在文件） | `test_cli.py::test_demo_json_output_is_byte_identical_to_the_shared_builder` + `test_patch_generator.py` + `test_prompt_assembler.py` + `test_review_orchestrator.py` + `test_config.py` + `test_result_store.py` → **301 passed in 5.55s** |

`1 skipped` 是仓库既有那条，与本次改动无关。全量数字里含本文件的 90 个用例，
既有 936 个用例全部原样通过（见本节末「未回归」）。

`tests/test_patch_generator.py`（90 个用例）：

| 分组 | 用例 | 断言要点 |
|---|---|---|
| diff 校验通过 | `test_valid_unified_diffs_are_accepted[8 组]` | 裸 hunk / 带文件头 / 省略行数 / 多段 hunk / 带函数名 / `\ No newline` / 空上下文行 / 空白包裹 |
| | `test_code_fence_around_the_whole_answer_is_stripped`、`test_a_deletion_line_starting_with_a_dash_is_not_a_file_header`、`test_crlf_is_accepted_and_normalized_to_lf` | 围栏剥离；hunk 内 `--- x` 是删除行而非文件头；CRLF 接受并归一化成 LF |
| diff 校验拒绝 | `test_invalid_outputs_are_rejected[18 组]` | 空串 / 纯解释文字 / 前缀后缀与 hunk 间散文 / 缺 `@@` / 无变更行 / 行数不符 / 非法 hunk 头 / hunk 内非法行 / JSON 包装 / 围栏外散文 / **长得像头部的散文（`@@ garbage @@`、`index of the bug is 3`）** / 非法的反斜杠行 / 垂直制表符断行 |
| | `test_non_string_input_is_rejected[4 组]` | `None`/数字/list/dict 一律拒绝且不抛异常 |
| 达标判定 | `TestIsPatchEligible`（2 + 7 + 1） | critical/high × valid 才达标；medium/low/info、needs_review/invalid/unverified 全不达标；`" CRITICAL "`/`"Valid"` 归一化 |
| 生成与降级 | `TestPatchGeneratorDegradation`（10） | 合法 diff 通过并计数；解释文字 → `""` 且 `invalid_outputs+1`；调用抛异常 → `""` 不抛；`max_attempts` 有界（默认 1 不重试）；构造参数写坏（`inf`/`nan`/负数/字符串）不抛；prompt 组装异常 → `""`；无模型面 → `""` 且 `calls=0`；provider/AIClient 两种注入面；token 用量（有/无自报） |
| prompt 组装 | `TestPatchPrompts`（4） | finding 事实 + 文件内容进 prompt；**相关文件不注入**；无上下文也能组装；超长截断 |
| 配置开关 | 6 个用例函数（23 个实例） | 默认 `False` 且无告警；13 种写法不告警且解析正确；7 种非法值回退 + 告警；`save`/`load` 往返；旧配置静默加载 |
| Finding 字段 | `TestFindingField`（4） | 默认 `""`、不带该键的模型 JSON 可校验；schema 既不在 `properties` 也不在 `required` 且 prompt 里搜不到；空值不进 payload（有值才带，双向可读）；序列化往返 |
| 编排器集成 | `TestOrchestratorIntegration`（9） | 只对两条达标 finding 生成（critical 采纳 / high 放弃）；生成器拿到本 run 的 AIClient；**开关关闭零构造零调用**且模型自述补丁被清空；生成器抛异常不中断整轮；无上下文 → 跳过且 `calls=0`；模型自述 patch 被丢弃；**真 PatchGenerator + provider 形态 chat** 端到端（合法落库、带解释文字落空、medium 不生成、token 统计）；落库 payload 里逐字带补丁 |

**未回归**：既有 936 个用例原样通过，未改动一字；新增的 90 个用例全部落在新文件里。
对既有文件的改动是纯加法：`Finding` 多一个带默认值的字段（外加一个只在空值时不输出该键的
`@model_serializer`，见 §2——不加它的话 `pr-review demo --json-output` 的字节级冻结快照会红，
这一条是实测出来的：全量跑第一次就挂在 `tests/test_cli.py:2496`）、`SERVER_SIDE_FINDING_FIELDS`
多一个名字（`test_prompt_assembler.py` 的既有断言仍然通过）、`PreferencesConfig` 多一个带默认值的字段、
`ReviewOrchestrator` 多一个写库前步骤与三个方法（`_suggested_patch_enabled` / `_attach_suggested_patches` /
`_clear_suggested_patches`，外加模块级 `_stat_value` 兜底）。

**离线联调**（不联网、不 spawn TUI，脚本经 stdin 直跑，不留文件）：

```
[A] 真 PatchGenerator + provider 形态 stub
  整体围栏: patch="@@ -1,2 +1,2 @@\n def run():\n-    return True\n+    return False"  usage={'calls': 1, 'invalid_outputs': 0, ...}
  裸 diff : patch="@@ -1,2 +1,2 @@\n def run():\n-    return True\n+    return False"  usage={'calls': 1, ...}
  带解释 : patch=""  usage={'calls': 1, 'invalid_outputs': 1, ...}
  非 diff : patch=""  usage={'calls': 1, 'invalid_outputs': 1, ...}
  chat kwargs: {'max_tokens': 1200, 'timeout_seconds': 60.0, 'structured_output': False}

[B] 真 ReviewOrchestrator（开关 ON）
  findings = [{"title": "critical valid",   "severity": "critical", "evidence_status": "valid",
               "suggested_patch": "@@ -1 +1 @@\n-old\n+new"},
              {"title": "critical valid 2", "severity": "critical", "evidence_status": "valid",
               "suggested_patch": ""},                    # 模型输出带解释文字 → 拒绝
              {"title": "high out-of-range","severity": "high",     "evidence_status": "invalid",
               "suggested_patch": ""},
              {"title": "medium valid",     "severity": "medium",   "evidence_status": "valid",
               "suggested_patch": ""}]
  metadata.suggested_patches = {"enabled": true, "candidates": 2, "patches_generated": 1,
                                "patches_skipped": 1, "calls": 2, "patches_invalid": 1,
                                "input_tokens": 1000, "output_tokens": 120}
  补丁调用次数 = 2 | structured_output = {False}

[B'] 同一输入、开关 OFF
  PatchGenerator 构造次数 = 0 | 补丁调用增量 = 0
  metadata.suggested_patches = {"enabled": false, "candidates": 2, "patches_generated": 0,
                                "patches_skipped": 0, "calls": 0, "patches_invalid": 0,
                                "input_tokens": 0, "output_tokens": 0}
  suggested_patch = ["", "", "", ""]
  payload 里 suggested_patch 键 = [False, False, False, False]   # 空值不进 payload（§2/§5）
```

（`medium valid` 与 `high out-of-range` 都没有补丁：前者严重度不够，后者证据校验没过——
这正是「只对达标 finding 生成」在真实数据流上的样子。）

## 7. 未决项 / 边界

1. **hybrid 路径未集成**（刻意，见 §4.2）：`cli.run_review` 默认走 `HybridReviewOrchestrator`，
   它不生成补丁。要在那里支持，需要先回答"补丁调用用哪个 provider、成本记到哪"
   （逐文件选路/本地优先策略），工作量明显大于标准编排器——建议单独排期。
2. **补丁调用不计入 `CostController` 的预算与 `total_cost`**：`AIClient` 没有暴露纯文本补全
   接口（`review_code` 只解析 JSON finding），而 `ai_client.py` 不在本任务写集内，
   所以 `PatchGenerator` 走的是 `client._provider.chat(...)`。metadata 里的
   `input_tokens`/`output_tokens` 是这一层如实记录的用量；把它们接进成本上限是后续任务。
3. **配置入口（向导 / CLI / TUI）未加**：`config.setup`、`pr-review preferences`、
   TUI 设置页都还没有这个开关（都不在写集内）。当前只能改配置文件
   （`preferences.suggested_patch: true`）——加载路径、归一化、落盘往返都已就绪（§6 用例）。
4. **上下文是「从头部截断」而非「以 finding 行为中心取窗」**：沿用
   `PromptAssembler._truncate_text` 的既有惯例（超限截断 + `[truncated]`），
   对超大文件且 finding 靠后的场景会丢掉目标行附近的内容。改进（按行取窗）很小，
   但会让 prompt 形状多一种分支，留给后续按真实命中率决定。
5. **相关文件（L1 预取）不注入补丁 prompt**（刻意）：补丁只允许改 finding 指向的这个文件，
   把别的文件摆进上下文只会诱导模型去改它们。若将来要做"跨文件修复"，那是另一个功能。
6. **`max_attempts > 1` 未在生产路径使用**：默认 1（不重试，避免第二笔计费）；
   重试逻辑已单测覆盖，但"重试能挽回多少"没有真实数据。
7. **语法合法 ≠ 一定能应用**：校验的定位是"过 `git apply --check` 会先过的那层解析"。
   `rename to y`、`Binary files a/x and b/x differ` 这类**形状合法**的头部会被接受
   （它们确实是 git 的输出格式），但单独出现、没有 `diff --git`/`---`/`+++` 时
   `git apply` 仍可能拒绝。要变成"保证可应用"就得真的把补丁喂给 git（本任务不做，
   只展示不落盘）。
8. **多文件 diff 一律拒绝**：第二个 `---`/`+++` 出现在 hunk 之后即视为非法
   （`PATCH_SYSTEM_PROMPT` 也明令"never touch other files"）。将来若要做"跨文件修复"，
   校验器与 prompt 都要一起改。
9. **未做 git 操作、未联网、未读取或输出任何凭据**；`.pytest_claude/` 是本任务的 pytest
   临时目录（联调用的 `l3-demo/demo.db` 也在其中）。

## 8. 独立复核（只读子 agent）

交付前用只读子 agent 对着任务 prompt 逐条对拍了一遍（它不跑 pytest、不做 git 操作；
测试数字以 §6 为准）。它的结论是"无高危缺陷、无既有测试会被打破、写入范围合规"，
同时指出 4 个校验器漏洞与 3 个健壮性隐患，除 2 条明确判定为"可接受边界"外全部修掉：

| 复核发现 | 处理 |
|---|---|
| F1 只按**前缀**判断 hunk 外的头部行 → `@@ garbage @@`、`index of the bug is 3`、裸 `@@` 被当成头部接受并原样落库 | **已修**：改成按**形状**匹配（`_FILE_HEADER_PATTERNS`），`@@` 开头但不匹配 hunk 头的行直接拒；新增 4 组拒绝用例（含 `index of the bug is 3`） |
| F2 hunk 内**任何** `\` 开头的行都被当 `\ No newline at end of file` 跳过且不计数 | **已修**：只认 git 的那一串逐字匹配，其它反斜杠行拒绝；新增用例 |
| F3 剥围栏不要求成对：末行 ` ``` `（前导空格）也会被当成收尾围栏，吃掉一行上下文 | **已修**：收尾围栏必须**顶格**（`lines[-1] == "```"`）。剩下的极端情形（开围栏没有收围栏、且末行内容恰为 ` ``` `）两个方向都只能拒绝，属可接受边界 |
| F4 `str.splitlines()` 会在 `\x0b`、U+2028 等处断行 → hunk 计数被灌水 | **已修**：只按 CRLF/CR/LF 断行（`_LINE_BREAK`），返回值同时把换行归一化成 LF；新增 VT 拒绝用例与 CRLF 归一化用例 |
| F1 附带：`rename to y`、`Binary files … differ` 仍是"形状合法但未必可应用" | **保留并在 §7.7 记录**：它们确实是 git 的头部格式，本模块只承诺语法层；"保证可应用"要真的喂给 git |
| F5 多文件 diff 被拒；文档却把 `diff --git` 列为允许头部 | **文档已改**（§3.2 写明"头部只在第一个 hunk 之前"），并在 §7.8 记录为刻意行为 |
| `PatchGenerator(max_attempts=float("inf"))` 在**构造**时抛 `OverflowError`（`_as_int` 只接 `TypeError`/`ValueError`） | **已修**：`_as_int` 补上 `OverflowError`；新增用例覆盖 `inf`/`nan`/负数/字符串/`None` |
| 编排器里 `PatchGenerator(...)` 构造与 `usage_stats()` 在 `try` 之外，抛了就会中断整轮（与"绝不中断审查"的契约矛盾） | **已修**：两处都包了兜底（构造失败 → 达标条数如实记 `patches_skipped`；统计失败 → 数字记 0），`usage_stats()` 缺键也用 `_stat_value` 兜底；新增 2 个用例 |
| 开关关闭时 `ReviewResult` 对象**同一个**（`_clear_suggested_patches` 零拷贝早返回），仅 metadata 多一个键 | 确认（子 agent 实测 `is` 判定为 True）；metadata 多键是任务要求，无既有用例断言整份 metadata |
| `@model_serializer` 是纯 no-op：16 个既有字段的键集合与顺序在 `model_dump`/`mode="json"`/`model_dump_json`/嵌套/`by_alias`/`exclude*` 下逐字不变 | 确认（子 agent 实测）；唯一差异是 `model_json_schema(mode="serialization")` 会带上该字段——`src/` 里没有任何地方用序列化模式 schema，属潜在项，已在此记录 |
| 子 agent 的另一项检查：`tests/test_cli.py` 的 `DEMO_JSON_SHA256` 冻结用例、`tests/test_prompt_assembler.py` 的 schema 断言、`test_config.py` 的 `normalize_symbol_locate` 口径（重构成 `_normalize_bool_preference` 后逐字不变）都不会因本次改动变红 | 确认；重构后的口径由 `docs/claude-symbol-locate-config.md:213` 的原始清单复核过 |
