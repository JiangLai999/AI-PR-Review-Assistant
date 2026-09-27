# 仓库结构上下文：finding 文件放开 + PR 变更清单 + 目录树（任务 `claude-repo-structure-context`）

**一句话结论**：绑定 run 之后，模型不再只拿得到 finding 点名的那两个文件——
**A)** findings 兜底读文件从写死的 2 条放宽到 8 条（真正的闸门仍是 12000 字符预算，
超预算逐条标注「本轮注入已达上限」）；**B)** 每一轮注入「本次 PR 变更文件」
（`共 N 个，另有 M 个被本次审查跳过`），首轮拉一次、进程内缓存；
**C)** 用户问到「结构/目录/树/有哪些文件」时注入 head 提交的目录树
（深度 ≤3、≤200 行、单目录 ≤25 项，三种折叠都带计数）。两段都小、都可降级：
拉不到就明写原因（只给异常类名），绝不阻塞对话、绝不编造。

- 写入范围：`src/ai_pr_review/backend/jsonl_server.py`、
  `src/ai_pr_review/services/repo_context.py`、`src/ai_pr_review/services/pr_fetcher.py`、
  `tests/test_jsonl_backend.py`、`tests/test_repo_context.py`、本文件
- 验证命令（`TEMP`/`TMP` = `.pytest_claude`）：
  `python -m pytest -q --no-cov` → **1328 passed, 1 skipped**
  （本次新增 21 条用例；基线 = 1328 − 21 = 1307 passed）
- 证据脚本（离线、零网络、零凭据）：`.pytest_claude/verify_repo_structure_context.py`
- 未做：不发真实网络请求（测试与证据脚本全部 stub/monkeypatch）、不读凭据、
  不做 git 操作、不改前端/TUI、未改 `tests/test_pr_fetcher.py`（不在 write_scope，见 §7.1）

## 1. A：finding 文件兜底放开（`jsonl_server.py:2519`）

`_findings_file_paths(run_id, limit=None)`：`limit=None` 时用新常量
`CHAT_FINDINGS_FILES_LIMIT = 8`（原来是写死的 `limit=2`）。触发路径不变——用户消息里
没有显式路径、但含 `CHAT_REPO_CODE_INTENT`（"代码/源码/原始内容/code/source"）时兜底到
本次 finding 点名的文件（findings 点名的 `.html` 等非源码扩展名也照读，见
docs/claude-chat-repo-files.md §1）。

**条数上限只是防病态 run 的兜底，真正的闸门是 `CHAT_REPO_FILES_TOTAL_CHARS = 12000`**：
`_collect_repo_files` 逐条扣预算，装不下的文件输出
`(未能读取 <path>：本轮注入已达 12000 字符上限)`——如实标注，不静默消失。
默认 8 覆盖实测场景（12 条 finding 涉及 3 个文件），同时不会因为一个 200 条 finding 的
run 去拉 200 个文件。

## 2. B：本次 PR 变更文件清单（`jsonl_server.py:2801`，渲染在 `repo_context.py:411`）

```
绑定 run（session.current_run_id）
  ↓ ResultStore.get_run_summary(run_id) → pr_url / excluded_files
PRFetcher.fetch_changed_file_paths(pr_url)        ← 新增轻量入口（pr_fetcher.py:162）
  ↓ 只做 URL 解析 → PR → files 分页，**不拉 diff**（大 PR 上 diff 是几十万字符的浪费）
render_pr_file_list(paths, limit=50, skipped=run.excluded_files)
```

输出（证据脚本 [3] 的原文）：

```
## 本次 PR 变更文件（共 4 个，另有 11 个被本次审查跳过）
- src/a.py
- src/b.py
- src/c.py
- website/index.html
规则：只依据上面的路径回答「改了哪些文件」；上面没列出的路径不得臆测。
```

- **`skipped`** 取 run 记录里的 `excluded_files`（审查阶段按规则跳过的文件数）——
  这是模型回答"为什么这次审查没提某个文件"的依据。老 run 没记这个数字时整句省略，
  不猜（`skipped=0`/`None` 都不写）。
- **截断**：超过 `CHAT_PR_FILES_LIMIT = 50` 条时折叠成
  `…（另有 N 个未列出，仅列出前 50 个）`。
