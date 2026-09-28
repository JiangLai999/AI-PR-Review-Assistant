你是本项目的协作 agent（opencode）。**收尾任务**：把 Web 界面里"后端生成的中文文案"补齐成
**中英双语**。用户点名三处，主控已核实共四类，方案如下（**契约已冻结，前端由 claude 并行消费**）。

## A. 结构化键（活接口返回，前端按当前语言渲染）

### A1 `SaveResult`（`src/ai_pr_review/web_config.py`）
新增两个字段（**保留现有 `message` 不变，供 CLI 与旧前端用**）：
```python
message_key: str = ""                       # 前端词典的 key
message_params: dict[str, Any] = field(default_factory=dict)
```
按下表填（key 名不可改，前端词典按这套写）：
| 场景 | message_key | params |
|---|---|---|
| 保存成功（`web_config.py:516`） | `config.save.saved` | `{"count": len(changed), "path": path.name}` |
| 没有改动（`:502`） | `config.save.noop` | `{}` |
| 未知键（`:373`） | `config.save.unsupported_key` | `{"keys": "<逗号分隔>"}` |
| 未知供应商（`:384`） | `config.save.unsupported_provider` | `{"provider": "<名>"}` |
| 非法值（`:401`/`:406`） | `config.save.invalid_value` | `{"name": "<字段>"}` |
| 非法值+可选值（`:440`） | `config.save.invalid_value_options` | `{"name": "<字段>", "options": "<可选值>"}` |
| 落盘校验失败（`:510`） | `config.save.verify_failed` | `{"fields": "<逗号分隔>"}` |
其余分支留空 `message_key=""`（前端回落原文）。

### A2 `CredentialStatus`（`src/ai_pr_review/credentials.py`）
新增（保留 `label`/`detail`/`fix_hint` 原文）：
```python
label_key: str = ""
detail_key: str = ""
fix_hint_key: str = ""
params: dict[str, Any] = field(default_factory=dict)
```
按下表填（`to_dict()` 同步输出这四键）：
| 场景（file:line 见文件现况） | label_key | detail_key | fix_hint_key | params |
|---|---|---|---|---|
| GitHub 未配置 | `credentials.github` | `credentials.github.missing` | `credentials.github.fix_token` | `{}` |
| GitHub 已认证（`:131`） | `credentials.github` | `credentials.github.ok` | 空 | `{"login": "<login>"}` |
| GitHub 401（`:136`） | `credentials.github` | `credentials.github.invalid` | `credentials.github.fix_reissue` | `{}` |
| GitHub 403（`:144`） | `credentials.github` | `credentials.github.forbidden` | `credentials.github.fix_retry` | `{}` |
| GitHub 其它状态（`:151`） | `credentials.github` | `credentials.github.other` | `credentials.github.fix_network` | `{"status": <码>, "body": "<截断>"}` |
| 模型供应商未配置（`:168`） | `credentials.provider` | `credentials.provider.missing` | `credentials.provider.fix_key` | `{}` |
（文件里若还有其它 `CredentialStatus` 构造点，一并按同一命名法补；拿不准的只填 `label_key` 与 `detail_key`，`fix_hint_key` 留空。）

## B. 生成时本地化（审查流水线写库的文案，按当时 `preferences.ui_language` 生成）

新建 `src/ai_pr_review/services/i18n_text.py`（**极小的双语表，不要引依赖**）：
```python
def is_english(language: object) -> bool: ...          # 与前端同口径：以 "en" 开头即英文
def review_summary(language: object, findings: int) -> str      # zh: 审查完成，发现 {n} 个问题 / en: Review complete — {n} finding(s).
def filter_included_by_default(language: object) -> str         # zh: 文件未命中过滤规则，默认纳入审查。 / en: File did not match any filter rule; included by default.
```
接线（只改这两处 + 如必须的调用方）：
1. `src/ai_pr_review/services/hybrid_orchestrator.py:484` 的 `summary = f"审查完成，发现 {...} 个问题"` → 用 `review_summary(...)`，
   语言取 `self.config.preferences.ui_language`（拿不到就默认中文）。
2. `src/ai_pr_review/services/filter_pipeline.py:244` 的 `message="文件未命中过滤规则，默认纳入审查。"` → 用 `filter_included_by_default(...)`，
   语言同样取 config 的 `preferences.ui_language`（该类若能拿到 config；拿不到就把 language 作为构造参数/方法参数注入，改动最小即可）。
3. `src/ai_pr_review/cli.py:2097` 的同类 summary **不要动**（CLI 侧另行处理）。

## 测试（新建 `tests/test_i18n_text.py` + 复用既有文件）
- `test_review_summary_zh_and_en`
- `test_filter_default_included_message_zh_and_en`
- `test_save_result_carries_message_key_and_params`（成功/未知键/非法值三态）
- `test_credential_status_carries_i18n_keys`（GitHub 未配置 + provider 未配置两条，断言 key 与原文都在）
- 既有 `tests/test_web_server.py` / `tests/test_credentials_and_jobs.py` **不得回归**（断言 `!ok → HTTP 400` 等既有契约不变）。

## 交付
1. 上述源码改动；2. 测试；3. `docs/opencode-backend-i18n.md`：四类文案的改法（结构化键 vs 生成时本地化，说明为什么分开）、
key 清单、验证数字、未决项（例如 CLI 侧文案、已落库的历史 run 不会回溯翻译）。

## 约束
- 只写：`src/ai_pr_review/{web_config.py,credentials.py}`、`src/ai_pr_review/services/{i18n_text.py,filter_pipeline.py,hybrid_orchestrator.py}`、
  `tests/test_i18n_text.py`、`docs/opencode-backend-i18n.md`（以及必要时既有测试文件的**新增**用例）；禁止改 `web/**`、禁止 git；
- 不动 `cli.py`；不改已落库数据；禁止读取/输出凭据。

## 验证（必须真跑，报数字）
```bash
TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest tests/test_i18n_text.py tests/test_credentials_and_jobs.py tests/test_web_server.py -q --no-cov
TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest -q --no-cov
```

完成后按总线报告：
`python scripts/agent_bridge.py report p4-backend-i18n --agent opencode --status completed --summary "<一句话>" --evidence "<文件:行号 + 测试数字 + key 清单数量>" --blocker "<未决项，没有写无>"`
