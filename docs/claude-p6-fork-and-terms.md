# P6 项③+项②终端侧 交付报告：fork 元数据贯通与终端证据术语统一（任务 `claude-p6-fork-and-terms`）

**一句话结论**：`PRData` 现在携带 head 仓库（`head_repo_full_name` / 只读 `is_fork`），
`PRFetcher.fetch` 从 `pull.head.repo.full_name` 填充并容错被删除的 fork 仓库；两个编排器把
`{"fork": {"is_fork": bool, "head_repo": str | None}}` 写进 run metadata（**不加数据库列**），
`publish_service` 与 `cli.render_github_comment_report` 据此决定链接形式——fork 用
`…/pull/N/files`，同仓库与缺 metadata 的旧 Run 仍用 `blob/<sha>`；终端 `render_terminal`
的中文证据文案统一到计划 §1 词汇表（`校验通过 / 待人工确认 / 校验不成立 / 未校验`），
并与评论徽章共用同一张表。

- 任务类型：实现（可写 `models/pr_data.py`、`services/pr_fetcher.py`、
  `services/review_orchestrator.py`、`services/hybrid_orchestrator.py`、
  `services/publish_service.py`、`services/report_renderer.py`（仅终端文案）、`cli.py`、
  `tests/**`、本文件）
- 验证命令：`New-Item -ItemType Directory -Force -Path .pytest_x` → `TEMP`/`TMP` 指向它 →
  `python -m pytest -q --no-cov`
- 结果：**568 passed, 1 skipped**（本轮新增 10 + 3 + 5 + 1 + 6 = 25 个用例，见 §3）
- 未做：未读/打印凭据，未执行任何 git 操作，未修改 write_scope 之外的文件（含 `frontend/tui`
  与 `rule_catalog.py`），未联网、未向任何 PR 写入内容

## 1. 项③ fork 元数据贯通

### 1.1 数据模型（`models/pr_data.py:73,83-90`）

```python
head_repo_full_name: str | None = Field(default=None, description="PR 源分支所在仓库的 full name…")

@property
def is_fork(self) -> bool:
    head = (self.head_repo_full_name or "").strip()
    return bool(head) and head.lower() != self.repo_full_name.lower()
```

缺数据（`None` / 空串 / 纯空白）一律 `False`：字段加入前抓取的 PRData、被删除的 fork 仓库都
落在这一支。owner/repo 在 GitHub 上不区分大小写，因此比较前 `lower()`。

### 1.2 抓取（`services/pr_fetcher.py:124,153,171-186`）

`fetch` 与 `fetch_metadata` 都经 `_head_repo_full_name(pr)` 取 `pull.head.repo.full_name`，
三重容错：属性缺失（`AttributeError`）、值为 `None`（fork 仓库已删除）、值不是字符串（测试替身）
都返回 `None`。`None` 是「未知」，不是「同仓库」这个结论——下游 `is_fork` 才把未知归为非 fork。

### 1.3 run metadata（`review_orchestrator.py:329`、`hybrid_orchestrator.py:277`）

```python
"fork": {"is_fork": pr_data.is_fork, "head_repo": pr_data.head_repo_full_name},
```

写在既有的 `metadata_json` 列里，**没有新增数据库列**，历史库（`metadata_json` 为 NULL →
`get_run_metadata` 返回 `{}`）照旧可读。

### 1.4 发布路径（`publish_service.py:151-165,168-200,269-271,290`）

`_fork_info(metadata)` 读取该键：非 dict / 缺键一律 `(False, None)`；`head_repo` 非字符串或空白
按 `None`。`_stored_run_pr_data(..., head_repo_full_name=…)` 让重建的 PRData 也带上 head 仓库，
`GitHubCommentMeta.from_fork = fork_flag or pr_data.is_fork`（**flag 优先**：fork 仓库被删除时
只剩 `is_fork=True`，此时仍必须走 PR files 链接）。

`cli.render_github_comment_report`（`cli.py:1647`）用 `artifacts.pr_data.is_fork` 填 `from_fork`，
所以 `--publish-comment` 的会话内评论与 `/publish` 的历史重新渲染口径一致。

### 1.5 实测链接形式

| 场景 | 位置链接 |
|---|---|
| 同仓库 Run / 缺 `fork` 键的旧 Run | `https://github.com/owner/repo/blob/head-sha/src/module_0.py#L1` |
| fork Run（`head_repo=contributor/repo`） | `https://github.com/owner/repo/pull/31/files` |
| fork 仓库已删除（`head_repo=None, is_fork=True`） | `https://github.com/owner/repo/pull/31/files` |