- **为什么每轮都注入**：清单很短（50 条路径 ≈ 2 千字符），且与 finding 解读强相关
  （"这个文件不在本次 PR 里"是高频追问）。挂在 system prompt 上、不落 `session.messages`，
  所以不会随历史重复计费。
- **无 PR 链接**（老记录）：`（未能读取变更文件清单：该 Run 未记录 PR 链接）`。

## 3. C：仓库目录树（`jsonl_server.py:2824`，渲染在 `repo_context.py:520`）

```
用户消息命中 CHAT_REPO_STRUCTURE_INTENT（结构/目录/树/哪些文件/文件列表/structure/
directory/folder/tree/layout，均按子串、大小写不敏感）
  ↓ run 的 repo_owner / repo_name / head_sha 三者齐全
PRFetcher.fetch_repo_tree_paths(owner, repo, head_sha)   ← 新增（pr_fetcher.py:173）
  ↓ PyGithub get_git_tree(ref, recursive=True)，只收 type == "blob"
render_repo_tree(paths, sha, max_depth=3, max_entries=200, max_children=25)
```

输出（证据脚本 [4] 的原文）：

```
## 仓库目录树（head 提交 bbbbbbbb · 深度 ≤3 · 最多 200 行）
（已排除 .git / node_modules / __pycache__ 等噪声与点目录；.github 等少数几个保留）
docs/
  design.md
src/
  a.py
  b.py
  c.py
website/
  index.html
规则：只依据上面的目录树回答结构问题；未展开/未列出的部分不得臆测。
```

**触发策略：按意图触发（不是每轮注入），理由有三**：

1. 成本：拉满的树 ≈ 200 行 ≈ 6 千字符 ≈ 1.5k token，而结构类问题只占对话的少数轮次；
   变更清单（§2）每轮注入是因为它小（≤50 行）且与每条 finding 的解读都相关。
2. 语义：目录树只在"这个仓库长什么样 / 有哪些文件"这类问题上提供信息；问
   "第 6 条 finding 为什么判 medium"时它是纯噪音，还会稀释审查上下文。
3. 降级成本对称：真被误判漏注入了，用户在下一轮换个说法（"目录结构"）即可命中；
   而每轮多付 1.5k token 是**每一轮**都在付。

按子串匹配（中英文各一组词，见 `CHAT_REPO_STRUCTURE_INTENT`）是刻意的：中文没有词边界，
"有哪些文件"这类说法必须命中；宁可偶发多注入一次（有缓存，最多一次 git tree 调用），
也不要因为换个说法就退化成"我看不到仓库结构"。

**三种折叠都给数字**（模型因此知道"还有内容"，不会把"没列出来"当成"不存在"）：

| 情形 | 文案 | 上限 |
|---|---|---|
| 目录深过 `max_depth` | `services/ …（56 项未展开）` | `CHAT_REPO_TREE_MAX_DEPTH = 3` |
| 同层子项过多 / 预算耗尽 | `…（另有 N 项未列出）` | `CHAT_REPO_TREE_MAX_CHILDREN_PER_DIR = 25` |
| 总行数超限（硬兜底） | `…（另有 N 行未列出）` | `CHAT_REPO_TREE_MAX_ENTRIES = 200` |

**行数在兄弟之间均分**（`repo_context._tree_lines`，`:475`）：纯深度优先会把预算全喂给
第一个大目录——实测本仓库的 `.agent-bus/`（深度 2、几十个锁文件）吃光整棵树，`src/`
一个字都进不了注入。改成"剩余预算 // 剩余子项"后每个兄弟至少露面一次，用不完的份额
自然回流（证据脚本与本仓库实测：`src/` / `tests/` / `docs/` / `website/` 都在，
且小目录完整列出）。

**噪声过滤**：`.git` / `node_modules` / `__pycache__` / `dist` / `build` / `target` /
`vendor` / `venv` 等目录名 + `*.pyc` / `.DS_Store` 等文件名；**点目录整体排除**
（`.venv313` 这类本机产物名字枚举不完），只放行 `.github` / `.devcontainer`。
文件不按点过滤（`.gitignore` 这类配置仍有信息量）。文案里明说"已排除…"，
模型不会把没列出的目录当成"不存在"。

