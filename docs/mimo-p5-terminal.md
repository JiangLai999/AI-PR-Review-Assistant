# MiMo · mimo-p5-terminal 只读验收报告

- 任务：`mimo-p5-terminal`（P5 Windows Terminal/ConPTY 物理键位与 IME 可验证性验收）
- 状态：**needs-review**
- 日期：2026-09-24
- 根目录：`C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant`
- 写入范围：仅本文件
- 访问边界：未读取 web-ui、用户真实配置/密钥/会话、`node_modules`、`tui_static`；未扫描根目录之外路径

## 1. 执行命令（精确）

```text
pwd
.venv313\Scripts\python.exe scripts\agent_bridge.py claim --agent mimo mimo-p5-terminal
.venv313\Scripts\python.exe scripts\agent_bridge.py report --help
```

`pwd` 输出：

```text
C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant
```

Claim 结果（摘要）：`task_id=mimo-p5-terminal`，`status=claimed`，`claimed_at=2026-09-24T09:07:43.402029+00:00`。

只读核对文件：

- `frontend/tui/scripts/verify-finding-keys.tsx`（存在，32 行）
- `docs/P5_CLI_ACCEPTANCE_2026-09-24.md`（存在，46 行）

## 2. 结论（先看这里）

| 验收项 | 本轮结论 | 证据等级 |
|---|---|---|
| Shift+Down 物理键 → Windows Terminal 编码 → OpenTUI | **无法验证** | 无物理键注入、无 UI 控制 |
| ConPTY / 合成键路径 | **仅有进程内 mock，不是 ConPTY** | `verify-finding-keys.tsx` |
| 中文 IME 组字 Enter 是否误提交 | **无法验证** | 无 IME / 无候选窗 |
| `verify-finding-keys.tsx` 脚本自身语义复核 | 与验收文档一致，断言合理 | 源码只读 |
| 是否可宣称 P5 终端键位通过 | **否** | — |

**禁止误读**：本报告**不**声称 Shift+Down 或 IME 已在真实 Windows Terminal 通过。上述两项需要真实键盘与真实中文 IME，当前会话不具备该能力。

## 3. 能力探测：能否控制真实 Windows Terminal

探测内容（只读）：

```text
Get-Command WindowsTerminal, wt, pwsh, powershell, conhost, py
Get-Process WindowsTerminal, wt, OpenConsole, conhost
echo WT_SESSION / TERM_PROGRAM / ConEmuANSI / SESSIONNAME
Get-Command AutoHotkey, AutoIt, ahk, nircmd, SendKeys
```

观测：

- `wt.exe` 存在（`C:\Users\21986\AppData\Local\Microsoft\WindowsApps\wt.exe`）。
- `WindowsTerminal` 进程在跑（PID 5052，主窗口标题 `MC | 项目文件与代码浏览`）。
- **本 shell 不在 Windows Terminal 内**：`WT_SESSION` 为空；`TERM_PROGRAM` / `ConEmuANSI` 为空。
- 存在多个 `conhost` / `OpenConsole`，属于当前代理运行时的控制台宿主，**不是**可编程的 WT 键盘注入接口。
- **无任何 UI 自动化工具**（AutoHotkey / AutoIt / nircmd / SendKeys 均不存在）。
- 任务约束禁止读取真实用户配置/密钥/会话，因此也不具备使用用户 WT 配置做注入实验的前提。

### 3.1 输入层级区分（必须分清）

| 层级 | 路径 | 本会话是否触及 | 能否证明物理 Shift+Down |
|---|---|---|---|
| L1 物理键 | HID → WT 键盘编码（含 kitty keyboard / Win32 VK）→ ConPTY VT → OpenTUI 解析 | **否** | 只有 L1 能证明 |
| L2 合成键 | SendInput / UIA / 外部消息注入 → 可能进 WT 或 conhost | **否**（无工具，且即便有也**不是** L1） | 否（最多证明 L2） |
| L3 进程内 mock | OpenTUI `testRender` + `mockInput.pressArrow(...)` | **是**（仅源码阅读；本轮未执行脚本） | **否** |

`verify-finding-keys.tsx` 的 `view.mockInput.pressArrow("down", { shift: true })` 属于 **L3 mock**，**不是** ConPTY 模拟键，更不是物理键。它在渲染器进程内直接派发按键对象，绕过：

1. Windows Terminal 键盘编码，
2. ConPTY/VT 序列化与解析，
3. 终端尺寸/焦点/修饰键状态机。

因此该脚本通过**只能**证明：在给定 mock 事件序列下，`FindingsDialog` 详情视口滚动且不切换 focused finding。它**不能**外推到真实 WT。

### 3.2 IME 为何本轮 100% 不可测

中文 IME 组字（composition）由 TSF/IME 在应用收到最终字符之前处理。验收点是：

> 组字过程中按 Enter，应提交候选/上屏，**不应**触发表单/对话框的 Enter 提交。

该路径依赖：

- 真实 IME（如微软拼音）加载与切换，
- 组字串与候选窗（UI 窗口，非 VT 输出可完整代表），
- IME 与目标 HWND/ConPTY 的消息循环时序。

当前会话没有桌面 UI 控制、没有 IME 切换、没有候选窗注入。`testRender` / PTY / mock **均不能**模拟 IME 候选窗。此项与 `docs/P5_CLI_ACCEPTANCE_2026-09-24.md` §未验收 1 的判断一致。

## 4. 只读源码核对：`verify-finding-keys.tsx`

脚本要点（32 行全文已读）：

