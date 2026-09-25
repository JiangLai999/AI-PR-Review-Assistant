# P6 项①+项④ 交付报告：sources 可信化与规则目录中文覆盖（任务 `claude-p6-rule-trust-i18n`）

**一句话结论**：交给模型的 JSON Schema 不再暴露 `sources` / `evidence` / `evidence_status` /
`evidence_issues` / `finding_id` / `rule_id`（`prompt_assembler.py:63,294-320`），模型产出在
`AIClient._parse_review_result` 后被强制归一（`ai_client.py:202-227`），来源判定统一走
`finding_has_source`；19 条规则文案（18 个 rule_id）集中到新的 `rule_catalog.py`，
`finding_localizer` 改为按 `rule_id` 取中文、旧标题表降级为兼容回退。
两个分析器对全部 19 段触发样例的输出与改造前**逐字节一致**（含 `finding_id`）。

- 任务类型：实现（可写 `services/analyzers/**`、`prompt_assembler.py`、`ai_client.py`、
  `finding_localizer.py`、`evidence/finding_validator.py`、`tests/**`、本文件）
- 验证命令：`New-Item -ItemType Directory -Force -Path .pytest_x` → `TEMP`/`TMP` 指向它 →
  `python -m pytest -q --no-cov`
- 结果：**543 passed, 1 skipped**（改造前 505 passed / 4 failed / 1 skipped；4 个 failed 见 §5.1）
- 未做：未读/打印凭据，未执行任何 git 操作，未修改 write_scope 之外的文件，未联网、未发布评论

## 1. 改动清单

| 文件 | 改动 |
|---|---|
| `services/analyzers/rule_catalog.py` | **新增**。规则目录：`RuleDefinition`（rule_id/title/problem/suggestion/category/severity/confidence + 三段中文）与 `RULE_CATALOG`（19 键 / 18 个 rule_id）、`get_rule`、`rule_for_id`、`all_rule_ids` |
| `services/analyzers/static_analyzer.py` | 8 条逐行规则改为 `self._finding(filename, line, snippet, rule="…")`，文案与元数据取自目录（`_finding` 见 `:68`） |
| `services/analyzers/python_ast_analyzer.py` | 11 条 AST 规则同样改为按目录构造（`_finding` 见 `:347`） |
| `services/prompt_assembler.py` | `Finding` 增加 `rule_id`；`sources` 增加 trim/lower 规范化；新增 `finding_has_source`；`get_json_schema()` 剔除服务端字段与随之失效的 `Evidence` 定义 |
| `services/ai_client.py` | `_parse_review_result` 解析后强制归一模型产出（`:202`） |
| `services/finding_localizer.py` | 主路径按 `rule_id` 本地化，旧 `_RULE_ZH` 保留为回退（`:81-119`） |
| `services/evidence/finding_validator.py` | 来源分支改用 `finding_has_source`（`:61`） |
| `tests/test_rule_catalog.py` | **新增**：目录覆盖、反向覆盖、中文渲染、旧表一致性 |
| `tests/test_finding_localizer.py` | **新增**：rule_id 本地化、旧表回退、来源闸门 |
| `tests/test_ai_client.py` | 新增 `TestModelFieldNormalization`（模型伪造 static_rule 不生效） |
| `tests/test_prompt_assembler.py` | 新增 Schema 隐藏字段与 `sources` 规范化测试 |
| `tests/test_upgrade_services.py` | 新增来源判定测试（大小写不再左右分支） |
| `tests/test_cli.py` | 刷新 2 个 demo 载荷 golden 哈希（原因见 §5.1） |

## 2. 项① sources 可信化

### 2.1 Schema 不再暴露服务端字段

`get_json_schema()` 仍返回 `ReviewResult.model_json_schema()`，但会从 `$defs.Finding` 的
`properties` 与 `required` 中删除 `finding_id` / `sources` / `evidence` / `evidence_status` /
`evidence_issues` / `rule_id`，并顺带删掉因此不再被引用的 `$defs.Evidence`。实测：

```text
Finding.properties = ['category','code_snippet','confidence','file','line_end','line_start',
                      'problem','severity','suggestion','title']
$defs               = ['Finding']        # 改造前为 ['Evidence','Finding']
```

`rule_id` 不在计划 §2.1 的清单里，但它与 `sources` 同类：一旦模型能填写它，
`localize_deterministic_finding` 会据此套用规则中文文案（内容伪造）。因此一并隐藏并归一。

### 2.2 解析后强制归一

`_parse_review_result` 校验成功后对每条 finding 覆盖：`sources=["ai_analysis"]`、`evidence=[]`、
`evidence_status="unverified"`、`evidence_issues=[]`、`finding_id=""`、`rule_id=""`
（每条 finding 使用新的列表对象，避免共享可变默认值）。理由：这些字段由确定性分析器/校验器负责，
模型自述不得影响控制流（来源分支、中文本地化分支）。

### 2.3 来源判定统一