## 4. 注入顺序与预算（`jsonl_server.py:2337`、`:2996`）

```
语言指令 → 能力边界 → <review_context>（finding 解读）→ 仓库结构段（B[+C]）→ 用户点名的源码 → 其它可切换审查
                      ↑ 结构段紧跟审查上下文：它是"解读这次审查"的一部分
```

- `_chat_repo_inventory(session, text)`（`:2761`）与 `_repo_files_for_chat` 并列，都在
  `_resolve_context` 之后调用（本轮刚切换的绑定就是要去读的那个 run），I/O 都走
  `asyncio.to_thread`，不卡 TUI 事件循环。
- **都不写 `session.messages`**：只进本轮 system prompt，历史不会重复膨胀、重复计费。
- 结构段**不参与** `preferences.chat_context_budget` 的 token 估算（`/context` 的
  `token_estimate` 仍只算审查上下文，docs/claude-backend-followup.md 的口径未变）；
  它自己的上限是：B ≤ 50 行 + C ≤ 200 行，实测本仓库 B+C = 3853 字符 ≈ 960 token。

## 5. 缓存与降级

| 项 | 策略 | 位置 |
|---|---|---|
| 成功结果 | 进程内长期缓存（run 的 head 提交不可变），同一 run 只拉一次 | `chat_inventory`（`:802`）/ `_chat_inventory_cached`（`:2853`） |
| 失败结果 | 进程内**冷却** `CHAT_INVENTORY_RETRY_SECONDS = 60s`：冷却期内直接复用失败文案、不再打网络；冷却过后下一轮自动重试 | 同上 |
| 拉取异常 | 只把**异常类名**写进注入段（`PRFetcher` 的异常文案可能夹 URL / token 片段），对话照常 | `_pr_files_section` / `_repo_tree_section` |
| 收集整体炸掉 | `_chat_repo_inventory` 吞异常、向 stderr 记一行 `repo inventory unavailable …`、返回空串 | `:2761` |
| run 读不到 | 返回空串（"读不到这次审查"已由审查上下文那段说明，不重复） | `_collect_repo_inventory`（`:2782`） |

失败冷却的理由：B 是**每轮**注入的，网络长时间不通时不该每一轮都付一次"带重试的网络
等待"（`PRFetcherConfig.max_retries = 3` + 指数退避）；而一次抖动也不该锁死整个会话——
冷却过后自动重试即可恢复。

## 6. 验证

### 6.1 测试

| 文件 | 结果 | 新增用例 |
|---|---|---|
| `tests/test_jsonl_backend.py` | **244 passed** | 8 |
| `tests/test_repo_context.py` | **39 passed** | 13 |
| 全量 `python -m pytest -q --no-cov` | **1328 passed, 1 skipped**（87.5s） | — |

新增用例（`test_jsonl_backend.py`）：

| 用例 | 钉住的行为 |
|---|---|
| `test_chat_findings_fallback_covers_every_named_file` | 12 条 finding / 3 个文件 → 三个都进注入；`_findings_file_paths` 返回全部 3 条 |
| `test_chat_findings_fallback_flags_the_file_over_the_char_budget` | 单行超长文件吃满预算 → 第三个文件被标注「本轮注入已达 12000 字符上限」 |
| `test_chat_injects_the_pr_changed_file_list_every_turn` | 每轮注入、`共 3 个，另有 12 个被跳过`、第二轮命中缓存（清单只拉一次） |
| `test_chat_cools_down_and_recovers_when_the_changed_list_cannot_be_read` | 失败降级文案 / 不泄漏异常 message / 冷却期内只拉一次 / 冷却过后自动恢复 |
| `test_chat_truncates_the_changed_file_list_over_the_limit` | 60 个文件 → 前 50 条 + `另有 10 个未列出` |
| `test_chat_never_fetches_inventory_without_a_bound_run` | 未绑定 → 两段都不注入、零调用（消息里全是结构关键词也一样） |
| `test_chat_injects_the_repo_tree_only_when_the_user_asks_about_structure` | 普通问题不注入不拉取；结构问题注入（head 提交 / 嵌套格式）；再问命中缓存 |
| `test_chat_reports_a_repo_tree_it_could_not_read` | 拉取失败 → `（未能读取仓库目录树：RuntimeError）`；老 run 无 head_sha → 各自原因、不打 GitHub |

