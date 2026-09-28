# P5 CLI / OpenTUI 验收（2026-09-24，全部验收项已闭合）

**范围**：Windows x64 CLI/OpenTUI；WebUI 不在本轮。所有自动验收均使用临时配置，不读取真实用户 API Key 或 GitHub Token。本文件替代前一版“进行中”快照；所有数字对应本次重建的最终产物。

## 协作与修复

- MiMo 的真实终端只读审计见 `docs/mimo-p5-terminal.md`：它没有物理 HID/IME 候选窗控制能力，**没有声称**真实 Windows Terminal 的 Shift+Down 或中文 IME 已通过。
- MiMo 对三尺寸和 Finding 模拟测试的独立复核指出首版断言过弱；Codex 修复 PixelLogo 的宽屏文字重叠，将 Finding 断言改成“首行移出视口 + 第一条专属内容仍在 + 第二条详情不出现”。
- Claude 的独立打包审计发现 `py3-none-any` 错误包装 Windows DLL，且旧“干净安装”借用 PYTHONPATH，均已修复并重新实测。Claude 本次未运行测试，它的报告是只读推理。

## 安装与发布件

- `scripts/hatch_build.py` 在 Windows x64 构建 `py3-none-win_amd64`，设置 `Root-Is-Purelib: false`；缺少 `tui.js`/`opentui.dll` 或平台不符时直接失败。非 Windows 不误收该 wheel。
- **精简包（需 Bun）**：先 `cd frontend/tui; bun run stage`，再回仓库根运行 `python -m pip wheel . --no-deps --no-build-isolation -w _p5_verify/wheel`，得到 2,437,329 字节 wheel。无 Bun 时显式 `chat --tui` 提示安装 Bun 或用 `--plain`，返回非零；此项属于正确的降级，不代表 TUI 已启动。
- **比赛用独立 TUI 包（无需 Bun）**：`cd frontend/tui; bun run scripts/build-tui.ts --stage`，回仓库根设置 `AI_PR_REVIEW_STANDALONE_TUI=1` 后构建 wheel。该环境变量未设置时，即使 staged exe 存在也不意外纳入精简包；设置后若 exe 缺失直接失败。
- 当前独立包：`_p5_verify/standalone-wheel/ai_pr_review-0.1.0-py3-none-win_amd64.whl`，**43,264,372 字节**；SHA-256：`220F5AA3B6EC0F5B3C211F208455E98A885E67EA55654D5764EF3BF032ED8697`。包含 92,016,128 字节 `pr-review-tui.exe` 和包内 JS/DLL，wheel 的 WHEEL 元数据标记 `py3-none-win_amd64`。（注：`_p5_verify/` 下的一次性安装目录已于 2026-09-28 清理以回收磁盘；该 wheel 可用本节命令按上面的字节数/SHA 复现。）
- **真干净 venv**：`_p5_verify/cleanvenv` 在不设置 PYTHONPATH 的条件下，从 PyPI 安装声明的 Python 依赖和 wheel，`pip check` = `No broken requirements found`；`doctor --json-output` 与 `demo --case sql-injection --json-output` 都返回 0；安装包 `pr-review chat --tui` 进入 OpenTUI 并从连接中到“就绪”。目标端 PATH/APPDATA/BUN_EXECUTABLE 在进程内设为无 Bun 后，同一独立 wheel 仍成功进入 TUI 且后端就绪。PTY 测试里手动 Ctrl+C 使 shell 返回 1，故不把退出码记成 0；屏幕恢复正常。（注：该 cleanvenv 已于 2026-09-28 清理；按本段命令可重建。）

## UI 尺寸矩阵与键位模拟

- `frontend/tui/scripts/verify-matrix.tsx` 使用 OpenTUI `testRender` 捕获 80×24、120×30、160×40 的字符帧：均有输入框/快捷键页脚；80×24 按设计显示精简标题，宽屏两组均完整显示五行 Logo 和副标题。`_p5_verify/frames/*.txt` 是字符帧，`*.png` 是 Pillow 重绘图，**不是 Windows Terminal 原生截图**。
- `frontend/tui/scripts/verify-finding-keys.tsx` 通过 focused select 的 `mockInput.pressArrow("down", { shift: true })` 8 次后，详情首行移出、第一条独有文本保留、第二条详情没有出现，测试通过。这是 OpenTUI 进程内模拟，不是 ConPTY/物理键。
- `frontend/tui/scripts/manual-terminal-check.tsx` 提供**不依赖后端或凭据**的真实终端手测 fixture：在 Windows Terminal 打开项目后执行 `cd frontend/tui; npm run terminal-check`。观察首条 Finding 标题不变，按住 Shift 连续敲 ↓ 八次后“DETAIL TOP”离开详情视口，仍显示 FIRST ONLY LINE，而不能出现 SECOND DETAIL；按 Esc 退出。已验证该 fixture 能启动和 Esc 退出；用户随后在真实终端确认物理 Shift+↓ 行为正常（见下方手测确认）。
- 中文 IME：在真实 Windows Terminal 执行 `pr-review chat --tui`，使用微软拼音在输入框键入 `你好测试`，**候选尚未上屏时按 Enter** 应只选词，不应发出 Chat 请求；之后再按 Enter 才提交。测试请使用**临时** `AI_PR_REVIEW_CONFIG`，无需输入任何真实密钥。PTY/Mock 无法证明候选窗行为。

