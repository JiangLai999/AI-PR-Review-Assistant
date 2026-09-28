# MiMo TUI 审计报告

> 审计方式：只读（工作区内取证）。未修改、创建或删除任何文件，未读取或输出密钥。模型：mimo-v2.6-pro。

## 结论摘要

| # | 主题 | 结论 |
|---|---|---|
| 1 | Composer 提交锁 | 在 `await` 窗口内 `submitLock` 可防聊天双发；但 `/retry`、`Ctrl+R` 路径不走锁，且 `startReview` 的 `reviewing()` 门闩在首个 `review.started` 事件前是空的，可并发发起两次审查。 |
| 2 | `/` 命令菜单 | 单匹配快速 Enter 已用 `liveDraft` 重读缓解；多匹配时 Enter 执行的是 `menuIndex` 选中项而非“唯一确定项”。带 `argument` 的命令名精确匹配时，第一次 Enter 只补全不执行，与文案“Enter 执行”不一致。 |
| 3 | 焦点恢复 | 机制存在（`focused` prop → `focus()`/`blur()`，且全局单焦点），弹窗关闭后 Composer 可拿回焦点；但弹窗打开期间 `Composer.useKeyboard` 整段早退，取消/退出快捷键失效。 |
| 4 | 布局 | 80x24 在「命令菜单展开」或「多行输入 + 首页 Logo」时固定高度合计可超过 24 行；120x30 宽高均安全。 |
| 5 | 启动链路 | 源码版可起 OpenTUI；pipx/wheel 版不能。wheel 只打包 `src/ai_pr_review`，不含 `frontend/tui`；`_open_tui_frontend` 用 `parents[2]/frontend/tui` 探测，安装布局下必失败并静默回退 plain chat。 |

## 发现（按 P0/P1/P2）

### P0

#### 1. pipx / wheel 安装版无法启动 OpenTUI，与源码版不是同一套 TUI 入口

- 问题：OpenTUI 前端源码与 `node_modules` 不在 wheel 内；启动探测路径按源码仓库布局写死。安装版 `pr-review chat` 只能回退 legacy plain Chat，不会进入 OpenTUI。
- 证据：
  - `pyproject.toml:61-64` `[tool.hatch.build.targets.wheel] packages = ["src/ai_pr_review"]`，注释只承诺打包 `web_static`，未包含 `frontend/tui`。
  - `src/ai_pr_review/cli.py:3305-3309` `_open_tui_frontend`：`project_root = Path(__file__).resolve().parents[2]`；`tui_root = project_root / "frontend" / "tui"`；`entry = tui_root / "src" / "main.tsx"`；`if not entry.exists(): return False`。
  - `src/ai_pr_review/cli.py:3328` 仍要求本机 `bun`/`bun.exe` 与 `frontend/tui/node_modules`（`--preload @opentui/solid/preload`）。
  - 对比：`cli.py:2566-2567` Web 资源用 `Path(__file__).parent / "web_static"`（包内路径），安装版可用；TUI 未做同等打包。
- 复现步骤：
  1. `pipx install "git+https://github.com/JiangLai999/AI-PR-Review-Assistant.git"`（或 `python -m build` 后 `pip install dist/*.whl`）。
  2. 交互终端执行 `pr-review chat`（或 `pr-review chat --tui`）。
  3. 观察：无 OpenTUI 全屏界面；默认路径打印 “OpenTUI 不可用，将回退到纯 Python Chat。”；`--tui` 则报 “OpenTUI 未能启动”。
- 影响：安装版与源码版用户路径分叉；比赛/演示若用 pipx 安装会得到另一套 Chat；phase9 验收矩阵中的“OpenTUI 首页”在安装版不可达。
- 最小修复建议：把可运行 TUI（编译产物或完整 `frontend/tui` + 锁定依赖）纳入 wheel，启动时用包内资源路径而非 `parents[2]`；或明确产品边界，失败时给出可操作错误而不是静默降级。

### P1

#### 2. `Ctrl+C` 无法“仅取消”，busy 时会直接销毁 TUI

