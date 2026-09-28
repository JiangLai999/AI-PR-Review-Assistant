你是本项目的协作 agent（mimo）。这是**实现任务**（写代码/文档）：把 Web 工作台的**接口面文档与运行时对齐**，
顺手修掉"文档在撒谎"的三处（你在提案 §1.3 里指出的同类问题）。另外加一条**防漂移**测试。

## 背景
- 服务端实际有 **16 条路径 / 17 个方法**（`src/ai_pr_review/web_server.py` 的 `do_GET`/`do_POST`）；
- `web/src/pages/ApiPage.tsx` 目前只列 7 条；
- `README.md:416` 声称"全部 HTTP 接口"、`:408` 与 `docs/API.md:108` 写"五个视图"（实际 6 个）；
- 主控正在并行新增两条端点（契约已冻结，见下），你要一并写进文档。

## 冻结的两条新端点（主控并行实现）
1. `POST /api/publish`：body `{run_id, confirm}`；返回 `{status: preview|published|already_published,
   comment_body, comment_chars, requires_confirmation, comment_url, comment_id, message}`；
   错误 400/404/409/415/502/503。
2. `GET /api/report/export?run_id=&format=markdown|json`：markdown 走 `text/markdown` + `Content-Disposition: attachment`；
   json 返回 `application/json`（run/review/plan/validation/interface_impacts/feedback）。
   另外：所有写端点要求 `Content-Type: application/json` 且同源（`Sec-Fetch-Site: same-origin` 或
   `Origin` 白名单），否则 **415**——这条也要写进文档的"安全"小节。

## 要做的事（write_scope 内）
1. `web/src/pages/ApiPage.tsx`：把端点表补全到 **18 条**（16 现有 + 2 新增），每条含：方法 / 路径 / 入参 /
   返回要点 / 典型错误码 / 一条 curl 示例；分组（审查 / 任务与流 / 报告与历史 / 配置与凭证 / 演示 / 发布）。
   保持现有页面风格与 design tokens；不要引入新依赖。
2. `docs/API.md`：同步补全（含 `--serve` 的启动方式与 `/static/` 入口、SSE `/api/jobs/{id}/events` 的
   `text/event-stream` 语义、写端点的同源守卫）；修正"五个视图"为实际 6 个（overview/review/history/benchmark/api/settings）。
3. `README.md`：修正 `:408`/`:416` 两处不实表述，指向 `docs/API.md` 的完整清单。
4. 新建 `tests/test_web_api_docs.py`（**不要改 tests/test_web_server.py**，那是主控的文件）：
   一条**防漂移**测试——用正则从 `src/ai_pr_review/web_server.py` 解析出 `do_GET`/`do_POST` 里出现的
   `/api/...` 路径字符串，与 `docs/API.md` 中列出的路径集合比较，缺失即失败（允许文档包含 `/api/` 前缀的说明性条目，
   用注释排除；实现要稳，不依赖行号）。测试要能独立通过：
   `TEMP=.pytest_mimo TMP=.pytest_mimo python -m pytest tests/test_web_api_docs.py -q --no-cov`。
5. `docs/DEV_RECORD.md`：改动点、清单对照表（服务端路径 ↔ 文档位置）、防漂移测试原理、验证数字、未决项。

## 约束
- 只写 write_scope：`web/src/pages/ApiPage.tsx`、`docs/API.md`、`README.md`、`tests/test_web_api_docs.py`、`docs/DEV_RECORD.md`；
- 禁止改 `src/ai_pr_review/**`（后端与守卫是主控的）、禁止改 `web/src` 里的其它文件（另一 agent 在改 ReviewPage/HistoryPage/client.ts）、禁止 git 操作；
- **禁止运行 `npm run build`**（`web_static/` 由主控统一重建）；允许 `cd web && npm run typecheck`；
- 禁止读取/输出任何凭据。

## 验证（必须真跑并报数字）
```bash
TEMP=.pytest_mimo TMP=.pytest_mimo python -m pytest tests/test_web_api_docs.py -q --no-cov   # 期望全绿
cd web && npm run typecheck                                                                  # 期望 exit 0
```

完成后按总线报告：
`python scripts/agent_bridge.py report web-p0-docs --agent mimo --status completed --summary "<一句话>" --evidence "<文件:行号 + 测试数字 + typecheck 结果>" --blocker "<未决项，没有写无>"`
