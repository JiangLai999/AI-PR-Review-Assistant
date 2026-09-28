# L2 数据源侦察：Code Search vs Trees+Fetch+Grep

- 任务：`mimo-l2-recon`（只读实测 + 文档，不改源码）
- 目标仓库：`JiangLai999/AI-PR-Review-Assistant`（public，默认分支 `main`）
- 认证：`GITHUB_TOKEN` 仅从环境变量读入请求头（`Authorization: Bearer …`），未落盘、未写入本报告
- 实测窗口：2026-09-26（UTC+8）
- 工具：`curl.exe --ssl-no-revoke`（见「坑」§5.1）；计时取 curl `time_total` / Python `perf_counter`

对应设计：`docs/repo-aware-review-plan.md` §5（L2 符号级定位）。

---

## 1. 结论速览（可执行）

| 项 | 结论 |
|---|---|
| **主数据源** | **trees + 按需 contents fetch + 本地 grep** 作主路径 |
| **Code Search** | 仅作**机会性加速**，且必须先做**对照探针**；本次实测中它**整体不可用** |
| **一次审查成本（2 变更文件 / 3 符号）** | trees 1 次 + contents 3–6 次 ≈ **4–7 请求 / 3–7 s**（精简启发式）；最坏全量 55 次 / ~38 s |
| **限流风险** | core 5000/h 对本路径**安全**；`code_search` 仅 **10/min**，3 符号即可用掉 30% 配额，重试/并发极易 429 |
| **降级策略** | code search 429/403/`incomplete_results=true`/对照探针失败 → 立即回落 trees 路径；trees 结果按 **commit SHA + blob SHA** 缓存 |
| **最大坑** | Code Search 对**确有内容**的仓库也返回 0（含 `psf/requests` 对照）；本地工作树远超远端默认分支 |

---

## 2. 原始数据

### 2.1 GitHub Code Search API

命令模板（token 取自环境变量，不回显）：

```bash
curl -sS --ssl-no-revoke \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/search/code?q=<symbol>+repo:JiangLai999/AI-PR-Review-Assistant&per_page=5"
```

#### (1a) 任务指定的 3 个真实符号

| 符号 | HTTP | total_count | top3 path | 单次耗时 | x-ratelimit-remaining / limit |
|---|---:|---:|---|---:|---|
| `HybridReviewOrchestrator` | 200 | **0** | — | 951.5 ms | 9 / 10 |
| `build_review_context` | 200 | **0** | — | 1058.5 ms | 8 / 10 |
| `RepoContextProvider` | 200 | **0** | — | 660.1 ms | 7 / 10 |

响应体指纹（0 命中时）：

```json
{"total_count":0,"incomplete_results":true,"items":[]}
```

注意 **`incomplete_results: true`**——这不是“符号不存在”的可靠证据，而是“检索未完成”的信号。

#### (1b) 远端默认分支上**确实存在**的符号（正对照）

远端 `src/ai_pr_review/services/review_orchestrator.py`（contents 拉取 200，7912 B）内含 `class ReviewOrchestrator:`。仍查不到：

| 查询 | HTTP | total_count | 耗时 | remaining |
|---|---:|---:|---:|---:|
| `ReviewOrchestrator repo:JiangLai999/AI-PR-Review-Assistant` | 200 | **0** | 688.9 ms | 9 |
| `"ReviewOrchestrator" repo:…`（URL 编码后） | 200 | **0** | 646.6 ms | 9 |
| `repo:… path:src ReviewOrchestrator` | 200 | **0** | 1084.5 ms | 7 |
| `repo:… filename:review_orchestrator.py` | 200 | **0** | 682.5 ms | 6 |
| `repo:… language:python Orchestrator` | 200 | **0** | 671.6 ms | 5 |
| `ContextBuilder repo:…` | 200 | **0** | 670.0 ms | 8 |
| `import repo:… language:python` | 200 | **0** | 712.1 ms | 7 |

#### (1c) 跨仓库对照（排除“本仓库未建索引”）

| 查询 | HTTP | total_count | 耗时 | remaining | 备注 |
|---|---:|---:|---:|---:|---|
| `requests repo:psf/requests` | 200 | **0** | 657.2 ms | 8 | 同样 `incomplete_results:true` |