- 证据：`frontend/tui/src/main.tsx:4` `render(() => ...)` 未传 config，未关 `exitOnCtrlC`；`@opentui/core` 中 `exitOnCtrlC` 默认 `true`，全局 keypress 钩子对 `ctrl+c` 调度 `destroy()` 且不阻止后续监听；`app.tsx:344-347` busy 时 `props.onCancel()` 与销毁并存；验收文档与 placeholder 却写“审查中按 Esc / Ctrl+C 取消”。
- 影响：长审查误触 `Ctrl+C` 即丢会话视图；与 Esc 取消行为不一致。
- 最小修复建议：`main.tsx` 传 `exitOnCtrlC: false`，仅在空闲分支 `renderer.destroy()`；busy 时只 `onCancel()` 并 `stopPropagation()`。

#### 3. `Ctrl+R` / 并发 `startReview` 可重复发起审查

- 证据：`app.tsx:231-234` `/retry` 同步路径立即释放 `submitLock`；`app.tsx:336-338` `Ctrl+R` 不经 submit；`app.tsx:776-777` `startReview` 仅以 `reviewing()` 为门闩，而 `setReviewing(true)` 在 `app.tsx:896-897` 的 `review.started` 才发生。
- 影响：重复审查、重复计费、进度 UI 交叉污染、历史多出垃圾 Run。
- 最小修复建议：增加 `reviewStartLock`，`startReview` 入口同步置位直到 completed/failed/cancelled；`Ctrl+R` 与 `/retry` 共用该锁。

#### 4. 80x24 下命令菜单展开（或首页 Logo + 多行输入）高度溢出

- 证据（静态高度合计，`app.tsx`）：页眉 Logo ≈ 7 行（`:71-81`）；滚动区 `flexGrow={1}`（`:990`）；Composer 命令菜单 ≈ 8 行（`:352-361`）、textarea 5–10 行（`:363-385`）、模式与快捷键 ≈ 4 行；页脚 ≈ 3 行（`:1129-1132`）。极值 ≈ 33 行（首页）/ 28 行（会话），均超过 24。弹窗 `FindingsDialog` `height={22}`（`:527`）、`HistoryDialog`（`:603`）在 24 行下贴满。
- 影响：小窗演示不可用，与迁移文档“80/120/160 列可布局”的验收缺口一致。
- 最小修复建议：命令菜单改为绝对定位覆盖层；根列布局设 `minHeight`/overflow 策略优先压缩 scrollbox；`rows < 28` 时 Logo 退化为单行标题。

#### 5. 提交后端请求无超时，Composer 可能永久卡死在 `submitLock`

- 证据：`frontend/tui/src/backend.ts:48-67` `request()` 无 timeout/Abort；`app.tsx:196-284` `submit` 在 `await` 期间持锁，仅 `finally` 解锁；`backend.ts:134-141` 仅在 stdout 关闭时 `rejectPending`。
- 影响：单次后端异常即可锁死输入，只能杀终端。
- 最小修复建议：`request` 增加超时（`Promise.race`），超时 reject 走 catch；取消请求单独短超时。

### P2

#### 6. 带参数命令名精确匹配时，第一次 Enter 只补全

- 证据：`app.tsx:205-210`（`selected.argument && liveDraft.trim() === selected.name`）；`command-menu.ts:32-34`；菜单文案 `app.tsx:360`。
- 影响：用户以为已执行；再次 Enter 可能在未填参数时直接执行（如裸 `/review`）。
- 最小修复建议：仅当 draft 无尾随空格且存在 `argument` 时补全；已有参数或再次 Enter 直接执行；文案改为“Tab 补全 · Enter 执行/补全”。

#### 7. 多匹配前缀 + Enter 执行的是列表选中项

- 证据：`command-menu.ts:23-29`；`app.tsx:202-212` 取 `options[Math.min(menuIndex(), ...)]` 作 override；`/s` + Enter 执行 `/status`。
- 最小修复建议：仅 `options.length === 1` 时 Enter 代执行；多匹配要求 Tab 或精确输入。

#### 8. busy 时 Esc 同时“关菜单”和“取消任务”

- 证据：`app.tsx:340-342`（busy → `onCancel`）；`app.tsx:303-306`（菜单 dismiss）；全局监听先于 focused renderable。
- 最小修复建议：菜单可见时 Esc 只 dismiss 并 `stopPropagation`；取消仅在菜单关闭时生效。

#### 9. `AI_PR_REVIEW_INITIAL_MESSAGE` 注入后从未被 TUI 消费

- 证据：`cli.py:3338-3339` 写入 env；`frontend/tui/src` 无该键。
- 最小修复建议：Composer 挂载时读取填入 draft，或删除死参数。