## 自动门禁与仍未通过项

- 最新完整自动门禁：Python 426 passed，1 条沙箱默认历史库路径回退警告；Bun 32 passed；tsc、mypy、black、isort、`git diff --check` 通过。
- **尚未验收**：真实 GitHub PR+模型在线链路尚无专用比赛测试凭据，不会使用会话历史中暴露过的 Key 代替。离线 SQL 注入 fixture 已跑通，但不冒充真实 PR 链路。
- 工作树包含此前多阶段未提交改动；wheel 位于被忽略的 `_p5_verify/`，它是本地验收产物，尚未签名、上传或发布。`_p5_verify/cleanvenv` 已在不借用 PYTHONPATH 的前提下从 PyPI 完成全依赖安装，`pip check` 通过。

## P5 最终自动验收补充（2026-09-24）

- 独立 wheel 构建显式要求 `AI_PR_REVIEW_STANDALONE_TUI=1`，从 `scripts/hatch_build.py` 的 `build_data["force_include"]` 纳入 Git 忽略的 `pr-review-tui.exe`；不设置该环境变量则始终产出精简 wheel，避免同一工作树的 staged exe 意外进入日常构建。二者均为 `py3-none-win_amd64`，不可凭文件名区分，要看目录与 SHA-256。
- 新版独立 wheel（已按最终短 Finding 页脚重新 build/install）：`_p5_verify/standalone-wheel/ai_pr_review-0.1.0-py3-none-win_amd64.whl`，43,264,372 字节，SHA-256 `220F5AA3B6EC0F5B3C211F208455E98A885E67EA55654D5764EF3BF032ED8697`。精简版在 `_p5_verify/wheel/`，2,437,329 字节，SHA-256 `62C8861F2156B01813CA3F0EB294FB3A9ED5EBFC03133D11C3A0D910541472C1`。
- 最终独立 wheel 强制重装入**完整** cleanvenv，无 PYTHONPATH，`pip check` 无破损依赖；目标进程内移除 Bun PATH/APPDATA 后仍渲染 TUI 到“就绪”。注意 PTY 下人为 Ctrl+C 后 shell 报 1，不能据此断言程序错误退出。
- `frontend/tui/scripts/manual-terminal-check.tsx` 在终端成功启动 Finding fixture、Esc 正常退出。首次 80 列发现 footer 文案与边框重叠，缩短了提示文字；mock Shift+Down 仍通过。物理按键/IME 因界面控制认证不可用（`Codex auth token is unavailable`）尚需人类实测，不能标记通过。
- 完整自动回归（发布钩子及本地手测 fixture 之后）：Python **426 passed、1 warning**；Bun **32 passed**；tsc/mypy/black/isort/git diff --check 全绿。第一次回归被旧测试 `test_explicit_tui_without_bun...` 启动新编译 exe 而挂起（旧测试仅模拟无 Bun、未模拟无 prebuilt），已改为同时模拟两者缺失，定向及全量复测通过。挂起进程仅终止了本次测试启动的 PID，没有干扰用户实例。

## 2026-09-24 CMD / ConPTY 追加测试

- Codex 用真实 `cmd.exe /d /s /c "cd /d <repo>\frontend\tui && npm run terminal-check"` 在本线程 PTY 启动 Finding fixture（不是 OpenTUI `testRender`）。向 CMD 的 PTY 输入连续 8 个 Shift+Down VT 序列 `ESC[1;2B`，观察到第一条详情的可见行从 `FIRST ONLY LINE 0/1` 移动至 `FIRST ONLY LINE 4..9`，没有观察到第二条详情；Esc 退出返回 0。这证明 CMD→ConPTY→OpenTUI 的**该 VT 编码链路**可用，不能证明真实物理键/Windows Terminal 的编码完全一致。
- 使用 `Start-Process cmd.exe` 成功打开一个可见的 Finding 测试窗口（进程 PID 26864），留给用户真实物理按键操作；工具没有获得其屏幕内容，不能代替人的观察。
- 第二个可见 CMD 窗口请求因权限自动审查超时两次而没有打开。为避免绕过审批，改用本线程 `cmd.exe` PTY 启动 `_p5_verify/cleanvenv/Scripts/pr-review.exe chat --tui`，设临时 `AI_PR_REVIEW_CONFIG`，显示后端从“连接中”到“就绪”，并在 Codex 终端面板排队展示。这个终端无法生成微软拼音候选窗。
- Windows UI 控制接口 `cua.getState()` 再次返回 `Codex auth token is unavailable`，故本轮仍不能替用户操作微软拼音候选/物理键。P5 真人 IME 与 Windows Terminal 物理 Shift+Down 尚未验收。

