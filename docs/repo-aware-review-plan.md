# 仓库感知审查方案（Repo-Aware Review）

状态：**L1 + L2 已实现**（2026-09-26），L3 进行中，L4 明确不做
—— 验收证据：`docs/l2-symbol-acceptance.md`（真实仓库逐行核对）、
`docs/mimo-l2-recon.md`（数据源实测）；实现记录：`docs/mimo-repo-context.md`（L1-a）、
`docs/mimo-repo-inject.md`（L1-b/接入）、`docs/claude-repo-config.md` 与
`docs/claude-tui-repo-context.md`（L1-c 配置入口）、`docs/mimo-l2-symbol-locator.md`（L2）
日期：2026-09-25
配套方案：`docs/dual-model-roles-plan.md`（CHAT/REVIEW 双槽 + 审查上下文）

---

## 1. 现状审计（2026-09-25）

### 1.1 已有能力

| 层级 | 能力 | 状态 | 代码位置 |
|---|---|---|---|
| L0 | 读**变更文件**的完整内容 | ✅ | `pr_fetcher.fetch_file_content(owner, repo, path, ref)`（PyGithub `get_contents`） |
| L0.5 | 变更文件的 AST 上下文（imports / 函数 / 类） | ✅ | `context_builder.ContextBuilder.build_context`（tree-sitter，`max_ast_items` 截断） |
| L0.6 | **变更文件之间**的符号引用关系 | ✅ | `analyzers/symbol_index.SymbolIndex`（"在**全部文件正文**中定位引用"——此处的"全部"= PR 变更文件集合） |
| L0.7 | 变更文件之间的接口影响（breaking change 提示） | ✅ | `analyzers/cross_file_interface.CrossFileInterfaceAnalyzer.build_relationship_map` |

### 1.2 缺失能力

| 层级 | 能力 | 状态 | 说明 |
|---|---|---|---|
| **L1** | 读仓库中**未被修改**的文件 | ❌ | 没有任何"按需读取/预取"入口；`fetch_file_content` 只被用于变更文件本身 |
| **L2** | 仓库级符号定位（找调用方/定义处） | ❌ | `SymbolIndex` 的输入只有 `list[tuple[FileDiff, FileContext]]`，天然看不见未变更文件 |
| **L3** | 生成修复 patch | ❌ | `Finding` 只有自然语言 `suggestion` |
| L4 | 直接提交修复 | ❌（建议维持） | 见 §7 风险 |

### 1.3 缺口的具体后果

PR 修改了 `workspace_entry.py` 中的一个函数签名，但仓库内另有 3 个文件调用它
（都未出现在本次 diff 中）。当前审查：

1. **看不见调用方** → 无法判断"这个签名变化会破坏调用点"，只能给泛泛的建议；
2. **误报**：模型被要求"审查这段改动"，缺少外部事实时容易给出无法核实的
   推断（如"这可能导致调用方出错"——对，但说不出具体哪个文件、哪一行）；
3. **无法回答追问**：用户在 chat 里问"还有谁在用这个函数"，系统无从回答。

---

## 2. 目标与非目标

### 目标

1. 审查时能读取**未被 PR 修改、但与变更相关的仓库文件**（测试、被导入模块、邻居模块）；
2. 在 finding 与报告中能引用**具体文件:行**的外部证据；
3. 所有仓库访问**可缓存、可预算、可降级**，不因外部 API 失败而中断审查。

### 非目标（本轮不做）

- 全仓库语义索引 / 向量检索（成本与复杂度不匹配当前阶段）；
- 自动修改用户仓库代码（生成 patch 属 L3，单独排期；自动提交永不做，见 §7）；
- 非 GitHub 平台（GitLab 等）。

---

## 3. 能力分级

| 级别 | 能力 | 输入 | 输出 | 成本 |
|---|---|---|---|---|
| **L1** | 相关文件预取 | 变更文件路径 + import 关系 | 相关文件内容（截断） | 每文件 1–3 次 API 调用（可缓存） |
| **L2** | 符号级定位 | 变更/新增的符号名 | 定义处 + 引用处（文件:行） | code search 1 次/符号 |
| **L3** | 修复建议 patch | 高置信度 finding + 相关文件 | unified diff 片段 | 模型 token（增量） |

L1 是其余两级的基础；本方案**优先交付 L1**。

---

## 4. L1 详细设计（本轮交付）

### 4.1 新模块：`services/repo_context.py`

```python
@dataclass(slots=True)
class RelatedFile:
    path: str
    reason: str          # "test" | "import" | "same_dir"
    content: str
    truncated: bool
    from_cache: bool

class RepoContextProvider:
    """按需读取仓库文件，带 SHA 缓存与预算控制。"""

    def __init__(self, config: AppConfig, fetcher: PRFetcher) -> None: ...

    def collect_for_file(
        self, *, owner: str, repo: str, ref: str, file_path: str,
    ) -> list[RelatedFile]:
        """按 §4.2 的策略返回相关文件（已去重、已排序、已截断）。"""

    def read_file(self, *, owner: str, repo: str, ref: str, path: str) -> str | None:
        """单文件读取（含缓存）。失败返回 None，不抛异常。"""
```

