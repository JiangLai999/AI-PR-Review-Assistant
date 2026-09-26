# L2 符号级定位实施：RepoSymbolLocator（trees + grep）

- 任务：`mimo-l2-locator`
- 对应设计：`docs/repo-aware-review-plan.md` §5；数据源侦察：`docs/mimo-l2-recon.md`
- 交付日期：2026-09-26

---

## 1. 结论速览

| 项 | 落地 |
|---|---|
| **数据源** | trees + 按需 contents + 本地 grep（code search 不用，理由见 recon） |
| **新模块** | `src/ai_pr_review/services/symbol_locator.py` |
| **集成点** | `ReviewOrchestrator`（签名变化 → 定位 → `symbols_located` + CrossFileReference） |
| **触发条件** | 变更文件接口签名真实变化（复用 `SymbolIndex.compare_with`）；无变化零请求 |
| **配置开关** | `preferences.symbol_locate: bool = True` |
| **降级** | 读树/读文件/正则/缓存任一异常 → 返回已收集结果，绝不向上抛 |
| **测试** | `tests/test_symbol_locator.py` 38 项；全量 `895 passed, 1 skipped` |

---

## 2. `RepoSymbolLocator` 接口

### 2.1 `SymbolLocation`

```python
@dataclass(slots=True)
class SymbolLocation:
    path: str
    line: int
    snippet: str
    source: str = "repo"
```

### 2.2 构造（纯依赖注入，不直接调 GitHub API）

```python
RepoSymbolLocator(
    read_tree: Callable[[], list[str]],       # 仓库相对路径列表
    read_file: Callable[[str], str | None],   # 单文件全文；读不到返回 None
    cache: RepoCache | None = None,           # 复用 repo_context.RepoCache 协议
    max_requests: int = 15,
    max_results_per_symbol: int = 5,
)
```

- `RepoCache` **不新造接口**，直接复用 `services/repo_context.py` 的 `RepoCache` 协议（`get(key) -> str | None` / `put(key, content)`）。
- 生产侧由编排器注入：`read_tree` 走 PR head SHA 的 recursive tree，`read_file` 走 `PRFetcher.fetch_file_content`，`cache` 为 `FileSystemRepoCache(owner, repo, head_sha)`（按 blob 路径缓存正文，目录已按 SHA 隔离）。

### 2.3 `locate(symbol, *, exclude_paths=None) -> list[SymbolLocation]`

流程：

1. `read_tree()` 拿全部路径；失败 → 返回 `[]`。
2. 过滤源码扩展名（复用 `repo_context.SOURCE_EXTENSIONS` = `.py/.ts/.tsx/.js/.jsx`）。
3. 跳过 `exclude_paths`（编排器传入**全部 PR 变更文件**，保证只报「未被 PR 修改的文件里的引用点」）。
4. **稳定排序**（见 §3）。
5. 逐文件：缓存优先 → 未命中才 `read_file`；标识符边界正则
   `(?<![A-Za-z0-9_])symbol(?![A-Za-z0-9_])`
   （与 `symbol_index._reference_pattern` 同思路）。
6. 命中行整行作为 `snippet`，超过 200 字符截断加 `…`。
7. **停机条件**（先到先停）：
   - 命中数 ≥ `max_results_per_symbol`，或
   - **真实** `read_file` 次数 ≥ `max_requests`（**缓存命中不计入**）。
8. 任何异常（读树 / 读文件 / 正则编译 / 缓存 I/O）→ 降级返回已收集结果，**绝不向上抛**。

---

## 3. 排序策略（可复现）

候选文件按 `(score 降序, path 字典序)` 稳定排序：

| 条件 | 加分 |
|---|---:|
| 文件名（不含目录、不含扩展名）包含完整符号名（大小写不敏感） | +2 |
| 文件名包含符号的任一词元（`buildReviewContext` → `build/review/context`，长度 ≥ 3） | +1/词元 |

同分按路径字典序。理由（recon §2.3(3a)）：定义/调用方文件常以符号关键词命名（`orchestr/context/review/...`），先读它们能在 `max_requests` 预算内更早命中；打分只依赖路径与符号名，与扫描顺序无关，结果可复现。

---

## 4. 编排器集成（为何选 `ReviewOrchestrator`）

### 4.1 选择理由：改动最小

| 编排器 | 签名对比 | 接口影响 | 决定 |
|---|---|---|---|
| `ReviewOrchestrator` | 已有 `_load_base_signatures` + `SymbolIndex.compare_with` | 已有 `interface_impacts` 写入 run metadata | **选它**：签名变化检测、metadata 通道、CrossFileReference 模型都在现成路径上，只需挂一个定位步骤 |
| `HybridReviewOrchestrator` | **无** | **无** | 若在此集成需先补 base 签名加载与接口分析，远超「改动最小」 |

因此 **只改 `review_orchestrator.py`**；`hybrid_orchestrator.py` 在 write_scope 内但本次不动。若后续 hybrid 也要 L2，应先把签名对比抽成共享步骤再复用。

### 4.2 触发与数据流