`Finding.sources` 增加 `mode="before"` 规范化：字符串单值自动包装成列表，元素 trim + lower，
未知值保留（仅规范化拼写）。判定统一走 `finding_has_source(finding, "static_rule")`
（`prompt_assembler.py:145`），`finding_validator.py:61` 与 `finding_localizer.py:88` 均改为调用它，
不再各自写 `"static_rule" in finding.sources`。

### 2.4 测试

`tests/test_ai_client.py::TestModelFieldNormalization`：模型 payload 同时声称
`sources=["static_rule"]`、`evidence_status="valid"`、`finding_id="model-supplied-id"`、
`rule_id="mutable_default_argument"` 并自带一条 `validation_status="valid"` 的 evidence，
断言落库为 `ai_analysis` / `[]` / `unverified` / `""` / `""`，且
`localize_deterministic_finding(finding, "zh-CN")` 保持英文标题（不会被当规则本地化）；
另有独立性测试（两条 finding 的 `sources` 不共享列表）。确定性规则的 finding 仍为 `static_rule`
（`tests/test_rule_catalog.py::TestReverseCoverage`、`tests/test_python_ast_analyzer.py`）。

## 3. 项④ 规则目录与中文覆盖

### 3.1 目录

`rule_catalog.py` 一条记录含 `rule_id`、`title`、`problem`、`suggestion`、`severity`、`category`、
`confidence` 与 `title_zh` / `problem_zh` / `suggestion_zh`；动态文案写成 `{placeholder}`，
分析器构造时渲染英文（`RuleDefinition.build_fields`），本地化时从英文标题反解占位符
（`RuleDefinition.localize` + `_extract_params`）。

- 英文文案与改造前的两个分析器逐字一致（§5.2 有差分验证）；
- 中文文案 18 个 rule_id 全量覆盖，其中旧 `_RULE_ZH` 已覆盖的 11 条**逐字沿用旧表**，
  因此这 11 条规则的中文渲染结果与改造前完全相同（`test_catalog_chinese_matches_legacy_table`）；
- 补上的 7 条：`hardcoded_credential_constant`、`debug_mode_enabled`、`raise_without_from`、
  `uncontextualised_value_error`、`weak_hash_algorithm`、`is_literal_comparison`、`unsafe_deserialization`。

### 3.2 两个分析器的构造路径

`StaticAnalyzer._finding(filename, line_number, snippet, *, rule, **params)` 与
`PythonAstAnalyzer._finding(line, *, rule, **params)` 都从目录取 `title/problem/suggestion/
category/severity/confidence/rule_id`，`finding_id` 仍按 `f"{file}:{line}:{rule_id}"` 计算，
因此历史 finding_id 不变。规则键保持 `rule="…"` 关键字形式不是风格选择：
`web_server.count_deterministic_rules()`（不在 write_scope 内）用
`re.findall(r'rule="([a-z][a-z0-9_]+)"', source)` 统计规则数，实测改造后仍返回 **18**，
与目录的 rule_id 数一致；若改成位置参数会静默变成 0（UI 显示 0 条规则）。

### 3.3 本地化

```text
localize_deterministic_finding(finding, language)
  ├─ 非 zh 或来源不是 static_rule → 原样返回
  ├─ rule_for_id(finding.rule_id).localize(finding.title)   # 主路径（目录，含动态片段）
  ├─ _localize_by_title(finding.title)                      # 兼容回退（旧 _RULE_ZH，含"标题（后缀）"拼接）
  └─ 都未命中 → 原样返回英文
```

### 3.4 测试

- 目录覆盖：每条规则三段中文非空、含汉字、与英文不同；rule_id 去重后 18 条；同 rule_id 的多条记录中文必须一致；
- 反向覆盖：用 `ast` 扫描两个分析器源码里所有 `_finding(...)` 调用（字面量或 `TLS_AST_RULE_KEY`
  常量按模块命名空间解析），断言 19 个键 **全部登记在目录**，且目录里没有未被使用的条目
  （新增规则不补目录、或目录残留死条目都会失败）；
- 中文渲染：19 个规则键逐一触发 → zh 下标题/问题/建议均含汉字、且都不等于英文原文，
  同时 `sources` 仍为 `["static_rule"]`、`rule_id` 不变；
- 动态标题：`弱哈希算法（md5）`、`不安全的反序列化（pickle）`。

## 4. 验证命令与证据

```text
New-Item -ItemType Directory -Force -Path .pytest_x
$env:TEMP = (Resolve-Path .pytest_x).Path ; $env:TMP = $env:TEMP
python -m pytest -q --no-cov
→ 543 passed, 1 skipped in 74.77s
```

补充证据（均为离线只读脚本，结果见本文档）：

