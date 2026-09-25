# mimo-repo-context 交付说明（L1-a）

- 任务：`mimo-repo-context`
- 目标：仓库感知 L1-a —— `RepoContextProvider` 预取服务 + 缓存接口 + 截断/预算/降级 + 单测
- 日期：2026-09-25
- 根目录：`C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant`
- 写入范围（仅此三份）：
  - `src/ai_pr_review/services/repo_context.py`
  - `tests/test_repo_context.py`
  - `docs/mimo-repo-context.md`

## 1. 设计边界

与 `docs/repo-aware-review-plan.md` §4 对齐，但本模块是**纯逻辑 + 依赖注入**：

| 不做 | 原因 |
|---|---|
| 不 import PyGithub | 读取通过注入的 `read_file` |
| 不 import `ai_pr_review.config` | 配置项在 L1-b 注入，保持可测 |
| 不读凭据 / 不做 git | 任务约束 |
| 不改其它模块 | write_scope 限制 |

`read_file: Callable[[str], str | None]` 接受「相对仓库根的路径」，`owner/repo/ref` 由调用方闭包绑定。

## 2. 公开 API

### `RelatedFile`（`@dataclass(slots=True)`）

| 字段 | 类型 | 含义 |
|---|---|---|
| `path` | `str` | 仓库根相对路径（`/` 分隔） |
| `reason` | `str` | `"test"` \| `"import"` \| `"init"` |
| `content` | `str` | 已截断的内容 |
| `truncated` | `bool` | 是否截断 |
| `from_cache` | `bool` | 是否来自缓存 |

### `RepoCache(Protocol)`

```python
def get(self, key: str) -> str | None: ...
def put(self, key: str, content: str) -> None: ...
```

稳定 key = 归一化后的仓库根相对路径。缓存存**原始全文**，截断在返回前做。

### `RepoContextProvider`

```python
RepoContextProvider(
    read_file: Callable[[str], str | None],
    cache: RepoCache | None = None,
    max_files: int = 3,
    budget_tokens: int = 4000,
)
collect_for_file(file_path: str) -> list[RelatedFile]
```

## 3. 预取策略

对变更文件 `path/to/mod.py`（仅 `.py/.ts/.tsx/.js/.jsx`，否则 `[]`）：

1. **同名测试文件**（候选依次尝试，**首个命中即收**）  
   `path/to/test_mod.py` → `tests/test_mod.py` → `tests/path/to/test_mod.py` → `test/test_mod.py`
2. **Python 相对导入**（`from .X import` / `from ..X.Y import` / `from . import X`）  
   折算为仓库根相对模块路径，**优先 `模块.py`，其次 `模块/__init__.py`**
3. **同目录 `__init__.py`**（变更文件本身不是它时）

优先级即上述顺序；按路径去重；总数上限 `max_files`。

### 截断

| 类型 | 上限 |
|---|---|
| 测试文件 | 120 行 |
| 导入 / init | 80 行 |

超限时取 **首个** `def`/`class`（含 `async def`）定义行 ±20 行；无定义则取文件头 `max_lines` 行，`truncated=True`。

### 预算

- 4 字符 ≈ 1 token，预算 `budget_tokens * 4` 字符；
- 超出时从**优先级最低**的条目开始丢弃；
- 若存在能单独放进预算的条目，则至少保留一条。

### 缓存与降级

- 每个文件先 `cache.get(key)`；命中 → `from_cache=True`，**不再调用** `read_file`；
- 未命中 → `read_file` 后 `cache.put`；
- `read_file` 抛异常或返回 `None` → 跳过该候选，**绝不向上抛**；
- `max_files <= 0` → 直接 `[]`。

## 4. 测试覆盖（`tests/test_repo_context.py`）

| 用例组 | 覆盖点 |
|---|---|
| CollectionOrderAndLimits | 测试优先、同目录优于 tests/ 根、回退 tests/、去重、`max_files` 上限、`=0` 空、非源码空 |
| Truncation | 超长测试文件/导入文件 `truncated=True` 且保留定义附近、无定义取头、短文件不截断 |
| Cache | 命中 `from_cache=True` 且 `read_file` 计数不增、缓存命中仍截断 |
| Degradation | 某候选抛异常仍继续、测试候选异常落到下一候选、缺失文件跳过 |
| Budget | 超预算丢最低优先级、至少保留一条、预算按截断后大小计 |
| RelativeImports | 单点、`..` 两级、`..X.Y`、优先 `.py`、回退 `__init__.py`、`from . import`、非 Python 跳过 |
| RelatedFileShape | 字段形状 |

## 5. 验证命令

```powershell
New-Item -ItemType Directory -Force -Path .pytest_x
$env:TEMP = (Resolve-Path .pytest_x).Path
$env:TMP  = $env:TEMP
python -m pytest tests/test_repo_context.py -q --no-cov
python -m pytest -q --no-cov
```

结果见任务 report 的 evidence。

## 6. 未决 / 后续（L1-b+）

- 真实 `PRFetcher` / SHA 磁盘缓存接入（计划 §4.3 路径与 LRU）；
- `Preferences.repo_context*` 配置项与 `off` 开关；
- `FileContext.related_files` 注入与 Prompt 段格式冻结测试（计划 §4.5）；
- 可观测性 metadata（计划 §4.7）。