```
_load_base_signatures()          # 已有：PR base 版本签名
        ↓
_cross_file_interface.analyze()  # 已有：interface_impacts（只在签名真实变化时非空）
        ↓
_locate_changed_symbols()        # 新增：仅当 impacts 非空 且 preferences.symbol_locate
        ↓
  RepoSymbolLocator.locate(symbol, exclude_paths=变更文件集)
        ↓
  symbols_located: {symbol: ["path:line", ...]}   → run metadata
  CrossFileReference(symbol, file=定义文件, line, referencing_file=命中文件)
        → 并入对应 InterfaceImpact.references / affected_files
```

- **无签名变化**（`interface_impacts == []`，含无 base、签名未变、单文件 PR 的既有闸门）→ **不触发定位，零额外请求**。
- **定位为空** → 该符号在 `symbols_located` 中**如实省略**，不写占位。
- 定位失败/异常 → `symbols_located` 为空字典，审查继续。

### 4.3 run metadata 新键

```json
"symbols_located": {
  "fetch_user": ["src/caller.py:2", "tests/test_service.py:10"]
}
```

---

## 5. 配置开关

`preferences.symbol_locate: bool = True`（`config.py`）：

- 常量 `DEFAULT_SYMBOL_LOCATE = True`。
- 归一化 `normalize_symbol_locate`：兼容 `bool` / `0|1` / `"true"|"false"|"on"|"off"` 等；非法值回退 `True` 并 `RuntimeWarning`（与 `normalize_workbench_mode` 同风格，不抛异常）。
- 旧配置缺字段 → 默认开启、零告警（`PreferencesConfig.__post_init__`）。

上限（`max_requests=15` / `max_results_per_symbol=5`）当前是 `RepoSymbolLocator` 构造参数默认值，对应 recon §4.2 的「启发式 3–6 文件、预算闸门」；本次不新增偏好项，如需用户可调再按 `_normalize_bounded_int` 惯例扩展。

---

## 6. 缓存 / 降级 / 上限

| 机制 | 行为 |
|---|---|
| **缓存** | `RepoCache` 协议，按路径缓存文件正文；`FileSystemRepoCache` 目录按 `owner/repo/sha` 隔离。**缓存命中不计入 `max_requests`** |
| **请求上限** | `max_requests`（默认 15）：真实 `read_file` 次数 |
| **结果上限** | `max_results_per_symbol`（默认 5）：命中即停 |
| **降级** | 读树抛错 → `[]`；读文件抛错 → 跳过该文件继续；正则抛错 → 跳过该文件；缓存 I/O 抛错 → 当未命中。**任何异常不向上抛** |
| **诚实性** | 找不到就是空，不臆测。远端默认分支可能落后本地（recon §3），结果仅代表 head SHA 上的引用 |

---

## 7. 测试

`tests/test_symbol_locator.py`（38 项，全部 stub，不读凭据、不打网络）：

| 组 | 覆盖 |
|---|---|
| TestLocateBasics | 命中（path/line/snippet）/ 未命中 / 标识符边界 / 非源码扩展名跳过 / 长行截断 / 空符号 |
| TestLimits | `max_requests` 截断 / `max_results_per_symbol` 提前停 / 上限为 0 |
| TestExcludeAndCache | `exclude_paths` / 缓存命中不增 `read_file` / 未命中回写 |
| TestDegradation | 读树抛错 / 读文件抛错（单文件与全量）/ 缓存抛错 |
| TestChangedSymbolsFromImpacts | 去重保序 / 空列表 |
| TestSignatureChangeTrigger | **有签名变化才触发**（compare_with 有/无变化、无 base）/ 编排器无变化不实例化 locator / 有变化定位并入 CrossFileReference / `symbol_locate=False` 关闭 / 空结果省略 |
| TestSymbolLocatePreference | 默认开启 / 归一化 / 非法回退告警 / 旧配置静默 |

---

## 8. 验证命令与数字

```powershell
New-Item -ItemType Directory -Force -Path .pytest_mimo
$env:TEMP = (Resolve-Path .pytest_mimo).Path
$env:TMP = $env:TEMP
python -m pytest -q --no-cov tests/test_symbol_locator.py   # 38 passed
python -m pytest -q --no-cov                                # 895 passed, 1 skipped in 87s
```

既有测试无回归（全量 895 通过 / 1 跳过，跳过项为原既有 skip）。

---

## 9. 未决项

1. **`read_tree` 的生产实现**经 `PRFetcher._get_repo` + PyGithub `get_git_tree(recursive=True)`（`PRFetcher` 不在 write_scope，未加公开 trees API）。后续可把 `list_tree_paths` 提升为 `PRFetcher` 公开方法。
2. **`truncated: true`**（大仓库 recursive tree）未处理：本仓库量级不会触发；recon §5.3 建议分目录遍历，留待真实大仓库接入时补。
3. **非 Python 启发式阈值**（`.ts/.tsx/.js/.jsx`）未标定（recon §7.4）。
4. **Hybrid 编排器**未接 L2（见 §4.1）。
5. 单文件 PR 仍走既有 `len(contexts) < 2` 闸门（`_load_base_signatures` / `analyze`），签名变化定位与跨文件影响同步跳过——保持既有行为，未放宽。
