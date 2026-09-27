# mimo · web-p0-docs-retry 变更说明

任务：Phase 0.3 重试 —— 接口文档对齐 18 端点 + 防漂移测试。
执行 agent：mimo。契约以调度器 prompt 为准，未再通读 `web_server.py` 推导。

## 1. 改动点

| 文件 | 动作 | 内容 |
|------|------|------|
| `web/src/pages/ApiPage.tsx` | 重写端点表 | 18 条 API + `/static/*`，按「审查 / 报告与历史 / 配置与凭证 / 演示 / 发布」五组展示；每条含方法、路径、入参、请求体、响应要点、错误码、curl 示例。沿用既有 `Card`/`CardHead`/`Chip`/`Section` 与 design tokens，无新依赖。 |
| `docs/API.md` | 扩写 | 新增「Web 工作台 HTTP 接口」全量章节：`pr-review serve` 启动、6 视图、全局约定（64 KB / 同源守卫 / 掩码）、18 端点总表 + 逐条明细、SSE 语义、`/static/*` 与 SPA fallback。 |
| `README.md` | 修正 | `:408`「五个视图」→「6 个视图」并补「设置」行；`:416`「全部 HTTP 接口」→ 指向 `docs/API.md`，并注明 18 条 API + 静态资源。 |
| `tests/test_web_api_docs.py` | 新增 | 防漂移测试（6 个用例）。 |
| `docs/mimo-web-api-docs.md` | 新增 | 本文件。 |

未触碰：`src/ai_pr_review/**`、`web/src` 其它文件、`tests/test_web_server.py`。未做 git 操作，未执行 `npm run build`，未读取/输出任何凭据。

## 2. 18 条端点对照表（服务端 ↔ 文档位置）

文档位置以 `docs/API.md` 的「端点明细」小节标题为准；`ApiPage.tsx` 为同内容的界面镜像。

| # | 方法 | 路径 | 服务端（`web_server.py`） | `docs/API.md` | `ApiPage.tsx` 分组 |
|---|------|------|--------------------------|---------------|--------------------|
| 1 | GET | `/api/health` | `do_GET` → `_send_json` | `GET /api/health` | 配置与凭证 |
| 2 | GET | `/api/meta` | `do_GET` → `_handle_meta` | `GET /api/meta` | 配置与凭证 |
| 3 | GET | `/api/history` | `do_GET` → `_handle_history` | `GET /api/history` | 报告与历史 |
| 4 | GET | `/api/report` | `do_GET` → `_handle_report` | `GET /api/report` | 报告与历史 |
| 5 | GET | `/api/report/export` | `do_GET` → `_handle_report_export` | `GET /api/report/export` | 报告与历史 |
| 6 | GET | `/api/benchmark` | `do_GET` → `_handle_benchmark` | `GET /api/benchmark` | 报告与历史 |
| 7 | GET | `/api/credentials` | `do_GET` → `_handle_credentials` | `GET /api/credentials` | 配置与凭证 |
| 8 | GET, POST | `/api/config` | `do_GET` 直接回视图 / `do_POST` → `_handle_config_save` | `GET /api/config` / `POST /api/config` | 配置与凭证 |
| 9 | GET | `/api/jobs` | `do_GET` → `job_manager.list_recent(10)` | `GET /api/jobs` | 审查 |
| 10 | GET | `/api/jobs/{id}` | `do_GET` startswith → `_handle_job_get` | `GET /api/jobs/{id}` | 审查 |
| 11 | GET | `/api/jobs/{id}/events` | `_handle_job_get` → SSE | `GET /api/jobs/{id}/events` | 审查 |
| 12 | GET | `/api/demo/cases` | `do_GET` → `demo_cases_payload()` | `GET /api/demo/cases` | 演示 |
| 13 | GET | `/api/demo/run` | `do_GET` → `run_demo_case` | `GET /api/demo/run` | 演示 |
| 14 | POST | `/api/plan` | `do_POST` → `orchestrator.plan_only` | `POST /api/plan` | 审查 |
| 15 | POST | `/api/review` | `do_POST` → `orchestrator.review` / `job_manager.start` | `POST /api/review` | 审查 |
| 16 | POST | `/api/jobs/{id}/cancel` | `do_POST` endswith `/cancel` → `job_manager.cancel` | `POST /api/jobs/{id}/cancel` | 审查 |
| 17 | POST | `/api/feedback` | `do_POST` → `_handle_feedback` | `POST /api/feedback` | 审查 |
| 18 | POST | `/api/publish` | `do_POST` → `_handle_publish` | `POST /api/publish` | 发布 |
| — | GET | `/static/*`（SPA fallback） | `do_GET` → `_serve_frontend` | 「静态资源 `/static/*`」 | 「静态资源」 |

