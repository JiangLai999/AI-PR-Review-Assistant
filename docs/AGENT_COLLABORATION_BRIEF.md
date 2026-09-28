# CLI / OpenTUI 协作任务单（2026-09-23）

主线目标：完成 AI-PR-Review-Assistant CLI 的数据隔离、安装版一致性与真实终端验收。WebUI 不在本轮范围内。

## 事实基线
- 工作区：`C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant`
- 源码版 OpenTUI + Python JSONL 后端可启动；Composer、命令菜单、本地 Ollama 增量输出和后端重启会话重建已有实现。
- 上次验证：Python 384 passed，Bun 6 passed；此数字是当时快照，继续工作前须重跑。
- 已知缺陷：显式临时配置的 `/history` 可能读取全局 SQLite 历史；pipx 安装版与源码版 TUI 尚未统一。
- 不要读取、复制、提交或传输历史会话中的 Token/API Key；任何演示使用脱敏或测试数据。

## Codex（主实现与集成）
- 独占写入：`src/ai_pr_review/config.py`、`src/ai_pr_review/backend/jsonl_server.py`、相关 Python 测试、打包配置。
- 首先修 `/history` 存储隔离：显式配置路径默认绑定独立结果库；显式指定 `result_store.db_path` 时尊重用户配置。
- 再验证 wheel/pipx 安装版的 TUI 分发；任何更改都须通过全量测试、类型检查和干净安装测试。

## 当前协作执行器：Claude Code（DeepSeek-V4.1-Flash）
- Claude Code 进程：`C:\Users\21986\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe`
- 负责独立复核：Python JSONL 后端、TUI 状态/事件协议、历史隔离和异常恢复；优先只读审计，除非主理人明确分配独占写入范围。
- 不读取、复制或传输密钥与完整私人会话；输出必须给出文件路径、复现命令和验证结果。
- 目标模型：DeepSeek-V4.1-Flash（以 Claude 当前会话实际配置为准，不能只凭进程名推断）。
- 建议成果文件：`docs/claude-tui-audit.md`。

## 当前协作执行器：MiMo Code（MiMo-V2.6-Pro）
- MiMo Code 进程：`C:\Users\21986\.mimocode\bin\mimo.exe`
- 负责 UI / OpenTUI / MiMo 风格交互复核：Composer、命令菜单、焦点切换、窄终端布局、启动链路和比赛展示路径。
- 优先只读审计，不与 Codex 同时修改同一文件；需要修改时使用独占文件范围并留下验证记录。
- 目标模型：MiMo-V2.6-Pro（以 MiMo 当前会话实际配置为准）。
- 建议成果文件：`docs/mimo-tui-audit.md`。

## 已取消的协作对象
- DeepSeek Harness：本轮不再作为协作执行器。
- OpenCode：本轮不再作为协作执行器。
- WorkBuddy：本轮不作为主动执行器；此前分享记录仅作为历史参考。

## 合并规则
1. 每个参与方先报告证据和文件路径，不以口头“全部完成”为验收依据。
2. Codex 逐条复现问题并决定是否修改；修改后重跑 Python 全量、Bun typecheck/test、mypy、格式与 diff 检查。
3. 任何可能覆盖别人的未提交工作、涉及凭据或上传到第三方的操作，先取得用户明确许可。