#### 10. 验收矩阵快捷键与实现不一致（Ctrl+M / Ctrl+H）

- 证据：实现为 `Ctrl+K` / `Ctrl+L`（`app.tsx:328-334,396-398`）；`docs/phase9-acceptance-matrix.md:22,29` 写 `Ctrl+M`/`Ctrl+H`。
- 最小修复建议：改文档与 UI 提示保持一致。

#### 11. 进度条 + 长 PR URL、页脚状态行在 80 列下溢出

- 证据：`app.tsx:1010`（进度条与 URL 同一 `text`）；`app.tsx:1129-1131`（页脚串接 profile/status/model/ONLINE）；内容宽 `width={76}`。
- 最小修复建议：URL 独立一行并中间截断；底栏模型名限宽省略。

#### 12. Finding 详情区提示“详情滚动”，但键盘无法聚焦滚动区

- 证据：`app.tsx:529-566`；`useKeyboard` 仅处理 escape/left/right/pageup/pagedown（`:515-524`）。
- 最小修复建议：`Shift+↑↓` 或 `Tab` 切到详情滚动；或文案改为“鼠标滚动”。

#### 13. 页脚硬编码工作区路径 `~\Desktop\ican`

- 证据：`app.tsx:1130`；`backend.ts:22` 实际 cwd 来自 `AI_PR_REVIEW_ROOT ?? process.cwd()`。
- 最小修复建议：显示真实 `AI_PR_REVIEW_ROOT` 或省略。

## 已验证正常项

1. 聊天提交锁：`submitLock` 同步置位、`finally` 释放（`app.tsx:197,217,283`），聊天不会双发。
2. 粘贴后立即 Enter：`submit` 以 `textarea?.plainText ?? value()` 作 `liveDraft`（`:200`）并用于命令解析（`:201-213`）。
3. Composer Enter 单通道：`onEditorKeyDown` 不处理 Enter（`:308-309`），仅 `onSubmit` + `keyBindings` 的 submit action。
4. Enter / Shift+Enter 绑定合并正确：`@opentui/core` `mergeKeyBindings` 按修饰位覆盖默认 `return→newline`。
5. 命令匹配边界：非 `/` 开头、含 `\n` 返回空（`command-menu.ts:24`）；带参草稿不落入补全（测试 `command-menu.test.ts:5-11`）。
6. Tab 补全 / ↑↓ 选中 / Esc 关闭菜单（`app.tsx:292-306`）在 focused textarea 的 keydown 先执行，不插入 Tab 字符。
7. 会话恢复策略：`sendWithSessionRecovery` 仅 `not_found` 重建并重试一次（`session-recovery.ts:3-10` + 对应测试）。
8. 后端代次绑定：`BackendClient.generation` 与 `ensureSession`（`app.tsx:833-881`）防止重启后复用旧 session；stderr 环形缓冲并入关闭错误（`backend.ts:87-107,134-141`）。
9. 陈旧 assistant 事件过滤：`isCurrentAssistantEvent` 要求 session_id + request_id 同时匹配（`protocol.ts:17-28`）。
10. 弹窗焦点恢复机制：`focused` prop → `focus()`/`blur()`，单焦点保证；关闭后 Composer 重新聚焦（`app.tsx:1083`）。
11. 弹窗 Enter 不双执行业务回调。
12. 会话滚动区与输入区分工：transcript 在 `scrollbox` 内，Composer/页脚在外（`:990-1053` vs `:1054-1132`）。
13. 120×30 宽度安全：内容宽 76、History 72、Findings 70、品牌 60 均 < 120。
14. wheel 含 Web 资源：安装版 Web 工作台与源码一致（对比 TUI 缺口）。

## 不确定项

1. 中文输入法提交时序：TUI 无 `compositionstart/end`；组字中 Enter 是否被终端拦截依 IME/终端版本而定，本次只读审计无法实机确认。
2. Shift+Enter 的修饰位：依赖终端上报 `shift: true`；未在本机 PTY 实测各终端。
3. 80×24 溢出时 Yoga 的最终表现（裁切/压缩/重叠）未跑渲染验证。
4. 弹窗关闭与 `focused` prop 更新的帧序未插桩验证，存在偶发未回焦的理论窗口。
5. `/export`、`/report` 等命令与后端实现的一一对应未逐项核对。
6. `docs/claude-tui-audit.md` 中后端结论属后端域，此处未复验。