评论正文实测（`.pytest_x/p6_sample.txt`）：

```text
1. 🛑 **SQL Injection in user query** · [`src/services/user.py:45-52`](https://github.com/owner/repo/blob/head123/src/services/user.py#L45-L52) · 95% · ✅ 校验通过
1. 🛑 **SQL Injection in user query** · [`src/services/user.py:45-52`](https://github.com/owner/repo/pull/123/files) · 95% · ✅ 校验通过   # 同一 finding，from_fork=True
```

## 2. 项② 终端术语统一（`services/report_renderer.py`）

### 2.1 唯一真源

新增模块级 `EVIDENCE_STATUS_LABELS`（`:91`）与 `_evidence_key`（`:101`）、`_EVIDENCE_ICONS`（`:107`）：

| status | 中文 | English | 徽章图标 |
|---|---|---|---|
| `valid` | 校验通过 | validated | ✅ |
| `needs_review` | 待人工确认 | needs review | 🔍 |
| `invalid` | 校验不成立 | invalid | ⛔ |
| `unverified` | 未校验 | unverified | ❔ |

评论徽章 `_github_evidence_badge`（`:624-633`）改为查这张表，输出与改造前逐字节一致
（`✅ 校验通过` 等）；终端明细行与汇总行查同一张表，因此同一 status 在两条渲染路径上必然是同一个
中文词（`tests/test_report_renderer.py::test_terminal_and_comment_agree_on_the_chinese_evidence_word`
对四个状态逐一比对）。

### 2.2 终端文案

```text
│ 证据状态 校验通过 1 · 待人工确认 1 · 校验不成立 0 · 未校验 0  │
…
│ 证据   校验通过 · 来源：ai_analysis                        │
```

- 汇总行（`:271-277`）用全称而非简写：`无效` 与明细的 `校验不成立` 并排会被读成两个状态；
- 明细行（`:311`）不再出现「证据有效 / 证据不成立」——校验器只证明「位置与片段自洽」，
  说「证据有效」是过度承诺；
- 英文文案未改（`validated / needs review / invalid / unverified`，评论徽章英文同理）；
- 顺带修一处潜在崩溃：汇总计数原先用 status 直接索引字典，词汇表外的值会 `KeyError`；
  现在与评论徽章一样归一到 `unverified`（`_evidence_key`）。

## 3. 测试

| 文件 | 新增 |
|---|---|
| `tests/test_pr_fetcher.py` | `TestPRData`：缺省/同仓库/大小写差异/跨仓库/空白 head 仓库的 `is_fork`；`TestPRFetcherFetch`：`fetch` 记录同仓库与 fork、容错被删除的 fork（`head.repo=None`）与无 `full_name` 的替身、`fetch_metadata` 同样记录 |
| `tests/test_review_orchestrator.py` | `ForkStubPRFetcher` + `RecordingResultStore`：标准/混合编排器分别写 `fork` 元数据，同仓库 run 为 `{"is_fork": False, "head_repo": None}` |
| `tests/test_jsonl_backend.py` | `fork` 元数据 JSON 往返；fork 预览用 `…/pull/31/files` 且不含 `/blob/head-sha/`；fork 仓库被删除时同上；同仓库 Run 仍用 blob；缺 metadata 的旧 Run 仍用 blob |
| `tests/test_cli.py` | fork PR 的 `--publish-comment` 评论用 files 链接且不出现 blob，同时 run metadata 记录 `fork` |
| `tests/test_report_renderer.py` | 终端四态词汇表（汇总行 + 明细行，且断言不含「证据有效/证据不成立」）；终端与评论逐状态同词比对（4 个参数化用例）；词汇表外 status 回退「未校验」 |

## 4. 未决项 / 留给集成验收

1. 三处术语比对（计划 §6）本轮只覆盖终端 + 评论两处；TUI 侧由 `mimo-p6-evidence-terms`
   改动 `frontend/tui/src/review-ui/helpers.ts`，本任务未触碰该目录，未做端到端比对。
2. `web/`（React 前端 `web/src/pages/ReviewPage.tsx`、`web/src/components/ui.tsx`）仍用
   「证据有效 / 证据不成立」旧词，不在本任务写入范围，未改。
3. 会话内 `--publish-comment` 走 `artifacts.pr_data.is_fork`（新抓取的数据必然有 head 仓库），
   历史 Run 走 metadata；两者都缺时按同仓库处理（blob），这是既定语义，不是静默兜底。
