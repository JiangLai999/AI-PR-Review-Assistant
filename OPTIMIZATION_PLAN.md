# AI PR Review 助手 — 优化计划

> 📅 创建日期：2026-05-30
> 🎯 目标：完成所有问题的修改与优化
> 🤖 协作：Claude Code + GPT 5.4

---

## 阶段 1：安全与一致性（1-2 天）

### 1.1 修复 API Key 安全问题 ✅

**问题**：
- API Key 明文保存到配置文件
- `config show` 明文输出 API Key

**解决方案**：
- 默认不持久化 API Key，只从环境变量读取
- `config show` 必须掩码输出（如 `sk-***abcd`）
- 显式 `--save-key` 才允许保存到文件
- 保存文件前检查权限

**预计工作量**：0.5-1 天

---

### 1.2 修复 README 真实性 ✅

**问题**：
- tree-sitter 上下文增强（实际是 regex fallback）
- SQLite 存储层（未接入主流程）
- GitHub Comment 渲染（用的是 Markdown）
- FastAPI badge（实际是 CLI 项目）

**解决方案**：
- 更新 README 为"真实状态"
- 区分"已实现"、"已实现但未启用"、"计划中"
- 删除或降级尚未落地的完成标记

**预计工作量**：0.5-1 天

---

### 1.3 修复重复 API 调用 ✅

**问题**：
- `PRFetcher._fetch_files()` 文件列表拉取两次
- 位置：`pr_fetcher.py:200-208`

**解决方案**：
- 删除冗余请求
- 补调用次数测试

**预计工作量**：0.5 天

---

### 1.4 切换 GitHub Comment 渲染路径 ✅

**问题**：
- 专用渲染器存在但未使用
- 发布评论时用的是 Markdown 渲染

**解决方案**：
- 发布评论路径切到专用渲染器
- 补 CLI 测试

**预计工作量**：0.5 天

---

### 1.5 补全默认过滤规则 ✅

**问题**：
- `tests/`、`test_*.py` 未默认排除

**解决方案**：
- 扩展默认 pattern
- 补测试

**预计工作量**：0.5 天

---

## 阶段 2：功能完善（2-4 天）

### 2.1 接入 ResultStore ✅

**问题**：
- 已实现但未使用，运行历史断裂

**解决方案**：
- 在 review 结束后持久化结果和元信息
- 增加 `pr-review history` 命令

**预计工作量**：1-2 天

---

### 2.2 补关键集成测试 ✅

**问题**：
- 安全、评论渲染、存储接线测试缺失

**解决方案**：
- 增加 CLI end-to-end stub 集成测试
- 覆盖主流程、配置安全、评论渲染

**预计工作量**：2-3 天

---

### 2.3 补 provider 安全校验 ✅

**问题**：
- 任意 endpoint 可带 key 发请求

**解决方案**：
- 强制 HTTPS 校验
- custom provider 风险提示
- allowlist

**预计工作量**：1 天

---

### 2.4 清理配置接线不完整问题 ✅

**问题**：
- `AppConfig` 包含 `cost_controller`、`result_store`、`report_renderer`
- 但主流程没有完整消费这些配置

**解决方案**：
- 明确"哪些配置会实际生效"
- 优先让 `report_renderer`、`result_store`、`cost_controller` 接入主流程

**预计工作量**：1 天

---

## 阶段 3：架构优化（3-7 天）

### 3.1 引入 orchestrator ✅

**问题**：
- CLI 兼任 orchestration 层
- 耦合过高，难以扩展

**解决方案**：
- 抽取 `ReviewOrchestrator` 类
- CLI 只负责参数解析和调用
- 支持 FastAPI、GitHub Action、定时任务复用

**预计工作量**：1-1.5 天

---

### 3.2 做受控并发性能优化 ✅

**问题**：
- 主流程完全串行，是最大性能瓶颈

**解决方案**：
- 引入受控并发（`asyncio.Semaphore`）
- 文件内容获取可并发
- AI 调用可用 Semaphore 控制并发数
- 同时评审 2-4 个文件

**预计工作量**：2-4 天

---

### 3.3 决定 tree-sitter 策略 ✅

**问题**：
- README 声称完成，但实际是 regex fallback

**解决方案**：
- 选项 A：真正实现 tree-sitter（3-7 天）
- 选项 B：降级为 roadmap，承认 regex-first

**预计工作量**：0.5 天（决策）或 3-7 天（实现）

---

### 3.4 补 CLI 高级能力 ✅

**问题**：
- 缺少调试和辅助功能

**解决方案**：
- 增加 `--dry-run`
- 增加 `--only-fetch`
- 增加 `--only-filter`
- 增加 `--show-filter-reasons`
- 增加 `pr-review history`
- 增加 `pr-review stats`

**预计工作量**：1-2 天

---

## 总工作量估算

| 阶段 | 工作量 | 优先级 |
|------|--------|--------|
| 阶段 1 | 2-3 天 | 🔴 高 |
| 阶段 2 | 5-7 天 | 🟡 中 |
| 阶段 3 | 5-10 天 | 🟢 低 |
| **总计** | **12-20 天** | - |

---

**开始执行！**
