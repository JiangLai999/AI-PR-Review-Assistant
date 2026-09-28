# 阶段九：CLI / OpenTUI 测试与比赛验收矩阵

> 目标：在不改造 WebUI 的前提下，验证 CLI / OpenTUI、Python 审查引擎、本地模型和第三方 API 的完整链路。

## 自动化门禁

| 检查 | 命令 | 通过条件 |
|---|---|---|
| Python 全量测试 | `python -m pytest -q` | 所有测试通过，仅允许明确标注的 skip |
| Python 类型检查 | `.venv313\Scripts\mypy.exe src` | 无 error |
| OpenTUI 类型检查 | `npm run typecheck` | tsc 返回 0 |
| Diff 检查 | `git diff --check` | 无空白错误 |

## 功能验收矩阵

| 场景 | 操作 | 预期结果 |
|---|---|---|
| 首次启动 | `pr-review chat --tui` | OpenTUI 首页正常显示 |
| 后端健康 | 启动后等待状态 | 底部状态从 CONNECTING 进入 READY 或 FALLBACK |
| 配置助手 | `Ctrl+P` | 方向键选择运行时，Enter 保存，Esc 取消 |
| 模型状态 | `/model status` | 显示 Provider、模型、Endpoint、可用性和建议 |
| 模型切换 | `Ctrl+K` | 列表选择模型并持久化 |
| 新会话 | `/new` | 消息、Finding、报告和进度清空 |
| PR URL | 粘贴 GitHub PR URL | 弹出确认，不直接启动 |
| 审查进度 | 确认审查 | 阶段、文件和百分比实时更新 |
| 取消 | 审查中按 Esc / Ctrl+C | 状态进入取消并恢复 READY |
| 失败重试 | `/retry` 或 Ctrl+R | 使用上次 PR URL 重新执行 |
| Finding | Ctrl+O | Finding 列表、分页、详情和证据可查看；Shift+↑↓ 滚动详情 |
| 历史 | Ctrl+L / `/history` | 可选择 Run 并恢复报告 |
| 导出 | `/export json <path>` | 生成 JSON 文件 |
| 降级 | 关闭 Ollama / 缺失 API Key | 错误分类、恢复建议和切换入口可见 |

## 性能验收

- 单个 Chat session 保留最近 40 条消息。
- 单条输入、输出和 Finding 文本有长度上限。
- Finding 详情按页渲染，每页 8 条。
- 审查任务最长运行 30 分钟。
- 单 session 进度事件设置上限，重复进度事件可丢弃，完成/失败/取消事件不可丢失。
- OpenTUI 退出时回收 Python 后端进程和 pending 请求。

## 竞赛演示主路径

```text
pr-review chat --tui
  -> Ctrl+P 选择 Local / Cloud
  -> 粘贴 GitHub PR URL
  -> Enter 开始审查
  -> 展示实时阶段与文件进度
  -> 展示 Finding 统计
  -> Ctrl+O 查看证据与修复建议
  -> /export markdown ./reports/demo.md
```

## 2026-09-22 实际验收记录

- OpenTUI + Bun 启动：通过。
- MiMo 风格首页渲染：通过。
- `/setup` 命令识别和命令提示面板：通过。
- Python JSONL `health` / `config.snapshot` / `model.status`：通过。
- 云端 API Key 未配置：正确返回 OFFLINE 与恢复建议。
- Ollama 服务不可用：正确返回本地模型不可用与切换建议。
- Ollama CLI 自动启动受本机 `C:\Users\21986\AppData\Local\Ollama` 日志权限限制，未将其误判为应用崩溃；降级与错误分类链路通过。
- 自动化门禁：375 passed，1 skipped；OpenTUI typecheck、mypy、diff check 均通过。

外部服务不可用场景以“可识别、可解释、可恢复”为验收标准，不把第三方服务状态误计为应用缺陷。