→ **Code Search 在本实测窗口内对任意仓库都返回空**，属于 API/索引侧故障或 token 能力降级，不是本仓库独有问题。

#### (1d) 查询语法坑

| 形式 | HTTP | 说明 |
|---|---:|---|
| `"ReviewOrchestrator"` 未做 URL 编码 | **400** | 引号导致 400，body 非 JSON |
| `%22ReviewOrchestrator%22`（`urllib.parse.quote`） | 200 | 合法但 `total_count=0` |

复现（PowerShell）：

```powershell
$q = [uri]::EscapeDataString('"ReviewOrchestrator" repo:JiangLai999/AI-PR-Review-Assistant')
curl.exe -sS --ssl-no-revoke -H "Accept: application/vnd.github+json" `
  -H "Authorization: Bearer $env:GITHUB_TOKEN" `
  "https://api.github.com/search/code?q=$q&per_page=5"
```

---

### 2.2 Git Trees API

```bash
curl -sS --ssl-no-revoke \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/JiangLai999/AI-PR-Review-Assistant/git/trees/HEAD?recursive=1"
```

| 指标 | 数值 |
|---|---|
| HTTP | 200 |
| 耗时 | **814.1 ms** |
| 响应字节 | **28 749 B** |
| `tree` 总条目 | **113** |
| `blob` 条目 | **94** |
| `truncated` | `false` |
| HEAD tree sha | `50b25c6256bb171de35cd2f86a8494a082949dbd` |
| x-ratelimit-remaining | 4999（core 桶） |

按扩展名过滤后的候选文件数：

| 扩展名 | 条目数 |
|---|---:|
| `.py` | 56 |
| `.js` | 2 |
| `.ts` / `.tsx` / `.jsx` | 0 |
| **候选合计**（.py/.ts/.tsx/.js/.jsx） | **58** |

---

### 2.3 降级路径：contents 拉取 + 本地 grep

命令模板：

```bash
curl -sS --ssl-no-revoke \
  -H "Accept: application/vnd.github.raw+json" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/JiangLai999/AI-PR-Review-Assistant/contents/<path>"
```

#### (3a) 任务要求的「3 个候选文件」抽样

选取规则：文件名与符号驼峰 token / 关键词（orchestr/context/review/repo/provider）匹配打分，取 top3。

| path | HTTP | 耗时 | bytes | lines | 三符号命中 |
|---|---:|---:|---:|---:|---|
| `tests/test_review_orchestrator.py` | 200 | 660.0 ms | 8 271 | 236 | 无 |
| `src/ai_pr_review/services/review_orchestrator.py` | 200 | 595.5 ms | 7 912 | 197 | 无 |
| `src/ai_pr_review/services/report_renderer.py` | 200 | 696.2 ms | 12 328 | 357 | 无 |

- 请求数：**3**
- 总耗时：**1 951.7 ms**
- 与 (1) 是否一致：**一致（都是 0 命中）**——因为这 3 个符号在**远端默认分支根本不存在**（见 §3）。

#### (3b) 智能候选（按符号相关文件名）

| path | HTTP | 耗时 | bytes |
|---|---:|---:|---:|
| `src/ai_pr_review/cli.py` | 200 | 809.8 ms | 58 121 |
| `src/ai_pr_review/services/context_builder.py` | 200 | 746.8 ms | 16 896 |
| `src/ai_pr_review/services/review_orchestrator.py` | 200 | 590.8 ms | 7 912 |
| `tests/test_cli.py` | 200 | 958.3 ms | 63 642 |
| `tests/test_context_builder.py` | 200 | 606.5 ms | 4 506 |
| `tests/test_review_orchestrator.py` | 200 | 590.0 ms | 8 271 |

- 请求数：**6**；总耗时：**4 302.2 ms**；三符号命中：**0**（符号不在远端）

#### (3c) 全量基线：远端全部 `src/` + `tests/` 下 `.py` 逐文件 grep

对 **远端确实存在** 的 `ReviewOrchestrator` / `ContextBuilder` 做穷尽检索，作为 trees 路径的 ground truth：

| 指标 | 数值 |
|---|---|
| 请求数 | **55** |
| 总耗时 | **38 456.5 ms（≈38.5 s）** |
| 总传输字节 | **403 906 B** |
| 单文件耗时区间 | 590–958 ms |
| 单文件字节（典型） | 4–64 KB |