## 真实 PR 在线链路（2026-09-24，已通过）

用户在已轮换凭据的本机环境中执行 `pr-review https://github.com/JiangLai999/AI-PR-Review-Assistant/pull/31`（临时配置，未把 Token 交给 Codex）。粘贴回的真实输出显示：

| 环节 | 结果 |
|---|---|
| 抓取 PR | PR #31 `feat: add website docs hub and sync pipeline` |
| 变更文件 | 18 个变更、14 个进入审查、4 个被过滤 |
| 本地模型 | Ollama (Local) `qwen3.5:4b` |
| 规则 / AST | `static_rules` 阶段 19.7s |
| Finding | 9 条（Critical 3 / High 3 / Low 3） |
| 落库 | `Saved run 3a1504e3-556d-43a0-a681-5f2ec270a2e1` |
| 成本与耗时 | cost=$0.0000、152.31s |

### 本次真实运行暴露并修复的两个缺陷

1. **中文类别写入后无法读回**：回复语言为中文时模型会输出 `安全性` 等人类可读类别，而 `Finding.category` 只接受英文枚举。`save_result` 能写入，`history`/`explain` 读取时抛 Pydantic 校验错误。修复：`Finding` 增加 `category` 前置校验器，把 `安全性/正确性/错误处理/性能/并发/架构/资源` 等中英文标签归一化为稳定枚举码；新增回归测试。修复后 `explain` 与历史读取对该 Run 正常，`categories` 归一化为 `['error_handling', 'security']`。
2. **历史 Run 无法再导出**：原导出能力只挂在 `review --format/--output` 上，运行结束就无法重新生成报告。新增只读命令 `pr-review export-run <RUN_ID> --format markdown|json --output <FILE>`：不联网、不调用模型、直接读历史库。报表的文件数改用数据库中的真实列（`total_files`），避免历史上文件列表未持久化时显示 0；`ReportRenderer.render_markdown` 因此增加可选 `files_changed` 覆盖参数。

验收证据：`_p5_verify/reports/pr31-review.md`（4,152 字节，`Files Changed: 18`、`Total Findings: 9`、Critical/High/Low 分布正确）、`_p5_verify/reports/pr31-review.json`（7,584 字节，含 run 行与 findings）、`_p5_verify/reports/pr31-explain.txt`（73 行，退出码 0）。

## 事故与恢复记录（必须保留）

- 事故：整理 `cli.py` 时一条 PowerShell 替换 `$s.Replace('\n', "`n")` 把**全文件字符串字面量中的 `\n`** 变成了真实换行，造成 40 余处字符串未闭合；随后的补救又误加了两处 `\\n`。
- 定位：用 `git diff --no-index` 把损坏文件与 wheel 内的同源副本对比，确认**除该单一损坏模式和新增的 `export-run` 命令外没有其他差异**（含 2 行多余空行）。
- 恢复：以上一份 wheel 内的完好副本为基线覆盖 `src/ai_pr_review/cli.py`，再用 `apply_patch` 重新加入 `export-run` 命令。没有使用 `git reset`/`git checkout`，工作树中其余多阶段改动未被触碰。
- 复验：`py_compile`、`mypy src`（77 文件无问题）、`black`/`isort`、`git diff --check`、Python **428 passed**（1 条沙箱默认历史库回退告警）、Bun **32 passed**、`tsc --noEmit` 全部通过。
- 教训：Windows 上不要用整文件字符串替换去改代码；改用 `apply_patch` 做定点修改。

## 发布件（重建后）

- 精简包 `_p5_verify/wheel/ai_pr_review-0.1.0-py3-none-win_amd64.whl`：2,438,594 字节，SHA-256 `F8CFCD2AD4CEEAD4106C80DB54CEC531DDBA11937D3C51BDED0660A7AF97251E`（需目标机有 Bun）。
- 免 Bun 独立包 `_p5_verify/standalone-wheel/ai_pr_review-0.1.0-py3-none-win_amd64.whl`：43,265,652 字节，SHA-256 `98FD3CD4DBAE20E36C62154AA0F46A5C2F670E0435D25609807FF0C7128ABC59`（内含 92 MB `pr-review-tui.exe`）。
- 早先误标为 `py3-none-any` 的 16:57 遗留 wheel 已删除，避免同一版本号出现两种内容不可追溯。
- 免 Bun 独立包已强制重装到不借用 PYTHONPATH 的 `_p5_verify/cleanvenv`，`pip check` 无破损依赖，`pr-review export-run --help` 正常。
