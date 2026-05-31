# Demo Walkthrough

本文件用于演示当前项目的核心能力，适合评审或路演时顺序操作。

## 1. 初始化配置

```bash
pr-review config
```

推荐演示点：

- 选择 provider
- 输入 API Key
- 选择界面语言与聊天布局
- 完成保存后直接运行 `config show`

## 2. 检查配置与模型

```bash
pr-review config show
pr-review config test
pr-review config health
pr-review config health --discover-models
pr-review config models
```

推荐演示点：

- 配置来源显示
- API Key 掩码显示
- provider 健康检查
- 模型发现和 fallback 提示

## 3. 运行 PR Review

```bash
pr-review https://github.com/owner/repo/pull/42
```

推荐演示点：

- 终端报告
- 过滤摘要
- 结果持久化

## 4. 使用 Chat Workspace

```bash
pr-review chat
```

推荐演示命令：

```text
/help
/config
/session
/model <模型ID>
/review <PR_URL>
/history
/stats
/clear
/exit
```

## 5. 查看历史与统计

```bash
pr-review history --limit 10
pr-review stats
```

推荐演示点：

- 最近 run 列表
- 统计信息
- 模型、成本、持续时间等元数据
