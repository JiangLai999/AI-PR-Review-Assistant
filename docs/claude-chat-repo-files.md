# chat 按需读取仓库文件（任务 `claude-chat-repo-files`）交付报告

**一句话结论**：绑定 run 之后，用户消息里点名的源码文件会按**该 run 的 head 提交**
现拉一份内容进本轮 system prompt——实测里"website/js/main.js 里的 tab.html 从哪来"
不再是"需要查看源码"；拉不到就明写"(未能读取 …)"，绝不编造；任何异常都降级为空串，
对话不受影响。L1（`RepoContextProvider`）预取过的文件直接命中同一个磁盘缓存，不重复拉取。

- 任务类型：实现（写入范围：`src/ai_pr_review/backend/jsonl_server.py`、
  `tests/test_jsonl_backend.py`、本文件）
- 验证命令：`New-Item -ItemType Directory -Force -Path .pytest_claude` → `TEMP`/`TMP` 指向它 →
  `python -m pytest -q --no-cov`
- 未做：未读/打印凭据（测试与新代码全用 stub `PRFetcher`）；未执行任何 git 操作；
  未改 TUI（展示层留后续任务）；未改 `services/repo_context.py`（只**复用**它的
  `SOURCE_EXTENSIONS` 与 `FileSystemRepoCache`）；未联网

## 1. 路径识别：`_mentioned_repo_paths(text) -> list[str]`（`jsonl_server.py:226`）

只认 `services/repo_context.SOURCE_EXTENSIONS`（`.py/.ts/.tsx/.js/.jsx`）——与 L1 预取
同一套口径，不新增第二份扩展名清单。去重（大小写不敏感），最多 2 条。

| 输入 | 结果 | 说明 |
|---|---|---|
| `website/js/main.js 里的 tab.html 从哪来` | `["website/js/main.js"]` | 实测原句；`.html` 不在源码扩展名内，忽略 |
| `` 看下 `src/a.py` 和 src/b.ts `` | `["src/a.py", "src/b.ts"]` | 反引号/中文标点自动截断（示例） |
| `frontend\tui\src\main.tsx` | `["frontend/tui/src/main.tsx"]` | Windows 分隔符折算成 `/` |
| `see src/main.js:120 for details` | `["src/main.js"]` | `:120` 行号不进入路径 |
| `main.js 是干嘛的` | `["main.js"]` | **裸文件名也认**（见下） |
| `https://github.com/example/repo/pull/31` | `[]` | PR 链接不是文件路径 |
| `看看 https://cdn.example.com/vendor/app.js` | `[]` | 网址里的 `.js` 不算（先整体剔除 URL） |
| `https://github.com/o/r/blob/main/src/app.js#L10` | `[]` | blob URL 同样不认（保守取舍，见下） |
| `docs/PROJECT_DESIGN.md` / `index.html` | `[]` | 非源码扩展名（原写作 docs/design.md，该文件不存在） |
| `版本 1.2.3 和 e.g.` | `[]` | 末段必须以字母开头，版本号/缩写不命中 |

**取舍一：裸文件名也认。** 实测里用户会直接说"main.js 里的 tab.html 从哪来"，只认带
目录的形态会漏掉最常见的一类问法。代价是语义歧义（仓库里可能有多处 `main.js`）：
裸名按**仓库根相对路径**去拉，拉不到就如实写"(未能读取 main.js：该提交的仓库里不存在…)，
不会拿同名文件顶替——模型看到的是"没读到"，而不是一个来路不明的同名文件。

**取舍二：URL 一律先剔除。** `…/pull/31` 里没有源码扩展名，本就不会命中；但
`https://host/vendor/app.js` 有。与其猜测"这个网址是不是指向本仓库"，不如整段丢掉：
用户想读的是**这次 PR 的那个文件**，粘贴网址属于另一种意图（后续若要做，应走"解析
blob URL"的独立路径，而不是把它当成裸文件名去 root 上撞）。

## 2. 拉取与注入：`_repo_files_for_chat(session, text) -> str`（`:1537`）