### 4.2 预取策略（启发式，**零模型成本**）

对每个变更文件 `path/to/mod.py` 依次尝试（命中即收集，去重）：

| 优先级 | 规则 | 示例 |
|---|---|---|
| 1 | **同名测试文件**（多候选路径） | `path/to/test_mod.py`、`tests/test_mod.py`、`tests/path/to/test_mod.py`、`test/test_mod.py` |
| 2 | **相对导入目标**（解析 import 语句） | `from .config import X` → `path/to/config.py`；`from ..utils import y` → `path/utils.py` |
| 3 | **同目录 `__init__.py`**（若变更文件非该文件） | `path/to/__init__.py` |
| — | ~~同目录全部邻居~~ | **不做**（噪音大、请求数不可控） |

**上限**：

- 每个变更文件最多 **3 个**相关文件（`preferences.repo_context_max_files`）；
- 每个相关文件最多注入 **N 行**（默认：测试文件 120 行 / 导入模块 80 行，
  超限时保留**符号定义附近**的片段并标记 `truncated=True`）；
- 每个变更文件的相关文件总预算 **4000 tokens**（`preferences.repo_context_budget_tokens`）。

**排序**：测试文件优先（对"是否破坏行为"最有信息量），其次导入模块，最后 `__init__.py`。

### 4.3 缓存设计

```
%LOCALAPPDATA%/ai-pr-review/repo_cache/<owner>__<repo>/<sha>/<path 的安全化名称>.txt
```

- **按 commit SHA 分目录**：内容不可变，命中即永久有效；
- 缓存命中 → **零 API 调用、零 rate limit 消耗**；
- 写入用 `tempfile` + `os.replace`（沿用项目既有 hardened-write 惯例）；
- 缺失/损坏缓存视为未命中，不抛异常；
- 规模控制：目录超过 `preferences.repo_cache_max_mb`（默认 200MB）时按 mtime 清理最旧条目（**审查开始前**检查一次，不在关键路径上做全量扫描）。

### 4.4 失败与限流

| 场景 | 行为 |
|---|---|
| GitHub 404（文件不存在） | 跳过该候选，不视为错误 |
| 401/403（权限/限流） | 记 warning，**关闭本轮的后续预取**，审查照常继续 |
| 网络超时 | 单文件重试沿用 `PRFetcher._execute_with_retry`；仍失败则跳过 |
| 任何异常 | **绝不让预取失败中断审查**（与现有"逐文件失败不影响整轮"一致） |

复用 `PRFetcher` 的 `_rate_limiter`（token bucket），不新建限流器。

### 4.5 注入点

现有链路：

```
hybrid_orchestrator.review()
  → fetch_file_content(变更文件) → ContextBuilder.build_context() → FileContext
  → PromptAssembler.build_user_prompt(context) → 模型
```

新增（在 `build_context` 之后、`build_user_prompt` 之前）：

```
  → RepoContextProvider.collect_for_file() → list[RelatedFile]
  → 附加到 FileContext（新增可选字段 related_files）
  → PromptAssembler 在 user prompt 末尾追加「## 相关仓库文件（未被本次修改）」段
```

**Prompt 段格式**（固定、可测试）：

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

**System prompt 的诚实约束**（与证据优先原则一致）：

> 相关文件仅用于核实影响面。引用它们时必须给出 `文件:行`；
> 未在上下文中出现的文件内容不得臆测。

### 4.6 配置项（`Preferences`）

```python
repo_context: str = "tests+imports"   # off | tests | tests+imports
repo_context_max_files: int = 3
repo_context_budget_tokens: int = 4000
repo_cache_max_mb: int = 200
```

- 非法值回退默认并 warning（沿用 `workbench_mode` 的处理惯例）；
- `off` = 完全关闭（零额外请求，行为与今天一致）；
- 可在配置助手第 5 阶段增加三选一（off / 测试文件 / 测试+导入），默认
  `tests+imports`。

### 4.7 可观测性

- 审查报告的 metadata 增加：
  ```json
  "repo_context": {
    "files": ["tests/test_auth_service.py", "path/to/config.py"],
    "from_cache": 1,
    "truncated": ["tests/test_auth_service.py"],
    "skipped_reason": null
  }
  ```
- 报告页脚/工作台可显示"已参考 N 个相关文件"（TUI 展示属可选，后端先落数据）；
- 与 `/explain`、`/context` 打通：chat 绑定的上下文里包含该清单。

### 4.8 测试清单

| # | 用例 | 断言 |
|---|---|---|
| 1 | 预取策略：给定文件树与 import 语句 | 返回期望文件列表、顺序正确（测试优先） |
| 2 | 上限：候选 > 3 个 | 只取 3 个 |
| 3 | 截断：文件超长 | `truncated=True`，保留定义附近片段 |
| 4 | 缓存：同一 SHA 二次调用 | 第二次零 fetch（stub 计数 == 1） |
| 5 | 失败降级：fetch 抛异常 | 审查正常完成，`skipped_reason` 有值 |
| 6 | `off` 配置 | 零额外 API 调用，prompt 中无相关文件段 |
| 7 | prompt 段格式 | 与 §4.5 的固定格式逐字一致（冻结测试） |
| 8 | 私有仓库 token 路径 | 使用 `config.github_token`，缺 token 时按匿名（公开仓库）行为 |

