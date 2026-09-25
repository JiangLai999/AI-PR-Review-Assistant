# mimo-repo-inject：仓库感知 L1-b 注入层

任务：`mimo-repo-inject`（agent: mimo）
前置：`mimo-repo-context` 已交付 `services/repo_context.py`（`RepoContextProvider` / `RelatedFile` / `RepoCache`）。
方案依据：`docs/repo-aware-review-plan.md` §4.5 / §4.7。

## 实际签名核对

前置交付与方案一致，无签名偏差：

- `RelatedFile(path, reason, content, truncated, from_cache)`（`reason ∈ {test, import, init}`）
- `RepoContextProvider(read_file, cache=None, max_files=3, budget_tokens=4000)`
- `RepoCache` 协议：`get(key) -> str | None` / `put(key, content) -> None`

`PreferencesConfig` **已包含** `repo_context` / `repo_context_max_files` /
`repo_context_budget_tokens` / `repo_cache_max_mb`（`config.py`，非本任务写域）。
因此直接读取这些字段，无需回退默认值（仍保留 `getattr` 兜底）。

注意：`config.py` 中**没有** `resolve_repo_context()`（只有 `normalize_*` 在
`__post_init__` 里做归一化）。hybrid 侧用 `_repo_context_mode()` 做同等 resolve。

## 交付内容

### 1. `services/context_builder.py`

`FileContext` 新增可选字段：

```python
related_files: list[dict] = Field(default_factory=list)
```

每个 dict：`{"path", "reason", "content", "truncated", "from_cache"}`。
**默认空列表 = 与注入前完全一致**，既有构造与断言不受影响。

### 2. `services/prompt_assembler.py`

当 `context.related_files` 非空时：

**user prompt 末尾追加固定格式段**（格式冻结，逐字测试）：

```markdown
## 相关仓库文件（未被本次修改）

### tests/test_auth_service.py（原因：test，已截断）
```python
…片段…
```

### path/to/config.py（原因：import）
```python
…片段…
```
```

英文界面：

```markdown
## Related repository files (not modified in this PR)

### tests/test_auth_service.py (reason: test, truncated)
…
```

**system prompt 追加诚实约束**（`RELATED FILE RULES`）：

- 中文：相关文件仅用于核实影响面。引用它们时必须给出 `文件:行`；未在上下文中出现的文件内容不得臆测。
- 英文：Related files are for impact verification only. When citing them, always give `file:line`. Never invent file content that does not appear in the context.

新增 API（均为附加，不改既有签名语义）：

- `render_related_files_section(related_files, response_language) -> str`
- `related_file_system_rules(response_language) -> str`
- `PromptAssembler.render_related_files(...)` / `PromptAssembler.related_file_rules()`
- `PromptAssembler.build_system_prompt(..., *, include_related_file_rules: bool = False)`

### 3. `services/repo_context.py`（仅新增）

`FileSystemRepoCache`：磁盘缓存，路径
`%LOCALAPPDATA%/ai-pr-review/repo_cache/<owner>__<repo>/<sha>/<safe-path>.txt`
（非 Windows 回退 `~/.local/share/ai-pr-review/repo_cache`）。

- 写入：`tempfile.mkstemp` + `os.replace`（原子）
- 读写失败一律吞掉（缓存未命中），绝不影响审查
- 路径段经 sanitize，防止 `../` 穿越

`RepoContextProvider.__init__` 新增可选 `reasons`（默认 `None` = 全部策略，既有行为不变）：
传 `{"test"}` 时只跑同名测试文件策略。

### 4. `services/hybrid_orchestrator.py`

`build_context` 之后、`build_user_prompt` 之前：

1. resolve `preferences.repo_context`；`off` → 零额外请求、不构造 provider
2. `read_file` 闭包委托 `self.pr_fetcher.fetch_file_content(owner, repo, path, head_sha)`
3. `max_files` / `budget_tokens` 取 `preferences.repo_context_max_files` / `repo_context_budget_tokens`
4. `tests` 模式只收集 `reason="test"`；`tests+imports` 收集全部
5. 任何异常 → 降级空列表 + `logger.warning`，审查绝不中断
6. 相关文件注入 `FileContext.related_files`；system prompt 追加诚实约束

run metadata 新增：

```json
"repo_context": {
  "files": ["tests/test_auth_service.py", "path/to/config.py"],
  "from_cache": 1,
  "truncated": ["tests/test_auth_service.py"],
  "skipped_reason": null
}
```

`skipped_reason`：成功为 `null`；`off` 为 `"off"`；预取异常为错误信息。

另外：hybrid 构造 `PromptAssembler` 时补传 `response_language`（与标准编排器一致），
使相关文件段的中/英标题跟随用户语言。

## 测试

新增 12 个用例（`tests/test_review_orchestrator.py`）：

| # | 用例 | 断言 |
|---|---|---|
| 1 | FileContext 默认 `related_files` | `== []`，prompt 无相关文件段 |
| 2 | user prompt 段格式（中） | 逐字冻结 |
| 3 | user prompt 段格式（英） | 逐字冻结 |
| 4 | system 诚实约束（中英） | 逐字断言 |
| 5 | `repo_context=off` | provider 构造/调用均为 0，`skipped_reason=="off"` |
| 6 | 非 off 注入 | metadata `files`/`from_cache`/`truncated` 正确，`skipped_reason is None` |
| 7 | provider 抛异常 | 审查正常完成，`skipped_reason=="prefetch exploded"` |
| 8 | `tests` 模式 | `reasons == frozenset({"test"})`，max_files=3，budget=4000 |
| 9–11 | FileSystemRepoCache | 读写往返、miss、原子写无残留 |
| 12 | 路径穿越 | 落盘点限制在缓存目录内 |

既有 prompt / 上下文测试无回归。

## 验证命令与结果

```powershell
New-Item -ItemType Directory -Force -Path .pytest_mimo
$env:TEMP = (Resolve-Path .pytest_mimo).Path
$env:TMP = $env:TEMP
python -m pytest -q --no-cov
```

结果：**838 passed, 1 skipped in 86.77s**

## 未决项

- `config.py` 无 `resolve_repo_context()`；本任务用 hybrid 内 `_repo_context_mode()` 等价 resolve。若后续在 config 侧抽出统一 resolve，可切换调用点（config.py 不在本任务写域）。
- `repo_cache_max_mb` 尚未接入 `FileSystemRepoCache` 的容量淘汰（本任务只建缓存通路）。
- 标准 `ReviewOrchestrator` 路径未接入预取（任务范围仅 hybrid）。
