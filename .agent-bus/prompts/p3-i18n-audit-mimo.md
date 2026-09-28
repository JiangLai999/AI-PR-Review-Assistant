你是本项目的协作 agent（mimo）。**Phase 3 的 i18n 前期审计任务**（范围刻意做小，先写文件后跑命令，
不要通读全仓；上两轮你两次卡在"先读一大堆"上，这次请严格按顺序执行）。

## 目标
在真正做 i18n 全站化之前，先把**工作量摸清**：`web/src` 里有多少必须翻译的中文字面量、
分布在哪些文件、哪些是"不该翻"的（例如 `/api/**` 路径、CSS 类名、`value` 常量）。
产出可复跑的审计工具 + 一份数字报告，供主控排期。

## 要做的事（只写 2 个文件）
1. `web/tools/i18n-coverage.mjs`（Node 脚本，**不依赖仓库里的其它模块**，只用 `node:fs`/`node:path`）：
   - 递归扫 `web/src/**/*.{ts,tsx}`；
   - 统计每个文件里"含中日韩汉字（`\u4e00-\u9fff`）的字符串字面量"数量，以及出现次数的**前 10 个文件**；
   - 明确排除噪音：`//` 与 `/* */` 注释、`import`/`export` 行、以 `/api` 或 `#` 开头的字符串、
     纯类名/标识符（例如 `st-valid`、`btn-primary`）、以及 `docs/` 与测试脚本目录；
   - 输出：
     a) 人类可读汇总（总文件数、含汉字的文件数、字面量总数、Top 10 文件 + 计数）；
     b) 一条 `I18N_AUDIT {json}` 行（便于机器消费）：`{files, filesWithCjk, literals, top: [{file,count}], generatedAt}`；
   - 退出码：始终 0（这是审计工具，不是门禁）；不修改任何源码。
2. `docs/DEV_RECORD.md`：把你实跑出来的数字写进去（总量、Top 10、你判断"可以先翻哪 3 个文件"）、
   噪音排除规则说明、以及"全站 i18n 建议的落地顺序（词典 → hook → 按页面分批）"。

## 纪律（避免再卡死）
- 不要读 `src/ai_pr_review/**`；不要逐个读 `web/src` 文件（脚本自己扫）；最多读 1 个文件确认编码与取词方式。
- 顺序：写 `i18n-coverage.mjs` → 跑它 → 把输出粘进文档 → 报告。目标 12 分钟内完成。
- 若脚本跑不通，最多修 2 次；仍不行就如实写未确认并照常交付文件。

## 约束
- 只写：`web/tools/i18n-coverage.mjs`、`docs/DEV_RECORD.md`；禁止改任何源码/其它文件；禁止 git；
- 禁止 `npm run build`；禁止读取/输出凭据。

完成后按总线报告：
`python scripts/agent_bridge.py report p3-i18n-audit --agent mimo --status completed --summary "<一句话>" --evidence "<脚本路径 + 实跑数字（文件数/字面量数/Top3）>" --blocker "<未决项，没有写无>"`