- 构造 2 条 finding；第 1 条长详情（`DETAIL TOP` … 18 行 … `DETAIL BOTTOM`），第 2 条详情 `second detail`。
- `testRender(..., { kittyKeyboard: true })`。
- 连续 8 次 `pressArrow("down", { shift: true })`。
- 断言：
  1. 初始帧含 `DETAIL TOP`；
  2. 8 次后 `DETAIL TOP` 移出视口且第 1 条独有内容 `FIRST ONLY LINE` 仍在；
  3. **不**出现 `second detail`（Shift+Down 不得切换 focused finding）；
  4. 帧发生实质变化（滚动发生）。

与 `docs/P5_CLI_ACCEPTANCE_2026-09-24.md`「Finding 键盘事件顺序（模拟，不是物理按键）」一节描述一致。文档已正确标注：

> 测试通过，但**尚不能代表 Windows Terminal 物理按键的实际编码**。

本轮复核同意该保留意见，并进一步明确：mock 层级低于 ConPTY，连 ConPTY 编码路径也未覆盖。

## 5. 与 P5_CLI_ACCEPTANCE 的差异 / 未闭环项

对照 `docs/P5_CLI_ACCEPTANCE_2026-09-24.md` §未验收/阻碍：

1. **IME 组字 Enter** — 本轮仍**无法验证**（见 §3.2）。
2. **物理 Shift+方向键在 WT 中是否被 select 消耗** — 本轮仍**无法验证**（见 §3.1）。
3. 干净离线安装 / GitHub PR 全链路 / 产物提交 — 不在本任务范围（本任务只做终端键位与 IME 可验证性）。

验收文档 §本轮最终复核（2026-09-24）结论「P5 不可标记全完成」仍然成立；本报告**不**推翻该结论。

## 6. 最小用户手测步骤（真实 Windows Terminal + 真实中文 IME）

> 以下需人工在 **Windows Terminal**（确认标题栏为 Windows Terminal，而非旧 conhost）中执行。不要通过远程桌面之外的无头代理伪造结果。

### 6.1 Shift+Down（Finding 详情滚动）

前置：

1. 安装 P5 wheel 或使用已 stage 的 TUI；临时配置，不读用户真实配置/密钥。
2. 打开 **Windows Terminal** 新标签（建议默认 120×30）。
3. 进入 `pr-review chat --tui`，确认页脚为「就绪」。
4. 打开 Findings 对话框，focused 停在**第 1 条** finding（详情较长、顶部可滚动）。

操作与判定：

| 步骤 | 动作 | 期望 | 失败特征 |
|---|---|---|---|
| A | 记录详情首行文本 | 含「顶部」内容 | — |
| B | 按住 **Shift**，按 **↓** 一次 | 详情视口下滚一行 | 无滚动 |
| C | 连续 Shift+↓ 至详情滚出首屏 | 顶部行不可见，底部内容进入 | 顶部永不消失 |
| D | 松开 Shift，单独按 **↓** | focused finding 切换到第 2 条 | Shift+↓ 已切过条目（mock 脚本禁止的行为） |
| E | Shift+↑ 回滚 | 视口回到顶部 | 乱跳条目 |

记录：WT 版本（`wt --version` 或「关于」）、键盘类型（笔记本/外接）、是否开启 kitty keyboard 协议。若 Shift+↓ 被系统/IME/WT 全局快捷键占用，换 `Shift+PgDn` 或记录冲突。

### 6.2 中文 IME 组字 Enter（不误提交）

前置：

1. 同上进入 TUI，焦点在**聊天输入框**。
2. 切换到中文 IME（如微软拼音），确保处于中文模式。

操作与判定：

| 步骤 | 动作 | 期望 | 失败特征 |
|---|---|---|---|
| A | 键入拼音 `ni hao`（不按空格） | 出现组字串/下划线，输入框显示未上屏拼音 | 没有组字态就上屏 |
| B | 组字态按 **Enter** | **仅上屏/确认候选**，消息**不发送** | 对话框提交、消息发出、焦点跳走 |
| C | 组字态按 **Space** | 上屏首选候选，仍不发送 | 空格直接发送 |
| D | 组字完成后按 **Enter** | 此时才发送消息 | 发送不了 |
| E | 英文模式直接输入后 Enter | 正常发送 | — |

务必在 B 步截屏或观察是否出现「已发送」类 UI。若 B 步发送，则为 **P0 输入法缺陷**。

## 7. 未解析的不确定性

1. 本代理会话与用户桌面会话隔离，即使 `WindowsTerminal` 进程存在，也**没有**已授权的窗口/键盘注入通道；未尝试启动 `wt.exe` 以免越权操作用户窗口。
2. `kittyKeyboard: true` 只影响 mock 渲染选项，**未**证明真实 WT 已启用 kitty keyboard 协议。
3. 未执行 `verify-finding-keys.tsx`（只读复核）。历史验收文档记载其在 mock 路径通过；本轮不重复运行、不修改脚本。
4. Shift+Down 在真实 WT 的编码（CSI `1;2B` vs kitty `down`+mods）是否被 OpenTUI 正确解析，只能由 §6.1 的 L1 测试回答。
5. IME 在 Windows Terminal + ConPTY 下的组字 Enter 消息顺序（`VK_PROCESSKEY` / `WM_CHAR` / TSF）对 OpenTUI 输入层的影响未知。

## 8. 最终状态

```text
report --status needs-review
```

原因：真实 Windows Terminal 物理键与中文 IME 组字**无法在本会话验证**；不伪造通过。逻辑层 mock 与验收文档一致，可作为回归护栏，但不能替代 §6 人工手测。