### 4.9 验收标准

1. **真实 PR 对比**：同一 PR 在 `off` 与 `tests+imports` 下各跑一次，报告
   metadata 的 `repo_context.files` 非空，且至少一条 finding 引用了
   **未在 diff 中出现的文件**（文件:行可在 GitHub 上核对）；
2. 二次运行（同 SHA）API 调用次数为 0（日志/计数器证明）；
3. 断网/限流场景：审查不中断，且报告如实标注 `skipped_reason`；
4. 全量测试绿。

---

## 5. L2 设计（符号级定位，次轮）

**目标**：回答"这个函数/类在仓库里还被谁使用"。

### 数据源（按优先级）

1. **GitHub Code Search API**：`GET /search/code?q=<symbol>+repo:<owner>/<repo>`
   - 优点：一次请求拿结果；缺点：只索引**默认分支**、有速率限制（认证后 30 req/min）；
   - 私有仓库需要 token（现有 `github_token` 已支持 `repo` scope）。
2. **降级方案**：`GET /git/trees/<sha>?recursive=1` 拉全仓库路径清单（1 次请求），
   按扩展名过滤 → 对候选文件**惰性** fetch + 正则匹配（受 §4 的预算约束）。

### 集成点

- 触发时机：变更文件里出现**签名变化**（`symbol_index` 已有的 signature 指纹）时，
  对变化的符号做一次定位；
- 结果写入 `CrossFileReference`（已有模型），扩展来源字段为
  `"changed_files" | "repo_search"`，报告里可区分；
- 注入格式与 L1 兼容（同样走「相关仓库文件」段，但标注"仓库检索"）。

### 测试与验收

- 单测：stub search 返回 → 解析出 文件:行；
- 真实：对一个确有跨文件调用的 PR，验证检索到的引用可在 GitHub 上核对；
- 限流降级：search 429 → 回落到 trees 方案或跳过（不中断审查）。

---

## 6. L3 设计（修复建议 patch，可选）

- `Finding` 增加可选字段 `suggested_patch: str`（unified diff 片段，
  仅针对**已拿到相关文件内容**的 finding 生成）；
- 生成时机：审查完成后，对 `critical/high` 且 `evidence_status == "valid"`
  的 finding 单独做一次"补丁生成"调用（可选、计入成本）；
- 展示：报告与 TUI finding 详情里以代码块展示；**不自动提交、不自动创建 PR**；
- 测试：patch 格式合法性（可被 `git apply --check` 解析的语法级校验）+ 有/无相关文件两种路径。

---

## 7. 风险与边界

| 风险 | 说明 | 缓解 |
|---|---|---|
| GitHub rate limit | 认证 5000 req/h；一次审查最坏 3N 次调用 | 缓存 + 每文件上限 + 403 后关闭本轮预取 |
| Token 预算膨胀 | 相关文件占满上下文 | 每文件预算 4000 tokens + 截断保定义附近 |
| 噪音引入 | 不相关文件降低审查质量 | 严格的三类启发式；`off` 可完全关闭；metadata 可审计 |
| 私有代码外发 | 用户仓库代码被发送到云端模型 | 配置项 `off`；配合 CHAT/REVIEW=本地实现"代码不出本机" |
| 权限过大 | 未来若做 L4 自动提交会有写权限风险 | **本轮明确不做 L4**；L3 只输出建议，不落盘到用户仓库 |

---

## 8. 分期与工作量

| 阶段 | 内容 | 规模 |
|---|---|---|
| **L1-a** | `RepoContextProvider` + 缓存 + 预取策略 + 单测 | ~1 轮 |
| **L1-b** | `FileContext.related_files` + PromptAssembler 注入 + 冻结测试 | ~1 轮 |
| **L1-c** | 配置项 + 配置助手三选一 + metadata 落库 + 真实 PR 验收 | ~1 轮 |
| L2 | 符号定位（search + trees 降级） | ~2 轮 |
| L3 | 修复建议 patch（可选） | ~1–2 轮 |

**L1 总计 2–3 轮**；与 `docs/dual-model-roles-plan.md` 的双槽/上下文方案
**互相独立**，可并行开发（不同模块，写集不重叠）。

---

## 9. 与比赛演示的关系

可演示的完整叙事（当前 demo 脚本的增强版）：

1. 打开一个真实 PR（改动一个被多处调用的函数）；
2. 审查完成 → finding **明确引用仓库中未被修改的调用点**（`a.py:12`、`b.py:34`）；
3. 在 chat 中追问"这些调用点需要一起改吗" → 基于绑定的审查上下文回答；
4. `/explain` 展示证据校验状态；报告 metadata 展示"参考了哪些仓库文件"。

这套叙事同时体现三个能力：仓库感知、证据可审计、双模型分工。