命中结果（可与 GitHub UI 人工核对）：

| 符号 | 命中文件 | 命中数 | 行号（前几条） |
|---|---|---:|---|
| `ReviewOrchestrator` | `src/ai_pr_review/cli.py` | 2 | 89, 748 |
| | `src/ai_pr_review/review_entry.py` | 3 | 18, 46, 53 |
| | `src/ai_pr_review/services/review_orchestrator.py` | 2 | 38, 196 |
| | `tests/test_review_orchestrator.py` | 4 | 1, 16, 173, 230 |
| `ContextBuilder` | `src/ai_pr_review/services/context_builder.py` | 1 | 71 |
| | `src/ai_pr_review/services/review_orchestrator.py` | 2 | 13, 45 |
| | `tests/test_cli.py` | 2 | 215, 362 |
| | `tests/test_context_builder.py` | 6 | 4, 51, 75, 90, 106, 114 |
| | `tests/test_review_orchestrator.py` | 2 | 158, 215 |

→ trees+fetch+grep **能稳定拿到跨文件引用**（L2 目标产物）。

---

## 3. 本地工作树 vs 远端默认分支（重要前提）

| 指标 | 本地工作树 | 远端 `main` (HEAD tree) |
|---|---:|---:|
| `.py` 文件数 | 124 | **56** |
| 过滤后总文件数 | 387 | **94** blobs |
| `HybridReviewOrchestrator` | 有（`cli.py`、`hybrid_orchestrator.py`） | **无** |
| `build_review_context` | 有（`services/review_context.py` 等） | **无** |
| `RepoContextProvider` | 有（`services/repo_context.py`） | **无** |

- 远端 `pushed_at = 2026-06-01T08:40:04Z`，默认分支内容**显著落后**本地（`py_only_local_count = 68`，`py_only_remote = 0`）。
- 任务指定的 3 个符号 **只存在于本地/未推送历史**，对远端 API 做检索时按设计就会是 0 命中。
- 远端缺的关键文件：`services/hybrid_orchestrator.py`、`services/review_context.py`、`services/repo_context.py`、`tests/test_repo_context.py`、`tests/test_jsonl_backend.py` 等（contents 返回 404）。

**因此**：(1) 与 (3) 的 0 命中在“符号是否存在于远端”这一点上**互相一致**；但 (1b)(1c) 证明 **Code Search 即便对存在的符号/文件也查不到**，所以不能把 code search 的 0 当作“无引用”。

---

## 4. 成本估算（一次审查：2 个变更文件 + 3 个待定位符号）

### 4.1 Code Search 主路径（理论）

| 项 | 数值 |
|---|---|
| 请求数 | 3（1 符号 1 次） |
| 总耗时 | ≈ 2.0–3.3 s（实测 0.57–1.09 s/次） |
| 配额 | `code_search` **10/min** → 3 次用掉 30%；`search` 桶 30/min |
| 是否会触发限流 | 单次审查不易；**10 符号/分钟即触顶**；并发审查、重试、多 PR 批处理会很快 429 |
| 本次实测可用性 | **否**（`incomplete_results:true` 且 0 命中，含跨仓库对照） |

### 4.2 Trees + 按需 fetch 主路径（推荐）

| 策略 | 请求数 | 总耗时 | 传输量 | 备注 |
|---|---:|---:|---:|---|
| trees + 3 个启发式文件 | 1+3 = **4** | ≈ 0.8+1.9 = **2.8 s** | ≈ 30 KB + 28 KB | §2.3(3a) |
| trees + 6 个智能候选 | 1+6 = **7** | ≈ 0.8+4.3 = **5.1 s** | ≈ 160 KB | §2.3(3b) |
| trees + 全量 src/tests py | 1+55 = **56** | ≈ 0.8+38.5 = **39.3 s** | ≈ 430 KB | §2.3(3c) ground truth |

限流（core 桶 5000/h）：

- 7 请求/审查 → 每小时可支撑 **~700 次**审查级定位，远不触顶；
- 56 请求/审查全量 → 每小时约 **89 次**，仍安全，但延迟不可接受（39 s）；
- **结论**：默认走启发式 3–6 文件；仅对 `critical/high` 且启发式无命中时升级到全量，且要有预算闸门。