计数口径：`/api/config` 的 GET+POST 合计为 1 条路径，因此是 **18 条 API + 静态资源**（不是 19，也不是编号到 20 的展示列表）。

## 3. 防漂移测试原理

`tests/test_web_api_docs.py` 做三件事：

1. **抽取服务端路由**：用正则定位 `web_server.py` 的 `do_GET` / `do_POST` 方法体，再抓取其中的 `"/api/..."` **字符串字面量**。只看方法体，天然排除模块级注释与 helper docstring 里的示例路径；若将来注释中出现带引号的 `/api/` 示例，加入 `EXCLUDED` 显式排除即可。
2. **抽取文档路径**：从 `docs/API.md` 抓取 `/api/...` 路径（自动去掉 `?query`）。
3. **双向断言**：
   - 服务端每条具体字面量必须出现在文档中（缺一个就失败）；
   - 前缀路由（`/api/jobs/`）必须在文档中有对应的具体子路径（如 `/api/jobs/{id}`）；
   - 文档里写死的不含 `{param}` 的具体路径必须能在服务端字面量或前缀子树中找到（防止文档凭空发明端点）；
   - 端点总表必须恰好 18 条编号行，且描述了 `/static/*`。

`EXCLUDED = {"/api/"}`：服务端 `do_GET` 的 404 兜底 `path.startswith("/api/")` 会抽出 `/api/`，它不是端点，不要求文档收录。

## 4. 验证数字

命令与结果（`TEMP`/`TMP` 指向 `<repo>/.pytest_mimo`）：

```text
$ python -m pytest tests/test_web_api_docs.py -q --no-cov
......                                                                   [100%]
6 passed in 0.03s
```

```text
$ cd web && npm run typecheck
> ai-pr-review-web@0.1.0 typecheck
> tsc --noEmit
（无输出，退出码 0）
```

- 防漂移测试：**6 passed / 0 failed**，耗时 0.03s。
- TypeScript：`tsc --noEmit` **0 错误**。
- 未执行 `npm run build`（任务明确禁止）。

## 5. 未决项

- `docs/API.md` 中部分响应字段（如 `/api/meta` 的 `rules`/`providers` 计数字段名、`/api/benchmark` 的 `line_accuracy` 字段名）按 prompt 契约书写，未对照 `web_server.py` 的 `to_dict()` 做二次核实；若实现侧字段名不同，需在下一轮以服务端序列化结果为准修订文档。
- `/api/jobs/{id}/events` 的 SSE 事件字段集（`completed_files`/`total_files`/`current_file`/`progress` 等）按任务快照同形描述，未逐一核对事件序列化代码。
- 防漂移测试当前只比对 `/api/...` **路径字面量**，不比对请求/响应 schema；schema 漂移仍靠人工或后续契约测试覆盖。
- 上一轮任务报告命令在 prompt 末尾写的是 `web-p0-docs`，本次任务 id 为 `web-p0-docs-retry`，上报按 `web-p0-docs-retry` 执行。