| 验证 | 方法 | 结果 |
|---|---|---|
| 英文文案逐字一致 + finding_id 不变 | 加载 `_p5_verify/cleanvenv/.../analyzers/{static,python_ast}_analyzer.py`（改造前快照）与当前实现，对 19 段样例比对 `title/problem/suggestion/category/severity/confidence/finding_id/sources/code_snippet/line_start/line_end` | 19 样例 × 2 分析器，**0 处差异** |
| demo 载荷仅多 `rule_id` | 当前 payload 逐个 finding 去掉 `rule_id` 后再算 SHA-256 | 与旧 golden 完全一致（`sql-injection` 91e9948d…、`tls-disabled` d277f194…、`clean-change` 不变） |
| Schema 收敛 | 打印 `get_json_schema()` | 见 §2.1 |
| UI 规则数 | `web_server.count_deterministic_rules()` | 18 == `len(all_rule_ids())` |
| Codex 独立验收脚本（只读运行） | `python _p5_verify/p6proto/verify_p6.py` | **[A] 8/8 通过、[B] 15/15 通过**；[D] 仅剩终端词汇 3 项失败，属项②（`claude-p6-fork-and-terms` 的 `report_renderer.py` 终端文案），不在本任务范围 |

## 5. 与计划的偏差、以及理由

### 5.1 `tests/test_cli.py` 的 2 个 demo golden 哈希被刷新（唯一的既有测试改动）

计划 §3.3 要求 `Finding` 增加 `rule_id`，而 demo 载荷按 `model_dump` 序列化 finding，
所以带 finding 的两个用例（`sql-injection`、`tls-disabled`）载荷多了一个键，冻结的 SHA-256 失配；
`clean-change` 无 finding，哈希不变。**除该键外载荷逐字节不变**（§4 的剥离法证明）。
这两个哈希是"CLI 重构不得改变打印字节"的快照，而非"载荷永远不变"的约束；
新哈希与原值的关系已写进 `tests/test_cli.py` 的注释，便于复核。

### 5.2 TLS 规则在目录里有两个键

`tls_verification_disabled` 由逐行规则（"Certificate verification is turned off, …"）与 AST 规则
（"Disabling certificate verification makes the request vulnerable …"）各自实现：rule_id、标题、
严重级别、置信度、分类相同，**英文问题描述不同**。计划要求英文逐字保留现状，故目录用两个键
（`tls_verification_disabled`、`tls_verification_disabled.ast`）共享同一 `rule_id`；后者用
`dataclasses.replace` 从前者派生，中文文案与 finding_id 因此不会漂移（有测试断言）。

### 5.3 归一清单比 §2.2 多一个 `rule_id`

见 §2.1 末段：`rule_id` 与 `sources` 同属"模型不得影响控制流"的字段。同理，`get_json_schema()`
也隐藏它（否则模型能看到并试图填写一个只能由目录产出的字段）。

### 5.4 `Mutable default argument` 的中文问题描述沿用旧表原文

`_RULE_ZH` 的旧句与英文模板现在多了 `{listed}` 占位符，我最初改写了中文，但那样这 11 条规则的
中文渲染会与改造前不一致。为把"确定性规则渲染零回归"做成可断言的性质，最终逐字沿用旧句
（代码里有注释说明）。

## 6. 未决项与边界外观察

1. **两个静态扫描器已不再反映真实调用形态（未修改，超出 write_scope）**：
   - `web_server.py:41-58` 的 `count_deterministic_rules()`：**返回值仍然正确**（实测 18 == 目录
     rule_id 数），因为两个分析器现在都写 `rule="…"`，命中它的第一条正则；但 docstring 里
     "`static_analyzer` 用位置参数（`..., 0.98, "dynamic_execution",`）"已过时。
   - `scripts/count_rules.py`：只认旧的"浮点置信度 + 规则名 + 逗号"位置形态，改造后会打印
     **每条规则 0 条**（该脚本在仓库中没有被任何测试/文档引用，不影响测试与运行时）。
   两者的正确修法都是改为读 `rule_catalog`（`RULE_CATALOG` / `all_rule_ids()`），
   这需要改 `web_server.py` / `scripts/`，不在本任务 write_scope 内。
2. **`docs/review-workspace-contract.md:869-882` 的 F10 追记未更新（超出 write_scope）**：
   该处把"sources 无约束"记为 follow-up；本轮已完成（Schema 隐藏 + 归一 + helper），
   建议集成方更新该行。
3. **未做真实 Run 的端到端重渲染**：本轮只做离线代码与本地渲染验证。渲染链路（orchestrator →
   `finding_localizer` → 落库 → 报告/评论）未在真实 Run 上跑过；不过 orchestrator 的调用点未变，
   且 19 条规则的中文本地化已逐条断言。计划 §6 的"真实 Run 重新渲染"仍需集成方执行。
4. **`rule_id` 会进入落库/接口载荷**（新增键，向后兼容：旧数据无此字段时默认 `""`，
   本地化自动回退到标题表）。TUI/Web 的 TS 类型未列出该键（写范围外），多余键会被忽略；
   若集成方希望前端展示"规则 ID"，可直接读取。
5. **模型侧非确定性**：Schema 已不暴露服务端字段，但模型仍可能**在文本里**编造"来源：static_rule"
   之类字样（例如写进 problem）。本轮只保证结构化字段不可伪造；内容层的表述不在本任务范围。