```
前提：会话已绑定 run（session.current_run_id）且消息里识别到路径 → 否则返回 ""
  ↓ 在 `_resolve_context` 之后调用（本轮刚切换的绑定就是要去读的那个 run）
ResultStore.get_run_summary(run_id) → repo_owner / repo_name / head_sha
  ↓ 三者缺一 → 逐条渲染"(未能读取 <path>：该 Run 未记录仓库 / head 提交，无法定位文件)"
  ↓ Run 已被清理  → "(未能读取 <path>：该 Run 不存在或已被清理，无法定位文件)"
FileSystemRepoCache(owner, repo, sha).get(path)  ← 命中即用，不打 GitHub
  ↓ 未命中
PRFetcher(config=self.config.pr_fetcher).fetch_file_content(owner, repo, path, head_sha)
  ↓ 成功后 put 回同一个缓存
截断（单文件 8000 / 合计 12000 字符）→ 组装注入段
```

- **注入段**（`_collect_repo_files`，`:1565`）标题固定为
  `## 用户提到的仓库文件（来自本次 PR 的 head 提交）`，第二行给出
  `（run <8位> · owner/repo @ <8位 sha>）`，让模型能自己说清"读的是哪个版本"；
  每个文件一个 `### <path>` + 围栏代码块。
- **诚实约束**（`_repo_files_rules`，`:1618`）随段注入：只依据给出的内容回答 /
  未给出内容的文件（含"(未能读取 …)"）不得臆测、不得用记忆里的同名文件替代 /
  引用代码必须给「文件:行」。措辞与 `review_context.CONTEXT_RULES` 同风格但不共用常量
  ——那里讲的是 finding，这里讲的是源码。
- **绝不编造**：`fetch_file_content` 返回 `None`（不存在/无权限）与抛异常是两种文案
  （`…不存在，或当前 Token 无权访问` / `…拉取失败（<异常类名>）`）。异常只带**类名**，
  不夹带 message：GitHub 客户端的异常文案里可能带 URL 或 token 片段。
- **降级**：`_collect_repo_files` 整个炸掉（历史库读不了、`PRFetcher` 构造时缺 Token
  抛 `AuthenticationError` …）→ `_repo_files_for_chat` 吞掉异常、向 stderr 记一行
  `repo file context unavailable …; continuing without it`，返回 `""`，对话照常。
- **阻塞**：网络与磁盘 I/O 走 `asyncio.to_thread`，不卡 TUI 的事件循环。
- **缓存**：复用 `services/repo_context.FileSystemRepoCache`——与 L1 预取同一个
  `<root>/<owner>__<repo>/<sha>/<safe-path>.txt` 布局。因此**审查阶段预取过的文件，
  聊天里再问起时零网络请求**（联调脚本 [E]：两轮里 `main.js` 只被拉了一次）。
  不缓存"不存在"的结果（缓存只存字符串），失败的文件下次再问会重试。
  本次**未改** `repo_context.py`：它的 `get/put` 接口对任意文件都成立。

## 3. 注入位置：只进本轮 system prompt（`:1396`、`:1746`）

```python
repo_files = await self._repo_files_for_chat(session, text)   # :1746，必须在 _resolve_context 之后
chat_options = {"system_prompt": self._chat_system_prompt(session, repo_files), ...}
```

`_chat_system_prompt` 的段落顺序：语言指令 → 能力边界 → `<review_context>` →
**仓库文件段** → 其它可切换审查的提示。未绑定 / 审查上下文读不到时同样会带上仓库文件段
（`_join_prompt_sections` 只丢空串）。

**不写 `session.messages`**：`repo_files` 只活在这一次调用的 system prompt 里，对话历史
仍只有 user/assistant 轮次（联调脚本 [C][D]：历史里查不到源码里的 `mountTabs`）。
否则每一轮都会把源码重新计费一遍。

## 4. 实测证据（离线，不联网不读凭据）

脚本：`.pytest_claude/verify_chat_repo_files.py`（stub `PRFetcher` + stub provider），
`python .pytest_claude/verify_chat_repo_files.py`：