### 4.3 限流对照表

| 桶 | limit | 实测观察 | 对 L2 的含义 |
|---|---|---|---|
| `code_search` | **10/min** | 每次 search 后 `X-RateLimit-Remaining` 递减 1（10→9→…→3） | 与设计文档“认证后 30 req/min”**不符**；必须按 10/min 设计 |
| `search` | 30/min | rate_limit 接口显示 | 与 code_search **分桶**，不能混用额度 |
| `core` | 5000/h | trees/contents 走此桶，实测 remaining 5000→4999 | trees+fetch 路径主预算 |

---

## 5. 坑清单（实测踩到）

### 5.1 运行环境

1. **Windows schannel 吊销检查失败**：`curl` 报 `CRYPT_E_REVOCATION_OFFLINE (0x80092013)`，Python `urllib` 报 `SSL: UNEXPECTED_EOF_WHILE_READING` / handshake timeout。  
   **缓解**：`curl.exe --ssl-no-revoke` 可稳定 200。生产代码若用 `httpx`/`requests`，需准备证书吊销降级策略，否则会表现为“随机网络错误”。
2. **Token 只允许出现在请求头**。调试命令若打印 argv 片段会泄露 token 前缀——脚本里禁止 echo Authorization。

### 5.2 Code Search API

3. **空结果 ≠ 无引用**：0 命中体带 `incomplete_results:true`；连 `requests repo:psf/requests` 都是 0。必须用**对照探针**（已知存在符号或知名公共仓库）判断检索是否可信，否则会得到错误的“无人调用”结论。
4. **只索引默认分支**（设计文档已列，实测吻合）：未推送 / 非默认分支 / PR head 上的符号永远查不到。
5. **配额是 10/min 不是 30/min**（`code_search` 桶）；`X-RateLimit-*` 响应头与 `rate_limit` 接口分桶一致。
6. **查询串必须 URL 编码**：裸 `"` 得 400。
7. **私有仓库 / 无 token**：本仓库 public，认证与匿名都能 200，但匿名 core 仅 60/h、search 10/min，匿名更易限流。私有仓库 code search 需要 `repo` scope token。
8. **老 REST code search 与新版搜索体验可能不一致**：本次只测了任务指定的 `GET /search/code`；若产品可切换 GraphQL/新 code search，需另测。

### 5.3 Trees / Contents

9. **`recursive=1` 可能 `truncated:true`**（大仓库）：本仓库 94 blobs / `truncated:false`；生产必须检查该标志，截断时改用分目录遍历。
10. **contents 一文件一请求**：全量 grep 成本线性膨胀（55 文件 ≈ 38 s）。应使用 trees 返回的 **blob sha** 走 `GET /git/blobs/{sha}`（内容寻址，可缓存、可并行、可去重）。
11. **大文件**：`cli.py` 58 KB / 1662 行，单次 contents 尚可；更大的 vendored 文件建议按字节预算截断后再 grep。
12. **远端 vs 本地漂移**：审查的是 PR 代码，L2 定位必须基于 **PR base/head 的 tree sha**，不能盲信 `HEAD`；本次 `HEAD` 已远落后本地。

### 5.4 与设计文档的差异

13. `docs/repo-aware-review-plan.md` §5 写“code search 一次请求拿结果 / 认证后 30 req/min”——实测为 **0 结果 + 10/min**，建议在实施前修订该节。
14. §5 降级描述“对候选文件惰性 fetch”方向正确，但需补充 **预算闸门、blob-sha 缓存、对照探针** 三项，否则会在 code search 失灵时静默产出错误结论。

---

## 6. 降级策略建议（可直接落地）

```
locate_symbol(symbol, repo, ref):
  1. 读缓存: key=(repo, ref_tree_sha, symbol) → 命中则返回
  2. 对照探针: code_search 查一个确定存在的公共符号（或本仓库 filename:探针）
     - 若 total_count==0 且 incomplete_results==true → 标记 search_untrusted，跳到 4
  3. code_search(q=symbol+repo:owner/name)
     - 200 且 total_count>0 → 返回并写缓存
     - 429/403/5xx / 0 命中 / incomplete_results → 记 fallback_reason，跳到 4
  4. trees 路径:
     - GET /git/trees/{ref}?recursive=1（缓存 by tree sha）
     - 按扩展名过滤候选；文件名/路径启发式打分
     - 预算内取 top-N（默认 N=6）fetch blob（by sha，缓存 by sha）
     - 本地正则 grep \b symbol \b
     - 无命中且 finding 为 critical/high 且预算允许 → 扩到全量 src/tests
  5. 结果元数据: source=code_search|trees_grep, fallback_reason, requests, elapsed_ms, truncated
```

