你是本项目的协作 agent（mimo）。这是**重试任务**（上一轮你在"重读 web_server.py 推导契约"时卡死、零落盘）。
这次**不要再推导契约**：下面把 18 个端点和两条新端点的契约都写死了，你只管写文件 + 跑两条验证命令 + 报告。

## 硬性纪律（避免再次卡死）
1. **不要**再通读 `src/ai_pr_review/web_server.py`（主控已实现，契约以本提示为准）；最多 grep 一次确认路径存在。
2. 按顺序写这 5 个文件，每个文件写完立刻保存；不要做"先通读全仓"的动作。
3. 除验证命令外不要跑其它命令；不要 npm run build。

## Web 工作台 HTTP 接口（18 条，写文档就用这份）
GET：
1. `/api/health` — 存活探针 → `{ok, service}`
2. `/api/meta` — 运行环境（规则数/供应商数/tree-sitter/跨文件开关/静态分析开关/模型）
3. `/api/history?limit=` — 历史 run 列表 + 统计
4. `/api/report?run_id=` — 单次 run 的完整报告（review/plan/validation/interface_impacts/feedback）
5. `/api/report/export?run_id=&format=markdown|json` — **新**：markdown 走 `text/markdown` + `Content-Disposition: attachment; filename="pr<N>-<run8>.md"`；json 与 `/api/report` 同形
6. `/api/benchmark?strategy=` — 准确率（precision/recall/F1/行号准确率 + 逐 case）
7. `/api/credentials?probe=0|1` — 凭证健康（只回掩码，绝不明文）
8. `/api/config` — 配置视图（provider/base_url/model/api_format/api_key 掩码/available_providers）
9. `/api/jobs` — 最近任务（10 条）
10. `/api/jobs/{id}` — 任务快照（status/total_files/completed_files/current_file/progress/error/elapsed_seconds/run_id）
11. `/api/jobs/{id}/events` — **SSE**（`text/event-stream`），逐文件进度事件
12. `/api/demo/cases` — 离线演示用例清单
13. `/api/demo/run?case=` — 离线演示结果（无需 Token/Key）
14. `/static/*`（含 SPA fallback） — 前端构建产物（`base=/static/`）
POST（**全部要求 `Content-Type: application/json` 且同源**，否则 415；`OPTIONS` → 405、不返回任何 `Access-Control-*`）：
15. `/api/plan {pr_url}` — 只做抓取/过滤/规划，不调用模型
16. `/api/review {pr_url, async_job?}` — 同步审查；`async_job:true` → 202 + job_id（进度走 11）
17. `/api/jobs/{id}/cancel` — 服务端真取消（文件边界生效）
18. `/api/feedback {run_id, finding_id, status, note?}` — 人工反馈落库
19. `/api/config {…}` — 保存配置（掩码/留空=不改；未知键 → `ok=false` 拒绝）
20. `/api/publish {run_id, confirm}` — **新**：`confirm=false` 只预览（`status=preview`、`comment_chars`、不碰 GitHub）；
    `confirm=true` 才发布 → `status=published|already_published` + `comment_url`/`comment_id`；
    错误码：400（run_id 缺失）/404（run 不存在）/409（无 GitHub PR 链接）/415（跨站或非 JSON）/502（GitHub 侧失败）/503（未配置 Token）
（上面编号到 20 是因为把 `/static/*` 也算一条；**端点计数以 18 条 API 为准**，文档里如实写"18 条 API + 静态资源"。）

## 要写的 5 个文件（只写这几个）
1. `web/src/pages/ApiPage.tsx`：把端点表补到上述 18 条（方法/路径/入参/返回要点/错误码/一条 curl 示例），
   分组：审查（plan/review/jobs/jobs{id}/events/cancel）· 报告与历史（report/report.export/history/benchmark）·
   配置与凭证（config GET+POST/credentials/meta）· 演示（demo.cases/demo.run）· 发布（publish）。
   沿用现有 design tokens 与组件，不引新依赖。
2. `docs/API.md`：同步这 18 条 + `pr-review serve` 启动方式 + `/static/` 入口 + SSE 语义 + 写端点同源守卫；
   修正"五个视图"→ 6 个视图（overview/review/history/benchmark/api/settings）。
3. `README.md`：修正 `:408`/`:416` 两处不实表述（"五个视图"/"全部 HTTP 接口"），指向 `docs/API.md`。
4. `tests/test_web_api_docs.py`（新）：**防漂移**测试——正则解析 `web_server.py` 的 `do_GET`/`do_POST` 里的 `/api/...` 字面量，
   与 `docs/API.md` 中出现的路径集合比较，缺一个就失败（注释里允许出现 `/api/` 前缀示例，用显式排除集合处理）。
5. `docs/mimo-web-api-docs.md`：改动点、18 条对照表（服务端 ↔ 文档位置）、防漂移测试原理、验证数字、未决项。

## 验证（必须真跑，报数字）
```bash
TEMP=.pytest_mimo TMP=.pytest_mimo python -m pytest tests/test_web_api_docs.py -q --no-cov
cd web && npm run typecheck
```

## 约束
- 只写这 5 个文件；禁止改 `src/ai_pr_review/**`、`web/src` 的其它文件、`tests/test_web_server.py`；禁止 git 操作；
- **禁止 `npm run build`**；禁止读取/输出凭据。

完成后按总线报告：
`python scripts/agent_bridge.py report web-p0-docs --agent mimo --status completed --summary "<一句话>" --evidence "<文件:行号 + 两条命令的数字>" --blocker "<未决项，没有写无>"`