```
[A] ok = True | fetcher calls = [('example', 'repo', 'website/js/main.js', 'c0ffeec0ffee…abcd')]
[B] system prompt 里的注入段：
    ## 用户提到的仓库文件（来自本次 PR 的 head 提交）
    （run d043199e · example/repo @ c0ffeec0）
    ### website/js/main.js
    ```
    import { mountTabs } from './tabs.js';
    …
      view.load('tab.html');
    ```
    规则：1. … 2. …不得臆测… 3. 引用代码时必须给出「文件:行」。
[C] 历史消息角色 = ['user', 'assistant']
[D] 对话历史里是否含源码 = False
[E] 第二轮 ok = True | fetcher calls = [main.js（第一轮已缓存，未再拉）, src/missing.py]
[F] 未读取说明 = ['(未能读取 src/missing.py：该提交的仓库里不存在，或当前 Token 无权访问)', …]
```

[A] 的第三个元组元素就是 `head_sha`：拉的是该 run 审查时用的那个提交，不是默认分支。

## 5. 测试（`tests/test_jsonl_backend.py` 末尾新增 8 条）

| 用例 | 钉住的行为 |
|---|---|
| `test_mentioned_repo_paths_hits_common_forms_and_ignores_the_rest` | 常见形态命中 / PR URL 与网址不误判 / 非源码扩展名忽略 / 去重 / 上限 2 |
| `test_chat_injects_the_mentioned_repo_file_from_the_run_head` | 注入内容 + 断言 fetcher 收到的 `(owner, repo, path, ref)` 正是 run 的 head_sha；历史里无源码 |
| `test_chat_without_a_mentioned_path_never_asks_github` | 无路径 / 未绑定 → 不注入、fetcher 零调用 |
| `test_chat_says_it_could_not_read_a_file_instead_of_inventing_one` | 返回 `None` → "(未能读取 …)"，同轮另一个文件照常注入 |
| `test_chat_survives_a_failing_repo_file_fetch` | 抛异常 → 只报类名（不泄漏 message）、对话成功；收集整体炸掉 → 降级空串 |
| `test_chat_reuses_the_l1_prefetch_cache_for_mentioned_files` | 两轮同一文件 → fetcher 只被调用 1 次 |
| `test_chat_truncates_mentioned_files_per_file_and_in_total` | 单文件 8000 / 合计 12000 字符上限与截断提示 |
| `test_chat_reports_a_run_without_a_head_sha_instead_of_guessing` | 老 run 无 head_sha / Run 被清理 → 各自的原因文案，且不打 GitHub |

数字：`tests/test_jsonl_backend.py` **177 passed**（基线 169，新增 8）；
全量 `python -m pytest -q --no-cov` → **936 passed, 1 skipped**（基线 928 passed, 1 skipped），
无回归。

## 6. 未决与边界

1. **只认 5 种源码扩展名**：`tab.html` 本身仍读不到（要改成"任意文本文件"需另开任务，
   还要考虑二进制/大文件与 `.md` 噪音）。实测那句问话里真正需要的是 `main.js`，已解决。
2. **不改 TUI**：本轮没有"正在读取仓库文件…"的进度提示；最多两次 `fetch_file_content`，
   延迟与一次普通工具调用同级。
3. **同名裸文件名歧义**（§1 取舍一）：按仓库根解析，读不到就如实说"没读到"。
4. **没有把"用户问的文件"写回 `session.messages`**：下一轮如果用户只说"那它呢"，
   不会再注入（本轮没有路径可识别）。要支持指代需要把"上一轮提到的路径"记在
   `Session` 上，属于后续增量。
5. **`repo_context` 偏好（off/tests/tests+imports）不影响本功能**：那是一份审查阶段的
   **预取**预算；聊天读文件是用户点名触发的按需读取，两件事的开关不应互相牵连。
   若日后要一个"聊天不许读源码"的总开关，应新增独立偏好而不是复用 `repo_context`。
