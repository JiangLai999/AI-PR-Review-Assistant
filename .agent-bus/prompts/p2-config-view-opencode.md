你是本项目的协作 agent（opencode）。**Phase 2 后端任务**：把 Web 设置页需要的
「当前值 + 可选项 + 运行档位」暴露出来，并统一校验规则。
你 Phase 0.2 已经把**写入**白名单做好了（`EDITABLE_PREFERENCE_FIELDS` 等），本轮补**读取**侧。

## 背景
- 现在 `ConfigView`（`src/ai_pr_review/web_config.py:60+`）只暴露 provider/base_url/model/api_format/密钥掩码/settings 数值项，
  **没有** `preferences` / `options` / `runtime_profile` → 前端设置页没办法渲染"界面语言/输出格式/chat 布局/工作台模式/仓库上下文/审查档位"这 6 个下拉，也无法按 CLI 助手的 6 阶段分组。
- CLI 助手的 6 阶段（`frontend/tui/src/app.tsx` 的 `screenStages` / `stageNames`，约 :1761-1799）：
  1 运行模式 · 2 模型服务 · 3 凭据与模型 · 4 界面与输出 · 5 审查偏好 · 6 确认。
- 你 Phase 0.2 定义的词表（`UI_LANGUAGES` / `OUTPUT_FORMATS` / `CHAT_LAYOUTS` / `WORKBENCH_MODES` /
  `REPO_CONTEXT_MODES` / `REVIEW_REASONING_EFFORTS`）就是**单一真相源**，本轮直接复用，不要再写第二份。

## 冻结的契约（前端已按此并行开发，字段名不可改）
`ConfigView.to_dict()` 新增三个键（**保持既有键不变**，老前端忽略新键即可）：

```json
{
  "preferences": {
    "ui_language": "zh-CN",
    "output_format": "terminal",
    "chat_layout": "compact",
    "workbench_mode": "auto",
    "repo_context": "tests",
    "review_reasoning_effort": "auto"
  },
  "options": {
    "ui_languages":   [{"value": "zh-CN", "label": "中文 / Chinese"}, {"value": "en-US", "label": "English"}],
    "output_formats": [{"value": "terminal", "label": "Terminal"}, {"value": "markdown", "label": "Markdown"}, {"value": "json", "label": "JSON"}],
    "chat_layouts":   [{"value": "compact", "label": "紧凑 / Compact"}, {"value": "split", "label": "分栏 / Split"}, {"value": "plain", "label": "纯文本 / Plain"}],
    "workbench_modes":[{"value": "auto", "label": "自动 / Auto"}, {"value": "always", "label": "常驻 / Always"}, {"value": "off", "label": "关闭 / Off"}],
    "repo_contexts":  [{"value": "...", "label": "..."}],
    "review_efforts": [{"value": "...", "label": "..."}]
  },
  "runtime_profile": "cloud"
}
```
约定：
- `preferences` 只放**这 6 个可编辑键的当前生效值**（来源 `config.preferences`，与 CLI 助手读的同一份）；
- `options` 每项必须是 `{"value","label"}`，label 用中英双语（`中文 / English`）与现有 UI 风格一致；
- `runtime_profile` 取 `config.preferences` 或既有 resolve 逻辑折算的当前档位（cloud/local/hybrid/custom），
  **不要**自己推导槽位；不确定就用既有函数/字段，并在文档里写清来源。
- `repo_contexts` / `review_efforts` 的 value 必须来自 `config.py` 的 `REPO_CONTEXT_MODES` /
  `REVIEW_REASONING_EFFORTS`（顺序一致），label 若 config 里没有中文说明，就按既有文案表补最小实现。

## 另一件事：统一校验规则（你 Phase 0 提案 §3.5）
现在前端 `SettingsPage` 的数值范围（max_tokens/timeout/review_concurrency/cross_file_max_files/max_cost_per_run/max_cost_per_24h）
与后端 `apply_config_update` 的校验各写一份。请把**后端**作为唯一真相源：
1. 在 `web_config.py` 里补一个可导出的范围表（例如 `NUMERIC_FIELD_RANGES`），供后端校验使用；
2. 同表通过 `/api/config` 的响应暴露出去（键名例如 `options.numeric_ranges`：`{"max_tokens": {"min": 1, "max": 128000, "step": 1}, ...}`），
   前端后续据此渲染 input 的 min/max/step（本轮前端不一定改，但契约要给到）；
3. 后端对越界值一律 `ok=False` + 明确 message（沿用你 Phase 0.2 的拒绝语义）。

## 交付
1. `src/ai_pr_review/web_config.py`：上述改动；
2. `tests/test_web_config_writes.py`（你已有该文件，继续用）：新增用例（名字建议）
   - `test_config_view_exposes_preferences_and_options`
   - `test_options_values_match_config_constants`（词表与 config.py 常量逐项对齐，防漂移）
   - `test_numeric_ranges_are_exposed_and_enforced`（越界 → ok=False）
3. `docs/opencode-web-config-view.md`：字段来源（file:line）、与 CLI 6 阶段的对应关系、校验单一真相源说明、验证数字、未决项。

## 约束
- 只写：`src/ai_pr_review/web_config.py`、`tests/test_web_config_writes.py`、`docs/opencode-web-config-view.md`；
- 禁止改 `web_server.py`（主控的）、`web/src/**`（claude/mimo 的）、禁止 git；禁止读取/输出凭据。

## 验证（必须真跑，报数字）
```bash
TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest tests/test_web_config_writes.py tests/test_web_server.py -q --no-cov
TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest tests/test_credentials_and_jobs.py -q --no-cov
```

完成后按总线报告：
`python scripts/agent_bridge.py report p2-config-view --agent opencode --status completed --summary "<一句话>" --evidence "<文件:行号 + 两段测试数字>" --blocker "<未决项，没有写无>"`