- **缓存**：必需。trees 按 `tree sha`、文件内容按 `blob sha` 不可变缓存；符号命中表按 `(tree_sha, symbol)`。
- **并发**：contents/blobs 可 4–8 并发把 38 s 压到 ~5–8 s；注意 core 桶 5000/h 与单线程 ~600–900 ms/请求的实测延迟。
- **熔断**：连续 2 次 code search `incomplete_results` 或对照探针失败 → 本轮审查关闭 code search，只走 trees，并在报告 metadata 标注 `skipped_reason`。

---

## 7. 未决项

1. **Code Search 空结果的根因**未定位：token 能力、仓库索引缺失、还是 2026-09-26 时段的 GitHub 搜索降级？需换 token / 换时段复测。
2. **新版 GitHub Code Search（GraphQL / 新 search API）** 未测；若 REST 旧接口长期不可用，需要评估替代。
3. **PR head/base ref 的 trees 成本**未测（本次用 `HEAD`）；预期同量级，但 sha 选取逻辑需在实施时验证。
4. **非 Python 扩展名**（`.ts/.tsx/.js/.jsx`）远端为 0–2 个候选，前端在 `frontend/` `web/` 等本地目录未推送；真实 PR 上的多语言启发式阈值需再标定。
5. 本任务为只读侦察，**未跑 pytest**（prompt 不要求新增/修改测试；`write_scope` 仅 `docs/mimo-l2-recon.md`）。L2 实施阶段应按 §5「测试与验收」补 stub 单测与限流降级测试。

---

## 8. 复现清单

```powershell
# 0) 环境（Windows）
# 需要 curl.exe --ssl-no-revoke；token 仅从环境变量进请求头
$H = @('-H','Accept: application/vnd.github+json',
       '-H',"Authorization: Bearer $env:GITHUB_TOKEN",
       '-H','X-GitHub-Api-Version: 2022-11-28')

# 1) rate limit 分桶
curl.exe -sS --ssl-no-revoke @H https://api.github.com/rate_limit

# 2) code search ×3 符号（另加 ReviewOrchestrator / psf/requests 对照）
curl.exe -sS --ssl-no-revoke @H `
  "https://api.github.com/search/code?q=HybridReviewOrchestrator+repo:JiangLai999/AI-PR-Review-Assistant&per_page=5"

# 3) trees
curl.exe -sS --ssl-no-revoke @H `
  "https://api.github.com/repos/JiangLai999/AI-PR-Review-Assistant/git/trees/HEAD?recursive=1"

# 4) contents 抽样 + 本地 grep
curl.exe -sS --ssl-no-revoke `
  -H 'Accept: application/vnd.github.raw+json' `
  -H "Authorization: Bearer $env:GITHUB_TOKEN" `
  "https://api.github.com/repos/JiangLai999/AI-PR-Review-Assistant/contents/src/ai_pr_review/services/review_orchestrator.py"
```

关键数字一览：

| 指标 | 值 |
|---|---|
| code search 命中（3 任务符号） | 0 / 0 / 0 |
| code search 命中（对照 `ReviewOrchestrator`） | 0（`incomplete_results:true`） |
| code search 命中（对照 `psf/requests`） | 0（`incomplete_results:true`） |
| code search 耗时 | 572–1085 ms |
| trees | 200 / 814 ms / 28 749 B / 113 entries / 94 blobs |
| 候选文件（.py/.js） | 58（56 .py + 2 .js） |
| contents 单文件 | 590–958 ms |
| 3 文件抽样 | 3 req / 1 952 ms / 0 命中 |
| 全量 55 文件 grep | 55 req / 38 457 ms / 403 906 B / ReviewOrchestrator×4 文件 / ContextBuilder×5 文件 |
| 一次审查估算（3 符号） | search 3 req/2–3 s（不可用）或 trees 4–7 req/3–7 s |
| code_search 限额 | 10/min |
