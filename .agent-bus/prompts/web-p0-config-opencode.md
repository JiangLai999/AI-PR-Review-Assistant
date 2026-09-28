你是本项目的协作 agent（opencode）。这是**实现任务**（写代码）：修掉你在
`docs/DEV_RECORD.md` §3.1/§3.2/§3.3 里**已实测复现**的三个配置写入缺陷，
让 Web 设置页"保存成功"与磁盘真实一致。

## 已复现的三个缺陷（你的探针结论，作为验收基线）
1. `apply_config_update` 白名单外的键被**静默丢弃**：`POST /api/config {"ui_language":"en-US"}` → `ok=true, changed=[]`；
2. `preferences.hybrid_strategy=local_only` 时，Web 提交的 `base_url`/`model` 被 **Ollama 值覆盖**（`changed=['base_url','model']` 但磁盘仍是 `http://127.0.0.1:11434/v1` / `qwen3.5:4b`）；
3. `review_reasoning_effort` 必须写 `preferences`，写 `ai_client` 时落盘仍是 `off`。

## 要做的事（write_scope 内）
1. `src/ai_pr_review/web_config.py`（主改动）：
   - 把 Web 设置页需要的 preferences 键纳入白名单：`ui_language`、`output_format`、
     `chat_layout`、`workbench_mode`、`repo_context`、`review_reasoning_effort`；
     `response_language`/`auto_publish_comment` **不暴露给 Web UI**（交互式界面里自动发评论太危险），
     但若它们已在白名单里，语义保持不变、不要回退；
   - **未知键不再是静默丢弃**：返回 `SaveResult(ok=False, message="unsupported key: <k>")`
     并把**接受的键集合**写进 `changed` 语义说明（主控会在 `web_server.py` 侧把 `ok=False` 映射成 HTTP 400，
     你**不要**改 web_server.py）；
   - 修缺陷 2：`local_only` 分支不得用 Ollama 值覆盖用户显式提交的 `base_url`/`model`
     （显式提交优先；只有未提交时才回落）。若根因在 `config.py` 的 resolve 链路上，
     **优先在 web_config 层解决**（例如提交时同步写 AI client 与 preferences 的一致值），
     并在文档里写清"为什么不动 config.py"；若确实必须动 config.py，先在报告里说明再动手（仍属你的 write_scope）；
   - 修缺陷 3：`review_reasoning_effort` 一律落 `preferences`（必要时同步 `ai_client`），落盘后**必须**能被读回。
   - 保持既有语义：`api_key`/`github_token` 掩码 + "留空=不改"。
2. 新建 `tests/test_web_config_writes.py`（**不要改 tests/test_web_server.py**，那是主控的文件）：
   把你三个探针固化成回归用例（临时 config 目录，不碰用户真实配置）：
   - `test_unknown_key_is_rejected_not_silently_dropped`
   - `test_ui_language_and_review_effort_persist_and_read_back`
   - `test_local_only_does_not_override_explicit_base_url_and_model`
   - （可再加：`test_blank_api_key_keeps_existing`）
3. `docs/DEV_RECORD.md`：缺陷 → 根因（file:line）→ 修复 → 用例 → 验证数字 → 未决项。

## 约束
- 只写 write_scope：`src/ai_pr_review/web_config.py`、`tests/test_web_config_writes.py`、`docs/DEV_RECORD.md`
  （若确需动 `src/ai_pr_review/config.py`，先确认改动最小且不改变 CLI 语义，并在文档与报告里显式声明）；
- 禁止改 `web_server.py` / `web_config.py` 之外的 Web 层、禁止改 `web/src/**`（另一 agent 的）、禁止 git 操作；
- 禁止读取/输出任何凭据；不确定写"未确认"。

## 验证（必须真跑并报数字）
```bash
TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest tests/test_web_config_writes.py -q --no-cov
TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest tests/test_web_server.py tests/test_credentials_and_jobs.py -q --no-cov
```
期望：新用例全绿；既有用例**不回归**（你上轮基线：两文件合计 81 passed）。

完成后按总线报告：
`python scripts/agent_bridge.py report web-p0-config --agent opencode --status completed --summary "<一句话>" --evidence "<文件:行号 + 两端测试数字>" --blocker "<未决项，没有写无>"`