`test_repo_context.py` 新增 `TestRenderPrFileList`（5 条：表头计数 / 省略跳过子句 /
截断计数 / 不可用文案 / 控制字符路径剔除）与 `TestRenderRepoTree`（8 条：目录在前的
嵌套格式 / sha 表头 / 深度折叠 / 兄弟均分 / 单目录上限 / 噪声过滤 / 空与不可用两态）。

被改写的既有用例：`test_chat_without_a_mentioned_path_never_asks_github` →
`test_chat_without_a_mentioned_path_never_fetches_repo_file_content`——B 之后"绑定 run"
本身会带来一次清单拉取，旧断言"零请求"不再成立；现在把"文件内容"与"清单"分开断言。

### 6.2 证据脚本（离线）

`python .pytest_claude/verify_repo_structure_context.py` → `ALL OK`：

```
[1] fetch_changed_file_paths -> ['src/a.py', 'website/index.html', 'docs/design.md']
    问到的 PR = [('example', 'repo', 31)] | 分页请求 = [0]
[2] fetch_repo_tree_paths -> ['src/a.py', 'README.md']          ← tree 条目被丢掉
    参数 = {'owner': 'example', 'repo': 'repo', 'ref': 'bbbb…', 'recursive': True}
[3] ## 本次 PR 变更文件（共 4 个，另有 11 个被本次审查跳过） …
[4] ## 仓库目录树（head 提交 bbbbbbbb · 深度 ≤3 · 最多 200 行） …（普通问题不注入）
    调用计数：变更清单 = 1 | 目录树 = 1（三轮对话，进程内缓存生效）
[5] 12 条 finding 涉及 4 个文件 → 全部进入注入（旧实现写死 limit=2）
    拉取的文件内容调用 = [website/index.html, src/a.py, src/b.py, src/c.py]
```

[1][2] 用的是**真** `PRFetcher` 方法，形状是替身 PyGithub 对象（`get_page` /
`get_git_tree`），因此覆盖了 URL 解析、分页、`recursive=True` 透传与 blob 过滤——
这三处正是 `tests/test_pr_fetcher.py`（不在 write_scope）本来该管的部分。

## 7. 未决与边界

1. **`tests/test_pr_fetcher.py` 不在本次 write_scope**：两个新方法没有进该文件的单测，
   由 §6.2 的证据脚本覆盖。若后续放开，应把 [1][2] 两步搬成正式用例。
2. **B/C 不计入 `chat_context_budget`**：`/context` 的 token 估算仍只算审查上下文。
   若要让用户看到"这次注入总共花了多少"，应扩展 `_context_status` 而不是悄悄改口径。
3. **C 的误判**：意图按子串匹配，"决策树"/"树形控件"这类词也会触发（多一次 git tree
   调用，有缓存）。要更准需要分词/意图分类，收益不抵复杂度。
4. **点目录整体排除**（保留 `.github` / `.devcontainer`）：主代码若藏在点目录下会看不到；
   注入段里的"已排除…"文案保证了这不会被说成"不存在"。
5. **`excluded_files` 由审查阶段写入**：`skipped` 只反映 run 记录，不重新计算过滤规则；
   老 run 没有这个数字时整句省略。
6. **缓存是进程内的**：重启后第一次问会重新拉一次清单/树（失败冷却也随之重置）。
   `chat_inventory` 按 `run_id` 累积（每段约 2–6 KB，不清理）；与 `sessions` 同一量级，
   真要收敛得等"会话/缓存回收"统一做。并发（两个会话绑同一 run 同时提问）最多各拉一次，
   后写入者覆盖先前结果——两段都是同一 head 提交的确定性渲染，覆盖无害。
7. **未做真实联网验证**：本任务约束禁止真实网络请求；`fetch_changed_file_paths` /
   `fetch_repo_tree_paths` 的真实 GitHub 行为（分页、限流、大仓库树）只有替身级证据。
8. **无 TUI 改动**：没有"正在读取仓库结构…"的进度提示；两段注入分别对应 1 次
   API 调用（首轮），延迟与一次普通工具调用同级。
